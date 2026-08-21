import json

import pytest

from taskboard.cli import main
from taskboard.render import render, render_markdown
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


def test_cli_notes_group_and_reclassify(db, capsys):
    run(db, 'init', 'demo', '--name', '结论分类')
    run(db, 'finding', '模型已定', '--category', '模型口径', '-p', 'demo')
    run(db, 'finding', '已部署', '--category', '交付状态', '-p', 'demo')
    capsys.readouterr()

    assert run(db, 'notes', '-p', 'demo') == 0
    output = capsys.readouterr().out
    assert '模型口径 · 1' in output and '交付状态 · 1' in output

    assert run(db, 'note-category', '1', '--category', '交付状态') == 0
    capsys.readouterr()
    store = Store(db)
    assert store.get_note(1)['category'] == '交付状态'
    store.close()


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


def test_render_uses_xcode_style_light_workspace(tmp_path):
    store = Store(tmp_path / 'board.db')
    store.create_project('x', '主题检查')
    html = render(store.snapshot())
    store.close()
    assert 'color-scheme:light' in html
    assert '--chrome:#f7f7f8' in html
    assert 'grid-template-columns:248px minmax(0,1fr)' in html
    assert 'class="navigator" aria-label="项目导航"' in html
    assert '<main class="content">' in html
    assert 'prefers-color-scheme: dark' not in html
    assert 'background:var(--ground)' in html
    assert '.done-fold summary, .active-fold summary, .blocked-fold summary, .dropped-fold summary {' in html
    assert 'grid-template-columns:48px minmax(0,1fr); align-items:center' in html
    assert '.done-fold > .step, .active-fold > .step,' in html
    assert 'grid-template-columns:64px minmax(0,1fr)' in html
    assert 'grid-template-columns:56px minmax(0,1fr)' in html
    assert '.task-disclosure { position:relative; width:100%' in html
    assert 'transform:translate(-50%,-50%) rotate(-45deg)' in html
    assert '.task-disclosure > span { position:absolute; left:calc(50% + 8px)' in html


def test_render_marks_gate_and_blocking(tmp_path):
    store = Store(tmp_path / 'board.db')
    store.create_project('x', '闸门')
    first = store.add_task('x', '前置')
    store.add_task('x', '闸门任务', gate=True, blocked_by=[first['ref']])
    html = render(store.snapshot())
    store.close()
    assert '闸门</span>' in html
    assert '阻塞 →' in html  # 主任务仍展示它会阻塞谁
    assert '<details class="blocked-fold">' in html
    assert '<summary>还有 1 项被阻塞待办</summary>' in html


def test_render_long_notes_use_full_width_reading_layout(tmp_path):
    store = Store(tmp_path / 'long-notes.db')
    store.create_project('demo', '长结论排版')
    store.add_note('demo', 'finding', '短结论', body='一句话说明')
    store.add_note('demo', 'finding', '长篇技术结论', body='技术正文' * 100)
    html = render(store.snapshot())
    store.close()

    assert 'class="note finding" id="note-1"' in html
    assert 'class="note finding long" id="note-2"' in html
    assert 'grid-column:1/-1' in html
    assert 'grid-template-columns:minmax(240px,.75fr) minmax(0,1.8fr)' in html
    assert 'grid-template-columns:48px minmax(0,1fr)' in html
    assert '.notes { display:flex; flex-direction:column' in html
    assert 'overflow-wrap:anywhere' in html
    assert '@media (max-width:760px)' in html


def test_render_groups_findings_by_category_with_uncategorized_last(tmp_path):
    store = Store(tmp_path / 'categories.db')
    store.create_project('demo', '结论分类')
    store.add_note('demo', 'finding', '采样口径', category='模型口径')
    store.add_note('demo', 'finding', '发版完成', category='交付状态')
    store.add_note('demo', 'finding', '旧数据')
    store.add_note('demo', 'link', 'docs/model.md', category='模型口径')
    html = render(store.snapshot())
    store.close()

    assert 'class="category-index"' in html
    assert '<h3>模型口径</h3><span>1 条</span>' in html
    assert '<h3>交付状态</h3><span>1 条</span>' in html
    assert '<h3>未分类</h3><span>1 条</span>' in html
    assert html.index('<h3>未分类</h3>') > html.index('<h3>交付状态</h3>')
    assert 'data-search="1 模型口径 采样口径' in html
    assert html.count('id="finding-demo-category-') == 3
    assert html.count('class="note-group" id="finding-demo-category-1" open') == 1
    assert 'class="note-group" id="link-demo-category-1" open' in html
    assert 'data-search="模型口径 docs/model.md' in html


