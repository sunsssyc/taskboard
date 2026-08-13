"""本地看板服务:每次请求实时读库,页面轮询 state.json 变化后自刷新。"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .render import render
from .store import Store


def make_handler(db_path: str, title: str, include_archived: bool):
    class Handler(BaseHTTPRequestHandler):
        # 每个请求单开连接:sqlite3 连接不跨线程共享
        def _snapshot(self) -> dict:
            store = Store(db_path)
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
            path = self.path.split('?')[0].rstrip('/') or '/'
            if path in ('/', '/index.html'):
                html = render(self._snapshot(), title=title, live=True)
                self._send(('<!doctype html><meta charset="utf-8">' + html).encode('utf-8'),
                           'text/html; charset=utf-8')
            elif path == '/state.json':
                snapshot = self._snapshot()
                # 生成时间每次都变,会让轮询永远判定为"有更新",故剔除
                snapshot.pop('generated_at', None)
                body = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode('utf-8')
                self._send(body, 'application/json; charset=utf-8')
            else:
                self.send_error(404, 'not found')

        def log_message(self, *_args):
            pass  # 静默:看板服务的访问日志没有价值

    return Handler


def serve(store: Store, host: str = '127.0.0.1', port: int = 8787,
          title: str = '任务看板', include_archived: bool = False,
          open_browser: bool = False) -> None:
    db_path = str(store.path)
    handler = make_handler(db_path, title, include_archived)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f'http://{host}:{port}'
    print(f'看板运行中 {url}  (Ctrl-C 停止;CLI 改动 2 秒内自动刷新)')
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
    finally:
        httpd.server_close()
