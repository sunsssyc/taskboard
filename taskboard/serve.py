"""本地看板服务:托管 Vue 前端构建产物,实时读库,并提供受限的本机轻量写入 API。

页面本身来自 ``apps/desktop`` 的构建产物(``npm run build:web`` 输出到 ``taskboard/web``),
与 Tauri 桌面端同一套界面;这里只负责数据与写入接口。写操作只在 loopback 监听时启用,
并同时校验 Host、Origin、进程级 CSRF token、JSON Content-Type 与请求体大小。
静态 ``board export`` 不包含这些接口与控件。
"""
from __future__ import annotations

import importlib
import json
import os
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import render as render_module
from . import store as store_module
from .store import Store

MAX_JSON_BODY = 64 * 1024
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}
WEB_STATUSES = {'todo', 'active', 'waiting', 'done'}
WEB_OWNERS = {'', '你', '我', '双方'}
WEB_DIR_ENV = 'TASKBOARD_WEB_DIR'
STATIC_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.map': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
}
MISSING_WEB_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>任务看板 · 前端未构建</title></head><body style="font-family:system-ui;padding:40px">
<h1>前端还没构建</h1>
<p>board serve 托管的是 Vue 桌面端同一套页面,先构建一次:</p>
<pre>cd apps/desktop &amp;&amp; npm ci &amp;&amp; npm run build:web</pre>
<p>或用 <code>TASKBOARD_WEB_DIR</code> / <code>--web-dir</code> 指向任一构建目录。
数据接口不受影响:<a href="/api/board">/api/board</a></p></body></html>"""


def code_version() -> float:
    """包内 .py 的最新修改时间,作为代码版本号。"""
    package_dir = Path(__file__).resolve().parent
    return max((path.stat().st_mtime for path in package_dir.glob('*.py')), default=0.0)


def find_web_dir(explicit: str | Path | None = None) -> Path | None:
    """找前端构建目录:显式指定就只认它;否则环境变量 → 包内 web/ → 仓库内 apps/desktop/dist。"""
    package_dir = Path(__file__).resolve().parent
    if explicit is not None:
        # 明确指了目录却不存在,静默换成别的只会让人排查半天
        candidates: list = [explicit]
    else:
        candidates = [
            os.environ.get(WEB_DIR_ENV),
            package_dir / 'web',
            package_dir.parent / 'apps' / 'desktop' / 'dist',
        ]
    for candidate in candidates:
        if candidate and (Path(candidate) / 'index.html').is_file():
            return Path(candidate).resolve()
    return None


def board_version(db_path: str | Path) -> str:
    """数据库(含 WAL)最近修改时间:网页以此判断 CLI 有没有改过东西。"""
    stamps = []
    for suffix in ('', '-wal'):
        path = Path(f'{db_path}{suffix}')
        if path.exists():
            stat = path.stat()
            stamps.append(f'{stat.st_mtime_ns}:{stat.st_size}')
    return '|'.join(stamps)


def inject_web_context(html: str, context: dict) -> str:
    """把 CSRF token 等页面上下文塞进构建产物的 <head>,并替换标题。"""
    script = ('<script>window.__TASKBOARD_WEB__ = '
              + json.dumps(context, ensure_ascii=False).replace('</', '<\\/')
              + ';</script>')
    if context.get('title'):
        html = re.sub(r'<title>.*?</title>',
                      lambda _m: f'<title>{render_module.esc(context["title"])}</title>',
                      html, count=1, flags=re.S)
    if '</head>' in html:
        return html.replace('</head>', script + '</head>', 1)
    return script + html


def make_handler(db_path: str, title: str, include_archived: bool, dev: bool = False,
                 csrf_token: str | None = None, write_enabled: bool = False,
                 web_dir: str | Path | None = None):
    state = {'code_version': code_version()}
    token = csrf_token or secrets.token_urlsafe(32)
    resolved_web_dir = find_web_dir(web_dir)

    def reload_if_code_changed() -> float:
        current = code_version()
        if current != state['code_version']:
            importlib.reload(store_module)
            importlib.reload(render_module)
            state['code_version'] = current
            print(f'[dev] 代码已重载 (version={current:.0f})')
        return current

    def page_version() -> str:
        parts = [f'{state["code_version"]:.0f}']
        if resolved_web_dir:
            parts.append(str((resolved_web_dir / 'index.html').stat().st_mtime_ns))
        return ':'.join(parts)

    class Handler(BaseHTTPRequestHandler):
        def _store(self):
            store_cls = store_module.Store if dev else Store
            return store_cls(db_path)

        def _snapshot(self) -> dict:
            store = self._store()
            try:
                return store.snapshot(include_archived=include_archived)
            finally:
                store.close()

        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, value: object, status: int = 200) -> None:
            body = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self._send(body, 'application/json; charset=utf-8', status)

        def _error(self, status: int, message: str) -> None:
            self._json({'ok': False, 'error': message}, status)

        def _expected_origins(self) -> set[str]:
            port = self.server.server_address[1]
            return {
                f'http://127.0.0.1:{port}', f'http://localhost:{port}',
                f'http://[::1]:{port}',
            }

        def _authorize_write(self) -> bool:
            if not write_enabled:
                self._error(403, '当前监听地址未启用写入')
                return False
            expected = self._expected_origins()
            origin = self.headers.get('Origin', '')
            host = self.headers.get('Host', '')
            if origin not in expected or f'http://{host}' not in expected:
                self._error(403, 'Host 或 Origin 不受信任')
                return False
            if self.headers.get('X-Taskboard-CSRF') != token:
                self._error(403, 'CSRF token 无效')
                return False
            content_type = self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
            if content_type != 'application/json':
                self._error(415, '只接受 application/json')
                return False
            return True

        def _read_json(self) -> dict | None:
            raw_length = self.headers.get('Content-Length')
            try:
                length = int(raw_length or '')
            except ValueError:
                self._error(411, '需要有效的 Content-Length')
                return None
            if length <= 0:
                self._error(400, '请求体不能为空')
                return None
            if length > MAX_JSON_BODY:
                self._error(413, '请求体过大')
                return None
            try:
                value = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._error(400, 'JSON 格式错误')
                return None
            if not isinstance(value, dict):
                self._error(400, 'JSON 顶层必须是对象')
                return None
            return value

        @staticmethod
        def _required_text(data: dict, key: str, max_length: int = 240) -> str:
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                raise store_module.BoardError(f'{key} 不能为空')
            value = value.strip()
            if len(value) > max_length:
                raise store_module.BoardError(f'{key} 不能超过 {max_length} 个字符')
            return value

        @staticmethod
        def _optional_text(data: dict, key: str, max_length: int = 60_000) -> str | None:
            value = data.get(key)
            if value in (None, ''):
                return None
            if not isinstance(value, str):
                raise store_module.BoardError(f'{key} 必须是文本')
            if len(value) > max_length:
                raise store_module.BoardError(f'{key} 不能超过 {max_length} 个字符')
            return value

        @staticmethod
        def _text_list(data: dict, key: str, max_items: int = 20) -> list[str]:
            value = data.get(key, [])
            if not isinstance(value, list) or len(value) > max_items:
                raise store_module.BoardError(f'{key} 必须是最多 {max_items} 项的列表')
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise store_module.BoardError(f'{key} 中每项都必须是非空文本')
            return [item.strip() for item in value]

        @staticmethod
        def _required_bool(data: dict, key: str) -> bool:
            value = data.get(key)
            if not isinstance(value, bool):
                raise store_module.BoardError(f'{key} 必须是 true/false')
            return value

        def _task_detail(self, project_key: str, ref: int) -> dict:
            store = self._store()
            try:
                snapshot = store.snapshot(include_archived=True)
                project = next((p for p in snapshot['projects'] if p['key'] == project_key), None)
                if project is None:
                    raise store_module.BoardError(f'没有这个需求: {project_key}')
                task = next((t for t in project['tasks'] if t['ref'] == ref), None)
                if task is None:
                    raise store_module.BoardError(f'{project_key} 里没有任务 #{ref}')
                events = []
                for row in store.events(limit=250, project=project_key):
                    if row['task_ref'] != ref:
                        continue
                    try:
                        payload = json.loads(row['payload']) if row['payload'] else {}
                    except json.JSONDecodeError:
                        payload = {'raw': row['payload']}
                    events.append({'action': row['action'], 'payload': payload, 'at': row['at']})
                    if len(events) == 20:
                        break
                return {'ok': True, 'project': {
                    'key': project['key'], 'name': project['name'], 'repo': project['repo'],
                }, 'task': task, 'events': events,
                    'detail_html': render_module.render_markdown(task.get('detail')),
                    'accept_html': render_module.render_inline_markdown(task.get('accept')),
                }
            finally:
                store.close()

        # ── 页面与静态资源 ──────────────────────────────────────────────
        def _web_context(self) -> dict:
            return {
                'csrf': token, 'writeEnabled': write_enabled, 'title': title,
                'dev': dev, 'includeArchived': include_archived,
            }

        def _send_index(self) -> None:
            if resolved_web_dir is None:
                self._send(MISSING_WEB_PAGE.encode('utf-8'), 'text/html; charset=utf-8', 503)
                return
            html = (resolved_web_dir / 'index.html').read_text(encoding='utf-8')
            html = inject_web_context(html, self._web_context())
            self._send(html.encode('utf-8'), 'text/html; charset=utf-8')

        def _send_static(self, path: str) -> bool:
            """构建目录内的文件才放行;路径穿越或目录外一律当作不存在。"""
            if resolved_web_dir is None:
                return False
            relative = path.lstrip('/')
            if not relative or '\x00' in relative:
                return False
            target = (resolved_web_dir / relative).resolve()
            try:
                target.relative_to(resolved_web_dir)
            except ValueError:
                return False
            if not target.is_file():
                return False
            content_type = STATIC_TYPES.get(target.suffix.lower(), 'application/octet-stream')
            self._send(target.read_bytes(), content_type)
            return True

        def do_GET(self):  # noqa: N802
            version = reload_if_code_changed() if dev else None
            path = unquote(urlsplit(self.path).path).rstrip('/') or '/'
            if path in ('/', '/index.html'):
                self._send_index()
                return
            if path == '/api/board':
                snapshot = self._snapshot()
                self._json({
                    'ok': True,
                    'snapshot': snapshot,
                    'viewPrefs': {'order': [], 'pinned': [],
                                  **store_module.load_view_prefs(db_path)},
                    'source': '本地 board serve',
                    'writeEnabled': write_enabled,
                    'version': board_version(db_path),
                })
                return
            if path == '/api/version':
                self._json({'ok': True, 'board': board_version(db_path), 'page': page_version()})
                return
            if path == '/api/session':
                self._json({'ok': True, **self._web_context()})
                return
            if path == '/state.json':
                snapshot = self._snapshot()
                snapshot.pop('generated_at', None)
                if dev:
                    snapshot['code_version'] = version
                self._json(snapshot)
                return
            parts = path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'tasks']:
                try:
                    self._json(self._task_detail(parts[2], int(parts[3])))
                except (ValueError, store_module.BoardError) as exc:
                    self._error(404, str(exc))
                return
            if not path.startswith('/api/') and self._send_static(path):
                return
            self._error(404, 'not found')

        # ── 写入 ────────────────────────────────────────────────────────
        def _post_concept(self, store, parts: list[str], data: dict) -> None:
            note_id = int(parts[2])
            action = parts[3] if len(parts) == 4 else 'edit'
            if action == 'align':
                note = self._optional_text(data, 'note', 2_000)
                entry = store.align_concept(note_id, note=note)
            elif action == 'reject':
                reason = self._required_text(data, 'reason', 2_000)
                entry = store.reject_concept(note_id, reason)
            elif action == 'edit':
                title_value = self._optional_text(data, 'title', store_module.CONCEPT_TITLE_LIMIT)
                body = self._optional_text(data, 'body', store_module.CONCEPT_BODY_LIMIT)
                category = self._optional_text(data, 'category', 40)
                keep_aligned = bool(data.get('keep_aligned', False))
                store_module.validate_markdown_newlines(body)
                entry = store.update_concept(
                    note_id, title=title_value, body=body, category=category,
                    keep_aligned=keep_aligned,
                )
            else:
                self._error(404, 'not found')
                return
            self._json({'ok': True, 'concept': entry})

        def do_POST(self):  # noqa: N802
            if dev:
                reload_if_code_changed()
            if not self._authorize_write():
                return
            data = self._read_json()
            if data is None:
                return
            path = unquote(urlsplit(self.path).path).rstrip('/') or '/'
            store = self._store()
            try:
                if path == '/api/view':
                    saved = store_module.save_view_prefs(db_path, data)
                    self._json({'ok': True, 'view': saved})
                    return
                if path == '/api/tasks':
                    project = self._required_text(data, 'project', 120)
                    title_value = self._required_text(data, 'title')
                    detail = self._optional_text(data, 'detail')
                    accept = self._optional_text(data, 'accept', 2_000)
                    owner = self._optional_text(data, 'owner', 120)
                    priority = data.get('priority', store_module.DEFAULT_PRIORITY)
                    if not isinstance(priority, int) or isinstance(priority, bool):
                        raise store_module.BoardError('priority 必须是 P0-P3 对应的整数 0-3')
                    repositories = self._text_list(data, 'repositories')
                    if store.project_repositories(project) and not repositories:
                        raise store_module.BoardError('请先确认并选择本任务关联仓库')
                    store_module.validate_markdown_newlines(detail, accept)
                    task = store.add_task(
                        project, title_value, detail=detail,
                        owner=owner, accept=accept, repositories=repositories,
                        priority=priority,
                    )
                    self._json({'ok': True, 'project': project, 'ref': task['ref']}, 201)
                    return
                if path == '/api/notes':
                    project = self._required_text(data, 'project', 120)
                    title_value = self._required_text(data, 'title')
                    body = self._optional_text(data, 'body')
                    metric = self._optional_text(data, 'metric', 2_000)
                    category = self._optional_text(data, 'category', 40)
                    store_module.validate_markdown_newlines(body)
                    note = store.add_note(
                        project, 'finding', title_value, body=body,
                        metric=metric, category=category,
                    )
                    self._json({'ok': True, 'project': project, 'id': note['id']}, 201)
                    return
                parts = path.strip('/').split('/')
                if len(parts) in (3, 4) and parts[:2] == ['api', 'concepts']:
                    self._post_concept(store, parts, data)
                    return
                if len(parts) == 4 and parts[:2] == ['api', 'projects'] and parts[3] == 'archived':
                    project = parts[2]
                    archived = self._required_bool(data, 'archived')
                    row = store.update_project(project, archived=archived)
                    self._json({'ok': True, 'project': row['key'], 'archived': bool(row['archived'])})
                    return
                if len(parts) == 5 and parts[:2] == ['api', 'tasks']:
                    project = parts[2]
                    ref = int(parts[3])
                    field = parts[4]
                    if field == 'status':
                        status = self._required_text(data, 'status')
                        if status not in WEB_STATUSES:
                            raise store_module.BoardError('网页只允许 todo/active/waiting/done')
                        # 区间由 Store 逐仓库记录,网页端不再自己探 git
                        task = store.set_status(project, ref, status)
                        commits = store.task_commits(project, ref)
                        sha = commits[0]['head_sha'] if len(commits) == 1 else None
                        self._json({'ok': True, 'project': project, 'ref': ref,
                                    'status': task['status'], 'commit': sha})
                        return
                    if field == 'owner':
                        owner = data.get('owner')
                        if not isinstance(owner, str) or owner not in WEB_OWNERS:
                            raise store_module.BoardError('网页只允许 你/我/双方/未分配')
                        task = store.update_task(project, ref, owner=owner)
                        self._json({'ok': True, 'project': project, 'ref': ref,
                                    'owner': task['owner']})
                        return
                    if field == 'priority':
                        priority = data.get('priority')
                        if not isinstance(priority, int) or isinstance(priority, bool):
                            raise store_module.BoardError('priority 必须是 P0-P3 对应的整数 0-3')
                        task = store.update_task(project, ref, priority=priority)
                        self._json({'ok': True, 'project': project, 'ref': ref,
                                    'priority': task['priority']})
                        return
                self._error(404, 'not found')
            except ValueError:
                self._error(404, '编号无效')
            except store_module.BoardError as exc:
                self._error(400, str(exc))
            finally:
                store.close()

        def do_OPTIONS(self):  # noqa: N802
            self._error(405, '不提供跨域访问')

        def log_message(self, *_args):
            pass

    return Handler


def serve(store: Store, host: str = '127.0.0.1', port: int = 8787,
          title: str = '任务看板', include_archived: bool = False,
          open_browser: bool = False, dev: bool = False,
          web_dir: str | Path | None = None) -> None:
    db_path = str(store.path)
    write_enabled = host.lower() in LOOPBACK_HOSTS
    handler = make_handler(
        db_path, title, include_archived, dev,
        csrf_token=secrets.token_urlsafe(32), write_enabled=write_enabled,
        web_dir=web_dir,
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f'http://{host}:{port}'
    hint = 'CLI 改动 2 秒内自动刷新'
    hint += ';网页可轻量写入' if write_enabled else ';非本机监听只读'
    if dev:
        hint += ';dev:改代码免重启,保存后页面自动刷新'
    resolved = find_web_dir(web_dir)
    if resolved is None:
        print('前端构建产物未找到:cd apps/desktop && npm ci && npm run build:web'
              f'(或设置 {WEB_DIR_ENV})')
    print(f'看板运行中 {url}  (Ctrl-C 停止;{hint})')
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
    finally:
        httpd.server_close()
