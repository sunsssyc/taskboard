import pytest

from taskboard.store import BoardError, Store


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


def test_dropped_tasks_are_not_actionable(store):
    task = store.add_task('demo', '放弃的')
    store.set_status('demo', task['ref'], 'dropped')
    snapshot = store.snapshot()['projects'][0]
    assert snapshot['tasks'][0]['actionable'] is False
    assert snapshot['counts']['dropped'] == 1


def test_notes_split_by_kind_and_gates_exclude_done(store):
    store.add_note('demo', 'finding', '结论一', body='正文', metric='40/40')
    store.add_note('demo', 'risk', '尾巴一')
    gate = store.add_task('demo', '闸门任务', gate=True)

    snapshot = store.snapshot()['projects'][0]
    assert [n['title'] for n in snapshot['findings']] == ['结论一']
    assert [n['title'] for n in snapshot['risks']] == ['尾巴一']
    assert snapshot['gates'] == [gate['ref']]

    store.set_status('demo', gate['ref'], 'done')
    assert store.snapshot()['projects'][0]['gates'] == []


def test_invalid_status_and_kind_rejected(store):
    task = store.add_task('demo', 'X')
    with pytest.raises(BoardError):
        store.set_status('demo', task['ref'], 'finished')
    with pytest.raises(BoardError):
        store.add_note('demo', 'todo', '类型不对')


def test_events_are_recorded(store):
    task = store.add_task('demo', '记录')
    store.set_status('demo', task['ref'], 'active')
    actions = [event['action'] for event in store.events(limit=10, project='demo')]
    assert 'status_changed' in actions
    assert 'task_added' in actions


def test_archived_projects_hidden_by_default(store):
    store.update_project('demo', archived=1)
    assert store.snapshot()['projects'] == []
    assert len(store.snapshot(include_archived=True)['projects']) == 1
