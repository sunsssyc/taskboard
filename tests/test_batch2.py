"""第二批功能:waiting 状态、brief、find、stale、accept、git 关联、
artifact url、并发写安全、已完成折叠。"""
import sqlite3
import threading

import pytest

from taskboard.cli import main
from taskboard.render import render
from taskboard.store import Store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('TASKBOARD_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('NO_COLOR', '1')
    return str(tmp_path / 'board.db')


def run(db, *argv) -> int:
    return main(['--db', db, *argv])


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / 'store.db')
    s.create_project('demo', '示例项目')
    yield s
    s.close()


# ── waiting ────────────────────────────────────────────────────────────

def test_waiting_task_is_not_actionable_but_counts_as_open(store):
    task = store.add_task('demo', '等你在服务器上跑')
    store.set_status('demo', task['ref'], 'waiting')

    project = store.snapshot()['projects'][0]
    assert project['counts']['waiting'] == 1
    assert project['tasks'][0]['actionable'] is False   # 等的是人,不是我能开工的
    assert project['waiting'] == [task['ref']]


def test_next_separates_waiting_and_owner_filter(db, capsys):
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'add', '我能做的', '--owner', '我', '-p', 'demo')
    run(db, 'add', '你要跑的', '--owner', '你', '-p', 'demo')
    run(db, 'wait', '2', '-p', 'demo')
    capsys.readouterr()

    run(db, 'next', '-p', 'demo')
    out = capsys.readouterr().out
    assert '我能做的' in out and '等人工' in out and '你要跑的' in out

    run(db, 'next', '--owner', '我', '-p', 'demo')
    out = capsys.readouterr().out
    assert '我能做的' in out and '你要跑的' not in out


# ── brief ──────────────────────────────────────────────────────────────

def test_brief_covers_state_next_and_findings(db, capsys):
    run(db, 'init', 'demo', '--name', '示例项目', '--summary', '一句话说明')
    run(db, 'add', '进行中的事', '-p', 'demo')
    run(db, 'add', '等你的事', '-p', 'demo')
    run(db, 'add', '可开工的事', '-p', 'demo')
    run(db, 'start', '1', '-p', 'demo')
    run(db, 'wait', '2', '-p', 'demo')
    run(db, 'finding', '已定结论', '--metric', '40/40', '-p', 'demo')
    run(db, 'risk', '一条尾巴', '-p', 'demo')
    run(db, 'set', '--artifact-url', 'https://example.com/board', '-p', 'demo')
    capsys.readouterr()

    run(db, 'brief', '-p', 'demo')
    out = capsys.readouterr().out
    assert '一句话说明' in out
    assert '进行中' in out and '进行中的事' in out
    assert '可开工' in out and '可开工的事' in out
    assert '等人工' in out and '等你的事' in out
    assert '已定结论' in out and '40/40' in out
    assert '一条尾巴' in out
    assert 'https://example.com/board' in out


def test_brief_omits_superseded_findings(db, capsys):
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'finding', '旧结论', '-p', 'demo')
    run(db, 'finding', '新结论', '--supersedes', '1', '-p', 'demo')
    capsys.readouterr()

    run(db, 'brief', '-p', 'demo')
    out = capsys.readouterr().out
    assert '新结论' in out and '旧结论' not in out


# ── find / stale ───────────────────────────────────────────────────────

def test_find_matches_tasks_and_notes_case_insensitively(store):
    store.add_task('demo', '跑 Export 脚本', detail='服务器执行')
    store.add_note('demo', 'finding', '导出口径已定', body='用 EXPORT 模型')
    store.add_task('demo', '无关任务')

    result = store.search('export')
    assert [t['title'] for t in result['tasks']] == ['跑 Export 脚本']
    assert [n['title'] for n in result['notes']] == ['导出口径已定']


def test_find_searches_accept_field_and_scopes_by_project(store):
    store.create_project('other', '另一个')
    store.add_task('demo', '任务甲', accept='跨月分位稳定')
    store.add_task('other', '任务乙', accept='跨月分位稳定')

    assert len(store.search('跨月')['tasks']) == 2
    assert len(store.search('跨月', project='demo')['tasks']) == 1


def test_stale_only_reports_idle_in_progress_tasks(store):
    fresh = store.add_task('demo', '刚动过')
    store.set_status('demo', fresh['ref'], 'active')
    old_active = store.add_task('demo', '很久没动')
    store.set_status('demo', old_active['ref'], 'active')
    old_todo = store.add_task('demo', '没开工的老任务')
    store.conn.execute(
        "UPDATE tasks SET updated_at = '2026-01-01T00:00:00+00:00' WHERE ref IN (?, ?)",
        (old_active['ref'], old_todo['ref']),
    )
    store.conn.commit()

    stale = store.stale_tasks(days=3)
    assert [t['ref'] for t in stale] == [old_active['ref']]  # todo 不算停滞:它本来就没开工
    assert stale[0]['idle_days'] > 3


