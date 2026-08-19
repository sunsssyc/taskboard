"""本地看板服务:每次请求实时读库,页面轮询 state.json 变化后自刷新。

dev 模式额外让**代码**也热生效:每次请求前比对包内 .py 的 mtime,变了就重载
store/render 模块,并把代码版本写进 state.json,让页面像数据变更一样自动刷新。
"""
from __future__ import annotations

import importlib
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import render as render_module
from . import store as store_module
from .store import Store


def code_version() -> float:
    """包内 .py 的最新修改时间,作为代码版本号。"""
    package_dir = Path(__file__).resolve().parent
    return max((path.stat().st_mtime for path in package_dir.glob('*.py')), default=0.0)


def make_handler(db_path: str, title: str, include_archived: bool, dev: bool = False):
    state = {'code_version': code_version()}

    def reload_if_code_changed() -> float:
        """dev:代码变了就重载模块,返回当前代码版本。"""
        current = code_version()
        if current != state['code_version']:
            # 先 store 后 render:render 依赖 store 的数据形状,反序会读到旧定义
            importlib.reload(store_module)
            importlib.reload(render_module)
            state['code_version'] = current
            print(f'[dev] 代码已重载 (version={current:.0f})')
        return current

    class Handler(BaseHTTPRequestHandler):
        # 每个请求单开连接:sqlite3 连接不跨线程共享
        def _snapshot(self) -> dict:
            store_cls = store_module.Store if dev else Store
            store = store_cls(db_path)
            try:
                return store.snapshot(include_archived=include_archived)
            finally:
                store.close()

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
            version = reload_if_code_changed() if dev else None
            path = self.path.split('?')[0].rstrip('/') or '/'
            if path in ('/', '/index.html'):
                html = render_module.render(self._snapshot(), title=title, live=True)
                self._send(render_module.html_document(html).encode('utf-8'),
                           'text/html; charset=utf-8')
            elif path == '/state.json':
                snapshot = self._snapshot()
                # 生成时间每次都变,会让轮询永远判定为"有更新",故剔除
                snapshot.pop('generated_at', None)
                if dev:
                    # 只改渲染代码时快照数据不变,带上代码版本才能触发页面刷新
                    snapshot['code_version'] = version
                body = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode('utf-8')
                self._send(body, 'application/json; charset=utf-8')
            else:
                self.send_error(404, 'not found')

        def log_message(self, *_args):
            pass  # 静默:看板服务的访问日志没有价值

    return Handler


def serve(store: Store, host: str = '127.0.0.1', port: int = 8787,
          title: str = '任务看板', include_archived: bool = False,
          open_browser: bool = False, dev: bool = False) -> None:
    db_path = str(store.path)
    handler = make_handler(db_path, title, include_archived, dev)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f'http://{host}:{port}'
    hint = 'CLI 改动 2 秒内自动刷新'
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