def test_safe_markdown_renders_supported_blocks_and_rejects_unsafe_html():
    rendered = render_markdown("""## 当前判断

**影响明确**，字段 `sampling_policy` 已固定。

- 证据一
- 证据二

1. 先验证
2. 再发布

> 不要跳过回归测试。

```python
print("<unsafe>")
```

[安全链接](https://example.com/docs?a=1&b=2)
[危险链接](javascript:alert(1))
[实体伪装](java&#x73;cript:alert(1))
[控制字符伪装](java\tscript:alert(1))
<script>alert(1)</script>
""")

    assert '<h5>当前判断</h5>' in rendered
    assert '<strong>影响明确</strong>' in rendered
    assert '<code>sampling_policy</code>' in rendered
    assert '<ul><li>证据一</li><li>证据二</li></ul>' in rendered
    assert '<ol><li>先验证</li><li>再发布</li></ol>' in rendered
    assert '<blockquote><p>不要跳过回归测试。</p></blockquote>' in rendered
    assert '<pre><code class="language-python">print(&quot;&lt;unsafe&gt;&quot;)</code></pre>' in rendered
    assert 'href="https://example.com/docs?a=1&amp;b=2"' in rendered
    assert rendered.count('<a href=') == 1
    assert 'href="javascript:' not in rendered and 'href="java&amp;#x73;cript:' not in rendered
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered


def test_task_and_note_fields_render_markdown(tmp_path):
    store = Store(tmp_path / 'markdown.db')
    store.create_project('demo', 'Markdown')
    store.add_task('demo', '结构化任务', detail='**影响**\n\n- 补测试', accept='运行 `pytest`')
    store.add_note('demo', 'finding', '结构化结论', body='> 已验证\n\n查看 [文档](docs/check.md)')
    store.add_note('demo', 'link', 'docs/check.md', body='查看 **支持范围**')
    html = render(store.snapshot())
    store.close()

    assert 'class="markdown card-detail"' in html
    assert '<strong>影响</strong>' in html and '<li>补测试</li>' in html
    assert '<div class="accept"><b>验收</b>运行 <code>pytest</code></div>' in html
    # 主任务默认完整展开,正文开关收进节点序号旁的 disclosure,不再使用底部按钮。
    assert '<div class="task-body"><div class="markdown card-detail"' in html
    assert 'class="task-disclosure" aria-expanded="true"' in html
    assert 'aria-label="收起 #1 全文"' in html
    assert 'body.hidden = !expanded' in html
    assert '展开全部' not in html
    assert 'class="markdown note-body"' in html
    assert '<blockquote><p>已验证</p></blockquote>' in html
    assert '<a href="docs/check.md">文档</a>' in html
    assert '<code>docs/check.md</code> 查看 <strong>支持范围</strong>' in html


def test_live_render_has_interactions_but_static_export_stays_read_only(tmp_path):
    store = Store(tmp_path / 'interactive.db')
    store.create_project('demo', '交互看板')
    store.add_task('demo', '可操作任务', detail='**说明**', owner='我')
    store.add_note('demo', 'finding', '分类提示', category='模型口径')
    snapshot = store.snapshot()
    store.close()

    live_html = render(
        snapshot, live=True, csrf_token='test-csrf', write_enabled=True,
    )
    assert 'name="query"' in live_html and 'name="status"' in live_html
    assert 'class="detail-button"' in live_html
    assert 'data-create="task"' in live_html and 'data-create="finding"' in live_html
    assert 'name="category"' in live_html
    assert 'list="finding-categories"' in live_html and '模型口径' in live_html
    assert "var createForm = createDialog ?" in live_html
    assert 'data-status="done"' in live_html
    assert 'data-csrf="test-csrf"' in live_html
    assert '/api/tasks/' in live_html
    assert "current.task.accept ? '\\n\\n验收条件" in live_html
    assert 'inset:0 0 0 auto' in live_html and '--inspector-shadow' in live_html

    static_html = render(snapshot)
    assert 'name="query"' in static_html  # 搜索筛选仍是纯前端只读交互
    assert 'class="detail-button"' not in static_html
    assert 'data-create="task"' not in static_html
    assert '<button type="button" class="action primary" data-status="done">' not in static_html
    assert 'data-csrf=' not in static_html
    assert '/api/tasks/' not in static_html


