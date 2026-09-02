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


def test_new_note_marks_old_as_superseded(store, monkeypatch):
    clock = {'value': '2026-09-02T01:00:00+00:00'}
    monkeypatch.setattr('taskboard.store.now_iso', lambda: clock['value'])
    old = store.add_note('demo', 'finding', '旧结论', body='当时这么认为')

    clock['value'] = '2026-09-02T02:00:00+00:00'
    new = store.add_note('demo', 'finding', '新结论', supersedes=[old['id']])

    refreshed = store.get_note(old['id'])
    assert refreshed['superseded_by'] == new['id']
    assert refreshed['superseded_at'] is not None
    assert refreshed['updated_at'] == clock['value']
    assert store.get_note(new['id'])['superseded_by'] is None


def test_notes_can_filter_superseded(store):
    old = store.add_note('demo', 'finding', '旧结论')
    store.add_note('demo', 'finding', '新结论', supersedes=[old['id']])

    assert len(store.notes('demo', 'finding')) == 2
    active = store.notes('demo', 'finding', include_superseded=False)
    assert [note['title'] for note in active] == ['新结论']


def test_snapshot_orders_active_first_and_links_both_directions(store):
    old = store.add_note('demo', 'finding', '旧结论')
    new = store.add_note('demo', 'finding', '新结论', supersedes=[old['id']])
    other = store.add_note('demo', 'finding', '无关结论')

    findings = store.snapshot()['projects'][0]['findings']
    assert [f['title'] for f in findings] == ['新结论', '无关结论', '旧结论']  # 被推翻的沉底
    by_id = {f['id']: f for f in findings}
    assert by_id[new['id']]['supersedes'] == [old['id']]
    assert by_id[old['id']]['is_superseded'] is True
    assert by_id[other['id']]['supersedes'] == []


def test_double_supersede_rejected_with_pointer_to_latest(store):
    first = store.add_note('demo', 'finding', '第一版')
    second = store.add_note('demo', 'finding', '第二版', supersedes=[first['id']])
    with pytest.raises(BoardError) as exc:
        store.add_note('demo', 'finding', '第三版', supersedes=[first['id']])
    assert str(second['id']) in str(exc.value)


def test_cross_project_supersede_rejected(store):
    store.create_project('other', '另一个')
    outsider = store.add_note('other', 'finding', '别的项目的结论')
    with pytest.raises(BoardError):
        store.add_note('demo', 'finding', '本项目结论', supersedes=[outsider['id']])
    # 校验发生在建记录之前:不该留下半成品
    assert store.notes('demo', 'finding') == []


def test_deleting_superseder_restores_old_note(store):
    old = store.add_note('demo', 'finding', '旧结论')
    new = store.add_note('demo', 'finding', '新结论', supersedes=[old['id']])
    store.delete_note(new['id'])
    assert store.get_note(old['id'])['superseded_by'] is None  # 不留悬空指针


def test_restore_undoes_supersede(store):
    old = store.add_note('demo', 'finding', '旧结论')
    new = store.add_note('demo', 'finding', '新结论', supersedes=[old['id']])
    store.restore_note(old['id'])
    assert store.get_note(old['id'])['superseded_by'] is None
    with pytest.raises(BoardError):
        store.restore_note(old['id'])  # 本来就有效
    store.supersede_note(old['id'], new['id'])  # 事后补回关系
    assert store.get_note(old['id'])['superseded_by'] == new['id']


def test_migration_adds_columns_to_existing_db(tmp_path):
    import sqlite3

    db = tmp_path / 'legacy.db'
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE projects (key TEXT PRIMARY KEY, name TEXT NOT NULL, repo TEXT,
            summary TEXT, archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT, metric TEXT,
            created_at TEXT NOT NULL);
        INSERT INTO projects VALUES ('demo','老库',NULL,NULL,0,'2026-01-01','2026-01-01');
        INSERT INTO notes (project, kind, title, created_at) VALUES ('demo','finding','老结论','2026-01-01');
    """)
    conn.commit()
    conn.close()

    store = Store(db)  # 打开即就地补列,老数据不动
    try:
        note = store.notes('demo', 'finding')[0]
        assert note['title'] == '老结论'
        assert note['superseded_by'] is None
        assert note['updated_at'] == note['created_at'] == '2026-01-01'
        newer = store.add_note('demo', 'finding', '新结论', supersedes=[note['id']])
        assert store.get_note(note['id'])['superseded_by'] == newer['id']
    finally:
        store.close()


def test_render_collapses_superseded_and_shows_overturns(store):
    old = store.add_note('demo', 'finding', '被推翻的旧结论', body='旧证据')
    store.add_note('demo', 'finding', '当前结论', supersedes=[old['id']])
    html = render(store.snapshot())

    assert '<details class="note superseded" id="note-1">' in html
    assert 'id="note-2"' in html and '<span class="note-id">[2]</span>' in html
    assert 'href="#note-2">已被 [2] 推翻</a>' in html  # 旧结论可跳到替代它的新结论
    assert 'id="note-1"' in html and '<span class="note-id">[1]</span>' in html
    assert 'href="#note-1">[1]</a>' in html            # 新结论可跳回被它推翻的旧结论
    assert html.index('当前结论') < html.index('被推翻的旧结论')  # 有效结论在前


def test_cli_supersede_flow(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('TASKBOARD_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('NO_COLOR', '1')
    db = str(tmp_path / 'board.db')
    main(['--db', db, 'init', 'demo', '--name', '示例'])
    main(['--db', db, 'finding', '旧结论', '-p', 'demo'])
    main(['--db', db, 'finding', '新结论', '--supersedes', '1', '-p', 'demo'])
    capsys.readouterr()

    main(['--db', db, 'notes', '-p', 'demo'])
    out = capsys.readouterr().out
    assert '新结论' in out and '旧结论' not in out          # 默认只列有效
    assert '另有 1 条已被推翻' in out

    main(['--db', db, 'notes', '--superseded', '-p', 'demo'])
    out = capsys.readouterr().out
    assert '旧结论' in out and '已被 [2] 推翻' in out

    main(['--db', db, 'restore', '1'])
    capsys.readouterr()
    main(['--db', db, 'notes', '-p', 'demo'])
    assert '旧结论' in capsys.readouterr().out
