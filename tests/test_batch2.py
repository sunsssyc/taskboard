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
        CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT, metric TEXT, created_at TEXT NOT NULL);
        INSERT INTO projects VALUES ('demo','老库',NULL,NULL,0,'2026-01-01','2026-01-01');
        INSERT INTO tasks (project, ref, title, created_at, updated_at)
            VALUES ('demo', 1, '老任务', '2026-01-01', '2026-01-01');
        INSERT INTO notes (project, kind, title, created_at)
            VALUES ('demo', 'finding', '老结论', '2026-01-01');
    """)
    conn.commit()
    conn.close()

    store = Store(db_path)
    try:
        task = store.add_task('demo', '新任务', accept='验收条件', branch='b', pr='1')
        assert task['ref'] == 2
        assert store.get_task('demo', 1)['accept'] is None   # 老数据保持原样
        assert store.get_note(1)['category'] is None
        assert store.set_note_category(1, '历史口径')['category'] == '历史口径'
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


# ── 项目切换 ────────────────────────────────────────────────────────────

def test_overview_cards_are_toggle_buttons_with_sections_tagged(tmp_path):
    store = Store(tmp_path / 'switch.db')
    store.create_project('alpha', '项目甲')
    store.create_project('beta', '项目乙')
    store.add_task('alpha', '甲的活')
    store.add_note('beta', 'finding', '乙的结论')
    html = render(store.snapshot())
    store.close()

    # 卡片是按钮而非锚点:页面常被宿主整高渲染,#锚点跳转不会滚动
    assert '<button type="button" class="pcard" data-project="alpha"' in html
    assert 'href="#p-alpha"' not in html
    # 每个 section 都带项目归属,切换时才能整组显隐
    assert html.count('data-project="beta"') >= 3   # 卡片 + 任务区 + 结论区
    # display:flex 会压过 UA 的 [hidden]{display:none},必须显式盖回来
    assert 'section[hidden] { display:none; }' in html


def test_single_project_keeps_explicit_all_projects_context(tmp_path):
    store = Store(tmp_path / 'one.db')
    store.create_project('solo', '独苗')
    html = render(store.snapshot())
    store.close()
    assert 'class="pcard all-projects" data-project="" aria-pressed="true"' in html
    assert '<h3>全部项目</h3><div class="key">1 projects</div>' in html


def test_sidebar_outline_lists_focus_tasks_under_project(tmp_path):
    store = Store(tmp_path / 'outline.db')
    store.create_project('alpha', '项目甲')
    store.add_task('alpha', '已完成的不进大纲')
    store.set_status('alpha', 1, 'done')
    store.add_task('alpha', '被阻塞的不进大纲')
    store.add_task('alpha', '阻塞源')
    store.add_dep('alpha', 2, 3)
    store.add_task('alpha', '等人工的活')
    store.set_status('alpha', 4, 'waiting')
    store.add_task('alpha', '进行中的活')
    store.set_status('alpha', 5, 'active')
    store.add_task('alpha', '可开工的待办')
    html = render(store.snapshot())
    store.close()

    # 大纲组包着项目卡与任务行
    assert '<div class="pgroup" data-project="alpha">' in html
    assert 'class="ptasks"' in html
    # 进行中 → 等人工 → 可开工待办;完成与被阻塞的不出现
    active_at = html.index('class="ptask" data-project="alpha" data-ref="5"')
    waiting_at = html.index('class="ptask" data-project="alpha" data-ref="4"')
    todo_at = html.index('class="ptask" data-project="alpha" data-ref="6"')
    assert active_at < waiting_at < todo_at
    assert 'data-ref="1"' not in html.split('class="ptasks"')[1].split('</div>')[0]
    assert 'data-ref="2"' not in html.split('class="ptasks"')[1].split('</div>')[0]
    # 任务行要带状态圆点与 ref,主区卡片也要带 data-ref 才能被定位
    assert '<i class="dot active"></i><span class="ref">#5</span>' in html
    assert '<div class="step" data-filter-item data-ref="5"' in html


def test_sidebar_outline_caps_rows_with_overflow_count(tmp_path):
    store = Store(tmp_path / 'cap.db')
    store.create_project('mega', '大项目')
    for index in range(9):
        store.add_task('mega', f'第 {index + 1} 件')
    html = render(store.snapshot())
    store.close()
    assert html.count('class="ptask" data-project="mega"') == 7
    assert 'class="ptask more" data-project="mega">还有 2 项…</button>' in html


def test_secondary_active_is_folded_but_expands_to_full_cards(tmp_path):
    store = Store(tmp_path / 'fold.db')
    store.create_project('alpha', '项目甲')
    store.add_task('alpha', '第一张进行中摊开', detail='主任务正文')
    store.add_task('alpha', '第二张进行中折起', detail='第二张正文')
    store.add_task('alpha', '第三张进行中折起', detail='第三张正文')
    store.add_task('alpha', '普通待办')
    for ref in (1, 2, 3):
        store.set_status('alpha', ref, 'active')
    html = render(store.snapshot())
    store.close()

    section = html.split('data-kind="tasks"', 1)[1]
    ref1 = section.index('data-ref="1"')
    ref2 = section.index('data-ref="2"')
    ref3 = section.index('data-ref="3"')
    ref4 = section.index('data-ref="4"')
    fold_at = section.index('<details class="active-fold">')
    assert ref1 < fold_at < ref2 < ref3 < ref4
    assert '主任务正文' in section[ref1:fold_at]
    folded_active = section[fold_at:ref4]
    assert '还有 2 项进行中 · 第二张进行中折起、第三张进行中折起' in folded_active
    assert '第二张正文' in folded_active and '第三张正文' in folded_active
    assert folded_active.count('class="task-body" hidden') == 2
    assert folded_active.count('class="task-disclosure" aria-expanded="false"') == 2
    assert '展开全部' not in section
    # 普通待办没有正文,仍然自然收成单行。
    assert section[ref4:].count('class="task-body"') == 0


def test_primary_active_prefers_actionable_and_secondary_is_title_only(tmp_path):
    store = Store(tmp_path / 'active-priority.db')
    store.create_project('alpha', '项目甲')
    store.add_task('alpha', '未完成前置')
    store.add_task('alpha', '被阻塞的进行中', detail='次要任务正文', blocked_by=[1])
    store.set_status('alpha', 2, 'active')
    store.add_task('alpha', '可执行的进行中', detail='主任务完整正文')
    store.set_status('alpha', 3, 'active')
    store.add_task('alpha', '被阻塞的待办', blocked_by=[1])
    html = render(store.snapshot(), live=True)
    store.close()

    section = html.split('data-kind="tasks"', 1)[1]
    # ref=3 虽然后创建,但可执行,必须提升为完全展开的主任务。
    primary_at = section.index('data-ref="3"')
    active_fold_at = section.index('<details class="active-fold">')
    secondary_at = section.index('data-ref="2"')
    blocked_at = section.index('<details class="blocked-fold">')
    assert primary_at < active_fold_at < secondary_at < section.index('data-ref="1"') < blocked_at
    assert blocked_at < section.index('data-ref="4"', blocked_at)
    assert '主任务完整正文' in section[primary_at:secondary_at]

    secondary = section[active_fold_at:section.index('data-ref="1"')]
    assert '次要任务正文' in secondary
    assert 'class="task-body" hidden' in secondary
    assert 'class="task-disclosure" aria-expanded="false"' in secondary
    assert 'class="chip active"' in secondary


def test_waiting_ready_are_compact_and_blocked_dropped_are_folded(tmp_path):
    store = Store(tmp_path / 'solo.db')
    store.create_project('alpha', '项目甲')
    store.add_task('alpha', '唯一的进行中', detail='唯一完整正文')
    store.set_status('alpha', 1, 'active')
    store.add_task('alpha', '等人工标题', detail='等人工正文')
    store.set_status('alpha', 2, 'waiting')
    store.add_task('alpha', '可开工标题', detail='可开工正文')
    store.add_task('alpha', '被阻塞标题', detail='被阻塞正文', blocked_by=[3])
    store.add_task('alpha', '已放弃标题', detail='已放弃正文')
    store.set_status('alpha', 5, 'dropped')
    html = render(store.snapshot())
    store.close()

    section = html.split('data-kind="tasks"', 1)[1]
    assert '唯一完整正文' in section[:section.index('data-ref="2"')]
    waiting_at = section.index('data-ref="2"')
    ready_at = section.index('data-ref="3"')
    blocked_at = section.index('<details class="blocked-fold">')
    assert waiting_at < ready_at < blocked_at
    queue = section[waiting_at:blocked_at]
    assert '等人工正文' in queue and '可开工正文' in queue
    assert queue.count('class="task-body" hidden') == 2
    assert queue.count('class="task-disclosure" aria-expanded="false"') == 2
    assert '<details class="blocked-fold">' in section
    assert '<summary>还有 1 项被阻塞待办</summary>' in section
    assert '被阻塞正文' in section
    assert '<details class="dropped-fold">' in section
    assert '<summary>已放弃 1 项</summary>' in section
    assert '已放弃正文' in section
