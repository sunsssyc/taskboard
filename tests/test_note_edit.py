import pytest

from taskboard.cli import main
from taskboard.store import BoardError, Store


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / 'board.db')
    s.create_project('demo', '示例项目')
    yield s
    s.close()


def test_edit_title(store):
    note = store.add_note('demo', 'finding', '旧标题', body='正文', metric='旧数字')
    updated = store.edit_note(note['id'], title='新标题')
    assert updated['title'] == '新标题'
    assert updated['body'] == '正文'      # 未传的字段不变
    assert updated['metric'] == '旧数字'


def test_edit_body(store):
    note = store.add_note('demo', 'finding', '标题', body='旧正文')
    updated = store.edit_note(note['id'], body='新正文')
    assert updated['body'] == '新正文'
    assert updated['title'] == '标题'


def test_edit_metric(store):
    note = store.add_note('demo', 'finding', '标题', metric='旧')
    updated = store.edit_note(note['id'], metric='新 · 更好')
    assert updated['metric'] == '新 · 更好'


def test_clear_body(store):
    note = store.add_note('demo', 'finding', '标题', body='正文')
    updated = store.edit_note(note['id'], body=None)
    assert updated['body'] is None


def test_clear_metric(store):
    note = store.add_note('demo', 'finding', '标题', metric='有数字')
    updated = store.edit_note(note['id'], metric=None)
    assert updated['metric'] is None


def test_edit_multiple_fields(store):
    note = store.add_note('demo', 'finding', '旧标题', body='旧正文', metric='旧')
    updated = store.edit_note(note['id'], title='新标题', body='新正文', metric='新')
    assert updated['title'] == '新标题'
    assert updated['body'] == '新正文'
    assert updated['metric'] == '新'


def test_edit_empty_title_rejected(store):
    note = store.add_note('demo', 'finding', '标题')
    with pytest.raises(BoardError):
        store.edit_note(note['id'], title='')


def test_edit_nothing_rejected(store):
    note = store.add_note('demo', 'finding', '标题')
    with pytest.raises(BoardError, match='至少要改一个字段'):
        store.edit_note(note['id'])


def test_edit_updates_timestamp(store):
    note = store.add_note('demo', 'finding', '标题')
    old_ts = note['updated_at']
    updated = store.edit_note(note['id'], title='改了')
    assert updated['updated_at'] >= old_ts
    assert updated['title'] == '改了'


def test_cli_note_edit(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv('TASKBOARD_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('NO_COLOR', '1')
    db = str(tmp_path / 'board.db')
    main(['--db', db, 'init', 'demo', '--name', '示例'])
    main(['--db', db, 'finding', '旧标题很长很费劲', '-p', 'demo',
          '--metric', 'v3 矛盾 2258/2581(含 206 正) · 太多了',
          '--body', '旧正文'])
    capsys.readouterr()

    main(['--db', db, 'note-edit', '1',
          '--title', '新标题简洁',
          '--metric', '矛盾率 87.5%'])
    out = capsys.readouterr().out
    assert '新标题简洁' in out
    assert '已更新' in out

    # 验证持久化
    main(['--db', db, 'notes', '-p', 'demo'])
    out = capsys.readouterr().out
    assert '新标题简洁' in out
    assert '矛盾率 87.5%' in out