def test_task_commands_reject_literal_paragraph_breaks(db, capsys):
    run(db, 'init', 'demo', '--name', '换行防错')
    capsys.readouterr()

    assert run(db, 'add', '错误换行', '--detail', r'第一段\n\n第二段', '-p', 'demo') == 1
    assert '字面量 \\n\\n' in capsys.readouterr().err

    assert run(db, 'add', '真实换行', '--detail', '第一段\n\n第二段', '-p', 'demo') == 0
    assert run(db, 'edit', '1', '--detail', r'改后第一段\n\n改后第二段', '-p', 'demo') == 1
    assert '字面量 \\n\\n' in capsys.readouterr().err

    # 明确放在代码跨度里的转义符是展示内容,不应误报。
    assert run(db, 'edit', '1', '--detail', r'展示 `\n\n` 转义符', '-p', 'demo') == 0


@pytest.mark.parametrize('command', ['finding', 'risk', 'link'])
def test_note_commands_reject_literal_paragraph_breaks(db, capsys, command):
    run(db, 'init', 'demo', '--name', '记录换行防错')
    capsys.readouterr()

    assert run(db, command, '错误记录', '--body', r'第一段\n\n第二段', '-p', 'demo') == 1
    assert '字面量 \\n\\n' in capsys.readouterr().err

    store = Store(db)
    try:
        assert store.notes('demo') == []
    finally:
        store.close()


def test_render_embeds_view_prefs_with_script_escape(db):
    store = Store(db)
    store.create_project('demo', '嵌入偏好')
    snapshot = store.snapshot()
    store.close()

    page = render(snapshot, view_prefs={'order': ['demo'], 'pinned': []})
    assert 'window.__BOARD_VIEW__ = {"order": ["demo"], "pinned": []};' in page

    hostile = render(snapshot, view_prefs={'order': ['x</script><script>alert(1)'], 'pinned': []})
    assert '<\\/script>' in hostile
    assert 'x</script>' not in hostile

    bare = render(snapshot)
    assert 'window.__BOARD_VIEW__ = {' not in bare


def test_cli_export_embeds_view_prefs(db, tmp_path, capsys):
    from taskboard.store import save_view_prefs

    assert run(db, 'init', 'demo', '--name', '导出嵌入') == 0
    save_view_prefs(db, {'order': ['demo'], 'pinned': ['demo']})
    out = tmp_path / 'board.html'
    assert run(db, 'export', '--out', str(out)) == 0
    capsys.readouterr()

    page = out.read_text(encoding='utf-8')
    assert 'window.__BOARD_VIEW__ = {"order": ["demo"], "pinned": ["demo"]};' in page


def test_render_bridge_mode_clicks_status_via_native_bridge(db):
    store = Store(db)
    store.create_project('demo', '桥接模式')
    store.add_task('demo', '可点状态', accept='通过验收')
    snapshot = store.snapshot()
    store.close()

    page = render(snapshot, bridge=True)
    assert 'class="chip todo status-button"' in page
    assert 'id="status-menu"' in page
    assert 'window.__boardSetStatus' in page
    assert 'handlers.boardStatus.postMessage' in page
    assert 'data-csrf' not in page  # 桥接模式没有 serve 的写入 API
    assert 'class="detail-button"' not in page  # 详情依赖 /api,桥接导出不含

    plain = render(snapshot)
    assert 'status-button' not in plain
    assert 'id="status-menu"' not in plain


def test_cli_export_bridge_flag(db, tmp_path, capsys):
    assert run(db, 'init', 'demo', '--name', '桥接导出') == 0
    assert run(db, 'add', '点我改状态', '-p', 'demo') == 0
    capsys.readouterr()

    out = tmp_path / 'bridge.html'
    assert run(db, 'export', '--bridge', '--out', str(out)) == 0
    page = out.read_text(encoding='utf-8')
    assert 'status-button' in page and 'handlers.boardStatus.postMessage' in page

    plain_out = tmp_path / 'plain.html'
    assert run(db, 'export', '--out', str(plain_out)) == 0
    assert 'status-button' not in plain_out.read_text(encoding='utf-8')
