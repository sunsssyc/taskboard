import subprocess

import pytest

from taskboard.store import (
    BoardError, Store, load_view_prefs, save_view_prefs, view_prefs_path,
)


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / 'board.db')
    s.create_project('demo', '示例项目', repo=str(tmp_path / 'repo'), summary='一句话')
    yield s
    s.close()


def test_task_refs_increment_per_project(store, tmp_path):
    store.create_project('other', '另一个', repo=str(tmp_path / 'other'))
    a = store.add_task('demo', '第一件')
    b = store.add_task('demo', '第二件')
    c = store.add_task('other', '别的项目第一件')
    assert (a['ref'], b['ref'], c['ref']) == (1, 2, 1)


def test_task_priority_defaults_persists_and_can_change(store):
    default = store.add_task('demo', '默认优先级')
    urgent = store.add_task('demo', '紧急任务', priority=0)

    assert default['priority'] == 2
    assert urgent['priority'] == 0
    updated = store.update_task('demo', default['ref'], priority=1)
    assert updated['priority'] == 1
    snapshot = store.snapshot()['projects'][0]
    assert {task['ref']: task['priority'] for task in snapshot['tasks']} == {
        default['ref']: 1,
        urgent['ref']: 0,
    }

    with pytest.raises(BoardError, match='P0/P1/P2/P3'):
        store.add_task('demo', '非法优先级', priority=4)


