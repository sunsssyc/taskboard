import json

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


def test_cli_flow_add_start_done(db, capsys):
    assert run(db, 'init', 'demo', '--name', '示例') == 0
    assert run(db, 'add', '第一件', '--owner', '我', '-p', 'demo') == 0
    assert run(db, 'add', '第二件', '--blocked-by', '1', '-p', 'demo') == 0
    capsys.readouterr()

    assert run(db, 'next', '-p', 'demo') == 0
    out = capsys.readouterr().out
    assert '第一件' in out and '第二件' not in out  # 被阻塞的不算可开工

    assert run(db, 'done', '1', '-p', 'demo') == 0
    out = capsys.readouterr().out
    assert '解锁' in out and '第二件' in out


def test_cli_ls_hides_done_until_flag(db, capsys):
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'add', '做完的', '-p', 'demo')
    run(db, 'done', '1', '-p', 'demo')
    capsys.readouterr()

    run(db, 'ls', '-p', 'demo')
    assert '做完的' not in capsys.readouterr().out
    run(db, 'ls', '--done', '-p', 'demo')
    assert '做完的' in capsys.readouterr().out


def test_cli_resolves_project_from_cwd(db, tmp_path, monkeypatch, capsys):
    repo = tmp_path / 'myrepo'
    repo.mkdir()
    run(db, 'init', 'byrepo', '--name', '按目录', '--repo', str(repo))
    run(db, 'add', '目录内任务', '-p', 'byrepo')
    capsys.readouterr()

    monkeypatch.chdir(repo)
    assert run(db, 'ls') == 0  # 不传 -p 也能定位
    assert '目录内任务' in capsys.readouterr().out


def test_cli_unknown_project_errors_cleanly(db, capsys):
    assert run(db, 'add', '无主任务', '-p', 'nope') == 1
    assert '没有这个项目' in capsys.readouterr().err


def test_cli_ambiguous_project_errors_cleanly(db, tmp_path, monkeypatch, capsys):
    run(db, 'init', 'a', '--name', 'A')
    run(db, 'init', 'b', '--name', 'B')
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    assert run(db, 'ls') == 1
    assert '认不出当前项目' in capsys.readouterr().err


def test_cli_export_html_and_json(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    repo.mkdir()
    run(db, 'init', 'demo', '--name', '示例项目', '--repo', str(repo))
    run(db, 'add', '任务甲', '--detail', '细节说明', '-p', 'demo')
    run(db, 'finding', '关键结论', '--metric', '40/40', '-p', 'demo')
    capsys.readouterr()

    html_path = tmp_path / 'out.html'
    run(db, 'export', '--out', str(html_path), '-p', 'demo')
    html = html_path.read_text(encoding='utf-8')
    assert html.startswith('<!doctype html><meta charset="utf-8">')
    assert '示例项目' in html and '任务甲' in html
    assert '关键结论' in html and '40/40' in html
    assert db not in html
    assert str(repo) not in html

    json_path = tmp_path / 'out.json'
    run(db, 'export', '--json', '--out', str(json_path))
    data = json.loads(json_path.read_text(encoding='utf-8'))
    assert data['projects'][0]['tasks'][0]['title'] == '任务甲'
    assert data['db'] is None
    assert data['projects'][0]['repo'] is None

    local_path = tmp_path / 'local.html'
    run(db, 'export', '--show-paths', '--out', str(local_path), '-p', 'demo')
    local_html = local_path.read_text(encoding='utf-8')
    assert db in local_html
    assert str(repo) in local_html


def test_render_escapes_html(tmp_path):
    store = Store(tmp_path / 'board.db')
    store.create_project('x', '<script>alert(1)</script>')
    store.add_task('x', '标题 & <b>粗</b>')
    html = render(store.snapshot())
    store.close()
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html
    assert '&amp;' in html


def test_render_theme_tokens_cover_three_states(tmp_path):
    store = Store(tmp_path / 'board.db')
    store.create_project('x', '主题检查')
    html = render(store.snapshot())
    store.close()
    assert 'prefers-color-scheme: dark' in html
    assert ':root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html
    assert 'background:var(--ground)' in html


def test_render_marks_gate_and_blocking(tmp_path):
    store = Store(tmp_path / 'board.db')
    store.create_project('x', '闸门')
    first = store.add_task('x', '前置')
    store.add_task('x', '闸门任务', gate=True, blocked_by=[first['ref']])
    html = render(store.snapshot())
    store.close()
    assert '闸门</span>' in html
    assert '阻塞于' in html and '阻塞 →' in html