# ── accept / git ───────────────────────────────────────────────────────

def test_done_prints_accept_criteria(db, capsys):
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'add', '带验收的任务', '--accept', '三张审计表全过', '-p', 'demo')
    capsys.readouterr()
    run(db, 'done', '1', '-p', 'demo')
    assert '三张审计表全过' in capsys.readouterr().out


def test_done_records_commit_sha_in_events(db, capsys, monkeypatch):
    import taskboard.cli as cli

    monkeypatch.setattr(cli, 'git_head_sha', lambda *_a, **_k: 'abc1234')
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'add', '要提交的活', '-p', 'demo')
    run(db, 'done', '1', '-p', 'demo')
    capsys.readouterr()

    store = Store(db)
    try:
        payloads = [event['payload'] for event in store.events(limit=10, project='demo')]
    finally:
        store.close()
    assert any('abc1234' in (payload or '') for payload in payloads)


def test_branch_and_pr_round_trip(db, capsys):
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'add', '带分支的活', '--branch', 'codex/foo', '--pr', '96', '-p', 'demo')
    capsys.readouterr()
    run(db, 'show', '1', '-p', 'demo')
    out = capsys.readouterr().out
    assert 'codex/foo' in out and 'PR 96' in out


# ── artifact url / export ──────────────────────────────────────────────

def test_export_reminds_existing_artifact_url(db, tmp_path, capsys):
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'set', '--artifact-url', 'https://example.com/b', '-p', 'demo')
    capsys.readouterr()
    run(db, 'export', '--out', str(tmp_path / 'out.html'))
    assert 'https://example.com/b' in capsys.readouterr().out


# ── 并发 ───────────────────────────────────────────────────────────────

def test_concurrent_add_task_allocates_unique_refs(tmp_path):
    db_path = tmp_path / 'race.db'
    setup = Store(db_path)
    setup.create_project('demo', '并发')
    setup.close()

    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def worker(index: int):
        store = Store(db_path)
        try:
            barrier.wait(timeout=5)
            store.add_task('demo', f'并发任务 {index}')
        except Exception as exc:  # noqa: BLE001 - 收集后统一断言
            errors.append(exc)
        finally:
            store.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    store = Store(db_path)
    try:
        refs = [task['ref'] for task in store.tasks('demo')]
    finally:
        store.close()
    assert sorted(refs) == list(range(1, 9))  # 无重号、无跳号


def test_wal_mode_enabled(tmp_path):
    store = Store(tmp_path / 'wal.db')
    try:
        mode = store.conn.execute('PRAGMA journal_mode').fetchone()[0]
    finally:
        store.close()
    assert mode.lower() == 'wal'


def test_legacy_db_gets_all_new_columns(tmp_path):
    db_path = tmp_path / 'legacy.db'
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE projects (key TEXT PRIMARY KEY, name TEXT NOT NULL, repo TEXT,
            summary TEXT, archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL,
            ref INTEGER NOT NULL, title TEXT NOT NULL, detail TEXT,
            status TEXT NOT NULL DEFAULT 'todo', owner TEXT, gate INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (project, ref));
        INSERT INTO projects VALUES ('demo','老库',NULL,NULL,0,'2026-01-01','2026-01-01');
        INSERT INTO tasks (project, ref, title, created_at, updated_at)
            VALUES ('demo', 1, '老任务', '2026-01-01', '2026-01-01');
    """)
    conn.commit()
    conn.close()

    store = Store(db_path)
    try:
        task = store.add_task('demo', '新任务', accept='验收条件', branch='b', pr='1')
        assert task['ref'] == 2
        assert store.get_task('demo', 1)['accept'] is None   # 老数据保持原样
        store.update_project('demo', artifact_url='https://example.com')
        assert store.get_project('demo')['artifact_url'] == 'https://example.com'
    finally:
        store.close()


# ── 渲染 ───────────────────────────────────────────────────────────────

def test_render_folds_done_tasks_and_shows_accept(store):
    done = store.add_task('demo', '做完的活')
    store.set_status('demo', done['ref'], 'done')
    store.add_task('demo', '在办的活', accept='跨月分位稳定')
    waiting = store.add_task('demo', '等人工的活')
    store.set_status('demo', waiting['ref'], 'waiting')

    html = render(store.snapshot())
    assert '<details class="done-fold">' in html
    assert '已完成 1 项' in html
    assert '跨月分位稳定' in html
    assert '等人工' in html