def test_opening_old_database_migrates_tasks_to_default_priority(tmp_path):
    import sqlite3

    path = tmp_path / 'legacy.db'
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE projects (key TEXT PRIMARY KEY, name TEXT NOT NULL, repo TEXT,
          summary TEXT, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL,
          ref INTEGER NOT NULL, title TEXT NOT NULL, detail TEXT, status TEXT NOT NULL,
          owner TEXT, gate INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, UNIQUE(project, ref));
        INSERT INTO projects VALUES ('demo', 'Demo', NULL, NULL, 0, 'now', 'now');
        INSERT INTO tasks (project, ref, title, status, gate, created_at, updated_at)
          VALUES ('demo', 1, '旧任务', 'todo', 0, 'now', 'now');
    """)
    connection.commit()
    connection.close()

    migrated = Store(path)
    try:
        assert migrated.get_task('demo', 1)['priority'] == 2
        assert migrated.snapshot()['projects'][0]['tasks'][0]['priority'] == 2
    finally:
        migrated.close()


def test_duplicate_project_rejected(store):
    with pytest.raises(BoardError):
        store.create_project('demo', '重复')


def test_blocked_task_is_not_actionable_until_blocker_done(store):
    first = store.add_task('demo', '前置')
    second = store.add_task('demo', '后置', blocked_by=[first['ref']])

    snapshot = store.snapshot()['projects'][0]
    by_ref = {task['ref']: task for task in snapshot['tasks']}
    assert by_ref[second['ref']]['open_blockers'] == [first['ref']]
    assert by_ref[second['ref']]['actionable'] is False
    assert by_ref[first['ref']]['actionable'] is True
    assert by_ref[first['ref']]['blocks'] == [second['ref']]

    store.set_status('demo', first['ref'], 'done')
    by_ref = {t['ref']: t for t in store.snapshot()['projects'][0]['tasks']}
    assert by_ref[second['ref']]['open_blockers'] == []
    assert by_ref[second['ref']]['actionable'] is True


def test_dependency_cycle_rejected(store):
    a = store.add_task('demo', 'A')
    b = store.add_task('demo', 'B', blocked_by=[a['ref']])
    with pytest.raises(BoardError):
        store.add_dep('demo', a['ref'], b['ref'])


def test_self_dependency_rejected(store):
    task = store.add_task('demo', '自己')
    with pytest.raises(BoardError):
        store.add_dep('demo', task['ref'], task['ref'])


def test_project_for_path_prefers_most_specific(store, tmp_path):
    outer = tmp_path / 'repo'
    inner = outer / 'nested'
    inner.mkdir(parents=True)
    store.create_project('nested', '子项目', repo=str(inner))

    assert store.project_for_path(inner)['key'] == 'nested'
    assert store.project_for_path(outer)['key'] == 'demo'
    assert store.project_for_path(tmp_path) is None


def test_workstream_and_task_repository_associations(store, tmp_path):
    backend = tmp_path / 'coinex_backend'
    admin = tmp_path / 'coinex_admin_frontend'
    backend.mkdir()
    admin.mkdir()
    store.create_project(
        'cross-repo', '跨仓库需求', repositories=[str(backend), str(admin)],
    )

    assert [row['name'] for row in store.project_repositories('cross-repo')] == [
        'coinex_admin_frontend', 'coinex_backend',
    ]
    task = store.add_task(
        'cross-repo', '只改后端', repositories=['coinex_backend'],
    )
    assert [row['name'] for row in store.task_repositories('cross-repo', task['ref'])] == [
        'coinex_backend',
    ]
    snapshot = next(
        project for project in store.snapshot()['projects'] if project['key'] == 'cross-repo'
    )
    assert [repo['name'] for repo in snapshot['repositories']] == [
        'coinex_admin_frontend', 'coinex_backend',
    ]
    assert [repo['name'] for repo in snapshot['tasks'][0]['repositories']] == [
        'coinex_backend',
    ]
    reopened = Store(store.path)
    try:
        assert [
            repo['name'] for repo in reopened.task_repositories('cross-repo', task['ref'])
        ] == ['coinex_backend']
    finally:
        reopened.close()
    with pytest.raises(BoardError, match='未关联到需求'):
        store.add_task('cross-repo', '越界仓库', repositories=['unknown'])
    with pytest.raises(BoardError, match='仍被任务'):
        store.set_project_repositories('cross-repo', [str(admin)])
    with pytest.raises(BoardError, match='仍被任务'):
        store.update_project('cross-repo', repo=str(admin))
    assert [row['name'] for row in store.project_repositories('cross-repo')] == [
        'coinex_admin_frontend', 'coinex_backend',
    ]


def test_shared_repository_requires_explicit_workstream(store, tmp_path):
    shared = tmp_path / 'shared'
    shared.mkdir()
    store.create_project('shared-a', '需求 A', repositories=[str(shared)])
    store.create_project('shared-b', '需求 B', repositories=[str(shared)])

    assert {row['key'] for row in store.projects_for_path(shared)} == {'shared-a', 'shared-b'}
    assert store.project_for_path(shared) is None


def test_move_repository_keeps_existing_task_associations(store, tmp_path):
    old = tmp_path / 'claude-taskboard'
    old.mkdir()
    store.create_project('tb', '看板', repositories=[str(old)])
    task = store.add_task('tb', '既有任务')
    new = tmp_path / 'taskboard'
    old.rename(new)

    # 换路径这件事 set --repo 做不到:旧路径不在新集合里就被当成解除关联
    with pytest.raises(BoardError, match='仍被任务'):
        store.set_project_repositories('tb', [str(new)])

    result = store.move_repository(str(old), str(new))

    assert result['previous_name'] == 'claude-taskboard'
    assert (result['projects'], result['tasks'], result['merged']) == (['tb'], 1, False)
    assert [row['name'] for row in store.project_repositories('tb')] == ['taskboard']
    assert [row['path'] for row in store.project_repositories('tb')] == [str(new)]
    assert [row['name'] for row in store.task_repositories('tb', task['ref'])] == ['taskboard']
    assert store.project_for_path(new)['key'] == 'tb'
    # 旧的单 repo 兼容字段也跟上,避免和关联表两处不一致
    assert store.get_project('tb')['repo'] == str(new)


def test_move_repository_requires_merge_when_target_registered(store, tmp_path):
    old = tmp_path / 'old'
    new = tmp_path / 'new'
    old.mkdir()
    new.mkdir()
    store.create_project('p1', 'P1', repositories=[str(old)])
    store.create_project('p2', 'P2', repositories=[str(new)])
    task = store.add_task('p1', '旧仓库任务')

    with pytest.raises(BoardError, match='--merge'):
        store.move_repository(str(old), str(new))

    result = store.move_repository(str(old), str(new), merge=True)

    assert result['merged'] is True
    assert [row['path'] for row in store.project_repositories('p1')] == [str(new)]
    assert [row['name'] for row in store.task_repositories('p1', task['ref'])] == ['new']
    # 旧登记行已合并掉,不再留下一条指向不存在路径的仓库
    assert str(old) not in [row['path'] for row in store.repositories()]


def test_move_repository_guards_missing_target_and_flags_name_clash(store, tmp_path):
    first = tmp_path / 'a' / 'foo'
    second = tmp_path / 'b' / 'bar'
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    store.create_project('clash', '同名', repositories=[str(first), str(second)])
    store.add_task('clash', '两个仓库', repositories=['foo', 'bar'])

    with pytest.raises(BoardError, match='不存在或不是目录'):
        store.move_repository(str(second), str(tmp_path / 'c' / 'foo'))

    renamed = tmp_path / 'c' / 'foo'
    renamed.parent.mkdir()
    second.rename(renamed)
    result = store.move_repository(str(second), str(renamed))

    # 改完两个仓库同名,按名字选仓库会歧义,调用方需要提示用户改传路径
    assert result['conflicts'] == ['clash']
    with pytest.raises(BoardError, match='不唯一'):
        store.add_task('clash', '按名字选', repositories=['foo'])
    assert store.add_task('clash', '按路径选', repositories=[str(renamed)])['ref']


def test_move_repository_force_accepts_absent_target(store, tmp_path):
    old = tmp_path / 'present'
    old.mkdir()
    store.create_project('later', '还没落地', repositories=[str(old)])
    target = tmp_path / 'not-yet'

    store.move_repository(str(old), str(target), force=True)

    assert [row['path'] for row in store.project_repositories('later')] == [str(target)]

def _git(repo, *argv):
    subprocess.run(
        ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t', *argv],
        check=True, capture_output=True,
    )


def _git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, 'init', '-q')
    _git(path, 'commit', '-q', '--allow-empty', '-m', 'init')
    return path


def _head(repo):
    return subprocess.run(
        ['git', '-C', str(repo), 'rev-parse', '--short', 'HEAD'],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_task_commit_range_is_recorded_per_repository(store, tmp_path):
    backend = _git_repo(tmp_path / 'backend')
    frontend = _git_repo(tmp_path / 'frontend')
    store.create_project('cross', '跨仓库', repositories=[str(backend), str(frontend)])
    task = store.add_task('cross', '改两个仓库')

    store.set_status('cross', task['ref'], 'active')
    base = {'backend': _head(backend), 'frontend': _head(frontend)}
    _git(backend, 'commit', '-q', '--allow-empty', '-m', '后端改动')
    _git(frontend, 'commit', '-q', '--allow-empty', '-m', '前端改动')
    store.set_status('cross', task['ref'], 'done')

    ranges = {entry['name']: entry for entry in store.task_commits('cross', task['ref'])}
    assert set(ranges) == {'backend', 'frontend'}
    for name, repo in (('backend', backend), ('frontend', frontend)):
        assert ranges[name]['base_sha'] == base[name]
        assert ranges[name]['head_sha'] == _head(repo)
        assert ranges[name]['complete'] is True
    # 区间要能真的还原出这个任务的提交
    log = subprocess.run(
        ['git', '-C', str(backend), 'log', '--oneline',
         f'{ranges["backend"]["base_sha"]}..{ranges["backend"]["head_sha"]}'],
        check=True, capture_output=True, text=True,
    ).stdout
    assert '后端改动' in log


def test_tasks_finished_in_sequence_do_not_share_a_range(store, tmp_path):
    repo = _git_repo(tmp_path / 'repo')
    store.create_project('seq', '顺序完成', repositories=[str(repo)])
    first = store.add_task('seq', '先做的')
    second = store.add_task('seq', '后做的')

    store.set_status('seq', first['ref'], 'active')
    _git(repo, 'commit', '-q', '--allow-empty', '-m', '第一件')
    store.set_status('seq', first['ref'], 'done')
    store.set_status('seq', second['ref'], 'active')
    _git(repo, 'commit', '-q', '--allow-empty', '-m', '第二件')
    store.set_status('seq', second['ref'], 'done')

    one = store.task_commits('seq', first['ref'])[0]
    two = store.task_commits('seq', second['ref'])[0]
    assert one['head_sha'] == two['base_sha']  # 首尾相接
    assert one['base_sha'] != two['base_sha'] and one['head_sha'] != two['head_sha']


def test_reopened_task_keeps_original_base(store, tmp_path):
    repo = _git_repo(tmp_path / 'repo')
    store.create_project('again', '返工', repositories=[str(repo)])
    task = store.add_task('again', '要返工的')

    store.set_status('again', task['ref'], 'active')
    base = _head(repo)
    _git(repo, 'commit', '-q', '--allow-empty', '-m', '第一轮')
    store.set_status('again', task['ref'], 'done')
    store.set_status('again', task['ref'], 'todo')
    store.set_status('again', task['ref'], 'active')
    _git(repo, 'commit', '-q', '--allow-empty', '-m', '第二轮')
    store.set_status('again', task['ref'], 'done')

    entry = store.task_commits('again', task['ref'])[0]
    # 起点保留第一轮:区间要盖住全部返工，而不是只剩最后一轮
    assert entry['base_sha'] == base
    assert entry['head_sha'] == _head(repo)


def test_done_without_start_is_marked_incomplete(store, tmp_path):
    repo = _git_repo(tmp_path / 'repo')
    store.create_project('direct', '直接完成', repositories=[str(repo)])
    task = store.add_task('direct', '没走 start')

    store.set_status('direct', task['ref'], 'done')

    entry = store.task_commits('direct', task['ref'])[0]
    assert entry['base_sha'] is None
    assert entry['head_sha'] == _head(repo)
    assert entry['complete'] is False


def test_rewritten_history_is_reported_not_silently_wrong(store, tmp_path):
    repo = _git_repo(tmp_path / 'repo')
    store.create_project('rebased', '改写历史', repositories=[str(repo)])
    task = store.add_task('rebased', '会被 rebase 掉')

    store.set_status('rebased', task['ref'], 'active')
    _git(repo, 'commit', '-q', '--allow-empty', '-m', '原提交')
    store.set_status('rebased', task['ref'], 'done')
    stale_head = store.task_commits('rebased', task['ref'])[0]['head_sha']
    _git(repo, 'commit', '-q', '--allow-empty', '--amend', '-m', '改写后')
    _git(repo, 'reflog', 'expire', '--expire=now', '--all')
    _git(repo, 'gc', '-q', '--prune=now')

    assert 'missing' not in store.task_commits('rebased', task['ref'])[0]  # 默认不探测
    verified = store.task_commits('rebased', task['ref'], verify=True)[0]
    assert verified['missing'] == ['head']
    assert verified['head_sha'] == stale_head  # 记录不改写,只是标注失效


def test_task_without_repository_records_no_range(store):
    task = store.add_task('demo', '没有关联仓库')
    store.set_status('demo', task['ref'], 'done')
    assert store.task_commits('demo', task['ref']) == []

def test_range_follows_the_worktree_the_command_runs_in(store, tmp_path, monkeypatch):
    """Agent 常在 git worktree 里干活,起点必须是那棵树的 HEAD,不是主检出的。"""
    main = _git_repo(tmp_path / 'main')
    _git(main, 'commit', '-q', '--allow-empty', '-m', '主检出又走了一步')
    linked = tmp_path / 'linked'
    _git(main, 'worktree', 'add', '-q', '--detach', str(linked), 'HEAD~1')
    store.create_project('wt', '工作树', repositories=[str(main)])
    task = store.add_task('wt', '在工作树里做')

    monkeypatch.chdir(linked)
    store.set_status('wt', task['ref'], 'active')

    entry = store.task_commits('wt', task['ref'])[0]
    assert entry['base_sha'] == _head(linked)
    assert entry['base_sha'] != _head(main)


def test_range_ignores_cwd_belonging_to_another_repository(store, tmp_path, monkeypatch):
    """只认同一个仓库的另一棵工作树;换个仓库就退回登记路径,不重蹈按 cwd 乱取的覆辙。"""
    target = _git_repo(tmp_path / 'target')
    stranger = _git_repo(tmp_path / 'stranger')
    _git(stranger, 'commit', '-q', '--allow-empty', '-m', '无关仓库的提交')
    store.create_project('iso', '隔离', repositories=[str(target)])
    task = store.add_task('iso', '在别的仓库里执行')

    monkeypatch.chdir(stranger)
    store.set_status('iso', task['ref'], 'active')

    entry = store.task_commits('iso', task['ref'])[0]
    assert entry['base_sha'] == _head(target)
    assert entry['base_sha'] != _head(stranger)

def test_dropped_tasks_are_not_actionable(store):
    task = store.add_task('demo', '放弃的')
    store.set_status('demo', task['ref'], 'dropped')
    snapshot = store.snapshot()['projects'][0]
    assert snapshot['tasks'][0]['actionable'] is False
    assert snapshot['counts']['dropped'] == 1


def test_notes_split_by_kind_and_gates_exclude_done(store):
    finding = store.add_note(
        'demo', 'finding', '结论一', body='正文', metric='40/40', category='模型口径',
    )
    store.add_note('demo', 'risk', '尾巴一')
    gate = store.add_task('demo', '闸门任务', gate=True)

    snapshot = store.snapshot()['projects'][0]
    assert [n['title'] for n in snapshot['findings']] == ['结论一']
    assert snapshot['findings'][0]['category'] == '模型口径'
    assert [n['title'] for n in snapshot['risks']] == ['尾巴一']
    assert snapshot['gates'] == [gate['ref']]

    store.set_status('demo', gate['ref'], 'done')
    assert store.snapshot()['projects'][0]['gates'] == []

    updated = store.set_note_category(finding['id'], '部署状态')
    assert updated['category'] == '部署状态'


def test_invalid_status_and_kind_rejected(store):
    task = store.add_task('demo', 'X')
    with pytest.raises(BoardError):
        store.set_status('demo', task['ref'], 'finished')
    with pytest.raises(BoardError):
        store.add_note('demo', 'todo', '类型不对')
    with pytest.raises(BoardError):
        store.add_note('demo', 'finding', '分类过长', category='x' * 41)
    with pytest.raises(BoardError):
        store.add_note('demo', 'finding', '分类换行', category='模型\n口径')


def test_events_are_recorded(store):
    task = store.add_task('demo', '记录')
    store.set_status('demo', task['ref'], 'active')
    actions = [event['action'] for event in store.events(limit=10, project='demo')]
    assert 'status_changed' in actions
    assert 'task_added' in actions


def test_agent_run_is_persisted_on_task_without_private_app_state(store, tmp_path):
    task = store.add_task('demo', '派发任务')
    repository = str((tmp_path / 'repo').resolve())

    run = store.record_agent_run(
        'demo', task['ref'], provider='codex', dispatch_id='codex-test-1',
        repository_path=repository, status='submitted',
        external_thread_id='thread-123', external_turn_id='turn-456',
    )

    assert run['provider'] == 'codex'
    assert run['external_thread_id'] == 'thread-123'
    snapshot_task = store.snapshot()['projects'][0]['tasks'][0]
    assert snapshot_task['agent_runs'][0]['dispatch_id'] == 'codex-test-1'
    assert snapshot_task['agent_runs'][0]['repository_path'] == repository
    assert any(event['action'] == 'agent_dispatched' for event in store.events(project='demo'))


def test_agent_run_rejects_unknown_provider_and_unrelated_repository(store, tmp_path):
    task = store.add_task('demo', '派发边界')
    repository = str((tmp_path / 'repo').resolve())
    with pytest.raises(BoardError, match='Agent 只能是'):
        store.record_agent_run(
            'demo', task['ref'], provider='other', dispatch_id='bad-provider',
            repository_path=repository, status='submitted',
        )
    with pytest.raises(BoardError, match='未关联'):
        store.record_agent_run(
            'demo', task['ref'], provider='codex', dispatch_id='bad-repo',
            repository_path=str(tmp_path / 'other'), status='submitted',
        )


def test_snapshot_derives_first_started_at_from_event_stream(store):
    task = store.add_task('demo', '生命周期')
    initial = store.snapshot()['projects'][0]['tasks'][0]
    assert initial['created_at'] == task['created_at']
    assert initial['first_started_at'] is None

    store.set_status('demo', task['ref'], 'active')
    first_event = next(
        event for event in reversed(store.events(limit=20, project='demo'))
        if event['action'] == 'status_changed'
    )
    first_started = store.snapshot()['projects'][0]['tasks'][0]['first_started_at']
    assert first_started == first_event['at']

    store.set_status('demo', task['ref'], 'todo')
    store.set_status('demo', task['ref'], 'active')
    assert store.snapshot()['projects'][0]['tasks'][0]['first_started_at'] == first_started


def test_archived_projects_hidden_by_default(store):
    store.update_project('demo', archived=1)
    assert store.snapshot()['projects'] == []
    assert len(store.snapshot(include_archived=True)['projects']) == 1


def test_view_prefs_roundtrip_and_resilience(store, tmp_path):
    db = tmp_path / 'board.db'
    assert load_view_prefs(db) == {}  # sidecar 不存在
    assert view_prefs_path(db).name == 'board.view.json'

    saved = save_view_prefs(db, {'order': ['b', 'a'], 'pinned': ['a'], 'junk': ['x']})
    assert saved == {'order': ['b', 'a'], 'pinned': ['a']}  # 未知键丢弃
    assert load_view_prefs(db) == {'order': ['b', 'a'], 'pinned': ['a']}

    saved = save_view_prefs(db, {'order': ['ok', 1, '', None], 'pinned': 'notalist'})
    assert saved == {'order': ['ok'], 'pinned': []}  # 非法条目过滤
    assert load_view_prefs(db) == saved

    view_prefs_path(db).write_text('{oops', encoding='utf-8')
    assert load_view_prefs(db) == {}  # 损坏 JSON 容错
    view_prefs_path(db).write_text('[1, 2]', encoding='utf-8')
    assert load_view_prefs(db) == {}  # 顶层非对象容错
