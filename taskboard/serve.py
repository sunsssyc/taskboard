"""本地看板服务：实时读库，并提供受限的本机轻量写入 API。

写操作只在 loopback 监听时启用，并同时校验 Host、Origin、进程级 CSRF token、
JSON Content-Type 与请求体大小。静态 ``board export`` 不包含这些接口与控件。
"""
from __future__ import annotations

import importlib
import json
import secrets
import subprocess
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


def code_version() -> float:
    """包内 .py 的最新修改时间，作为代码版本号。"""
    package_dir = Path(__file__).resolve().parent
    return max((path.stat().st_mtime for path in package_dir.glob('*.py')), default=0.0)


def _git_head(repo: str | None) -> str | None:
    """完成任务时记录该项目仓库的 HEAD，而不是看板服务自己的 cwd。"""
    if not repo:
        return None
    try:
        result = subprocess.run(
            ['git', '-C', repo, 'rev-parse', '--short', 'HEAD'],
            check=True, capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def make_handler(db_path: str, title: str, include_archived: bool, dev: bool = False,
                 csrf_token: str | None = None, write_enabled: bool = False):
    state = {'code_version': code_version()}
    token = csrf_token or secrets.token_urlsafe(32)

    def reload_if_code_changed() -> float:
        current = code_version()
        if current != state['code_version']:
            importlib.reload(store_module)
            importlib.reload(render_module)
            state['code_version'] = current
            print(f'[dev] 代码已重载 (version={current:.0f})')
        return current

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

        def _task_detail(self, project_key: str, ref: int) -> dict:
            store = self._store()
            try:
                snapshot = store.snapshot(include_archived=True)
                project = next((p for p in snapshot['projects'] if p['key'] == project_key), None)
                if project is None:
                    raise store_module.BoardError(f'没有这个项目: {project_key}')
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

        def do_GET(self):  # noqa: N802
            version = reload_if_code_changed() if dev else None
            path = unquote(urlsplit(self.path).path).rstrip('/') or '/'
            if path in ('/', '/index.html'):
                body = render_module.render(
                    self._snapshot(), title=title, live=True,
                    csrf_token=token, write_enabled=write_enabled,
                    view_prefs=store_module.load_view_prefs(db_path),
                )
                self._send(render_module.html_document(body).encode('utf-8'),
                           'text/html; charset=utf-8')
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
            self._error(404, 'not found')

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
                    store_module.validate_markdown_newlines(detail, accept)
                    task = store.add_task(
                        project, title_value, detail=detail,
                        owner=owner, accept=accept,
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
                if len(parts) == 5 and parts[:2] == ['api', 'tasks'] and parts[4] == 'status':
                    project = parts[2]
                    ref = int(parts[3])
                    status = self._required_text(data, 'status')
                    if status not in WEB_STATUSES:
                        raise store_module.BoardError('网页只允许 todo/active/waiting/done')
                    project_row = store.get_project(project)
                    sha = _git_head(project_row['repo']) if status == 'done' else None
                    task = store.set_status(project, ref, status, commit_sha=sha)
                    self._json({'ok': True, 'project': project, 'ref': ref,
                                'status': task['status'], 'commit': sha})
                    return
                self._error(404, 'not found')
            except ValueError:
                self._error(404, '任务编号无效')
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
          open_browser: bool = False, dev: bool = False) -> None:
    db_path = str(store.path)
    write_enabled = host.lower() in LOOPBACK_HOSTS
    handler = make_handler(
        db_path, title, include_archived, dev,
        csrf_token=secrets.token_urlsafe(32), write_enabled=write_enabled,
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f'http://{host}:{port}'
    hint = 'CLI 改动 2 秒内自动刷新'
    hint += ';网页可轻量写入' if write_enabled else ';非本机监听只读'
    if dev:
        hint += ';dev:改代码免重启,保存后页面自动刷新'
    print(f'看板运行中 {url}  (Ctrl-C 停止;{hint})')
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
    finally:
        httpd.server_close()
