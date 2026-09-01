import pytest

from taskboard.cli import main
from taskboard.render import render
from taskboard.store import BoardError, Store


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / 'board.db')
    s.create_project('demo', '示例项目')
    yield s
    s.close()


def test_settle_marks_note_as_settled(store):
    note = store.add_note('demo', 'finding', '已验证结论', body='证据确凿')
    store.settle_note(note['id'])

    refreshed = store.get_note(note['id'])
    assert refreshed['settled_at'] is not None


def test_unsettle_restores_to_active(store):
    note = store.add_note('demo', 'finding', '已验证结论')
    store.settle_note(note['id'])
    store.unsettle_note(note['id'])

    refreshed = store.get_note(note['id'])
    assert refreshed['settled_at'] is None


def test_cannot_settle_superseded_note(store):
    old = store.add_note('demo', 'finding', '旧结论')
    store.add_note('demo', 'finding', '新结论', supersedes=[old['id']])

    with pytest.raises(BoardError):
        store.settle_note(old['id'])


def test_cannot_settle_already_settled(store):
    note = store.add_note('demo', 'finding', '结论')
    store.settle_note(note['id'])

    with pytest.raises(BoardError):
        store.settle_note(note['id'])


def test_cannot_unsettle_active_note(store):
    note = store.add_note('demo', 'finding', '活跃结论')
    with pytest.raises(BoardError):
        store.unsettle_note(note['id'])


def test_notes_filter_settled(store):
    a = store.add_note('demo', 'finding', '活跃结论')
    b = store.add_note('demo', 'finding', '已完成的结论')
    store.settle_note(b['id'])

    all_notes = store.notes('demo', 'finding')
    assert len(all_notes) == 2

    active_only = store.notes('demo', 'finding', include_settled=False)
    assert [n['title'] for n in active_only] == ['活跃结论']


def test_snapshot_orders_settled_between_active_and_superseded(store):
    a = store.add_note('demo', 'finding', '活跃')
    b = store.add_note('demo', 'finding', '已沉淀')
    store.settle_note(b['id'])
    old = store.add_note('demo', 'finding', '旧结论')
    store.add_note('demo', 'finding', '新结论', supersedes=[old['id']])

    findings = store.snapshot()['projects'][0]['findings']
    titles = [f['title'] for f in findings]
    # 活跃 → 新结论(活跃) → 已沉淀 → 旧结论(被推翻)
    assert titles.index('活跃') < titles.index('已沉淀')
    assert titles.index('已沉淀') < titles.index('旧结论')


def test_render_collapses_settled_with_tag(store):
    note = store.add_note('demo', 'finding', '已完成的结论', body='做完了')
    store.settle_note(note['id'])
    html = render(store.snapshot())

    assert 'note settled' in html
    assert '已沉淀' in html


def test_cli_settle_flow(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('TASKBOARD_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('NO_COLOR', '1')
    db = str(tmp_path / 'board.db')
    main(['--db', db, 'init', 'demo', '--name', '示例'])
    main(['--db', db, 'finding', '结论一', '-p', 'demo'])
    main(['--db', db, 'finding', '结论二', '-p', 'demo'])
    capsys.readouterr()

    # 沉淀
    main(['--db', db, 'settle', '1'])
    out = capsys.readouterr().out
    assert '已沉淀' in out

    # 默认不显示已沉淀
    main(['--db', db, 'notes', '-p', 'demo'])
    out = capsys.readouterr().out
    assert '结论一' not in out
    assert '结论二' in out
    assert '1 条已沉淀' in out

    # --settled 显示已沉淀
    main(['--db', db, 'notes', '--settled', '-p', 'demo'])
    out = capsys.readouterr().out
    assert '结论一' in out and '已沉淀' in out

    # 恢复
    main(['--db', db, 'unsettle', '1'])
    out = capsys.readouterr().out
    assert '恢复为活跃' in out

    main(['--db', db, 'notes', '-p', 'demo'])
    out = capsys.readouterr().out
    assert '结论一' in out
