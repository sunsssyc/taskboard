import json
import subprocess
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from taskboard.serve import MAX_JSON_BODY, make_handler
from taskboard.store import Store


@contextmanager
def running_server(db_path, *, token='test-csrf', write_enabled=True):
    handler = make_handler(
        str(db_path), '测试看板', include_archived=False,
        csrf_token=token, write_enabled=write_enabled,
    )
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(port, method, path, body=None, headers=None):
    connection = HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read()
        content_type = response.getheader('Content-Type', '')
        value = json.loads(raw) if 'application/json' in content_type else raw.decode('utf-8')
        return response.status, response.getheaders(), value
    finally:
        connection.close()


def write_headers(port, token='test-csrf'):
    return {
        'Origin': f'http://127.0.0.1:{port}',
        'Content-Type': 'application/json',
        'X-Taskboard-CSRF': token,
    }


def test_write_api_rejects_untrusted_requests(tmp_path):
    db_path = tmp_path / 'secure.db'
    store = Store(db_path)
    store.create_project('demo', '安全边界')
    store.close()

    with running_server(db_path) as port:
        payload = json.dumps({'project': 'demo', 'title': '不应写入'})

        status, response_headers, _ = request(port, 'POST', '/api/tasks', payload, {
            'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json',
        })
        assert status == 403  # 缺 CSRF
        assert not any(name.lower() == 'access-control-allow-origin' for name, _ in response_headers)

        headers = write_headers(port)
        headers['Origin'] = 'http://evil.example'
        status, _, _ = request(port, 'POST', '/api/tasks', payload, headers)
        assert status == 403

        headers = write_headers(port)
        headers['Host'] = 'evil.example'
        status, _, _ = request(port, 'POST', '/api/tasks', payload, headers)
        assert status == 403

        headers = write_headers(port)
        headers['Content-Type'] = 'text/plain'
        status, _, _ = request(port, 'POST', '/api/tasks', payload, headers)
        assert status == 415

        oversized = json.dumps({'project': 'demo', 'title': 'x' * MAX_JSON_BODY})
        status, _, _ = request(port, 'POST', '/api/tasks', oversized, write_headers(port))
        assert status == 413

        invalid_type = json.dumps({'project': 'demo', 'title': '类型错误', 'owner': ['我']})
        status, _, value = request(port, 'POST', '/api/tasks', invalid_type, write_headers(port))
        assert status == 400 and value['error'] == 'owner 必须是文本'

    store = Store(db_path)
    assert store.tasks('demo') == []
    store.close()

    with running_server(db_path, write_enabled=False) as port:
        status, _, page = request(port, 'GET', '/')
        assert status == 200 and 'data-create="task"' not in page
        status, _, _ = request(
            port, 'POST', '/api/tasks', payload, write_headers(port),
        )
        assert status == 403


def test_live_page_create_task_finding_and_read_detail(tmp_path):
    db_path = tmp_path / 'write.db'
    store = Store(db_path)
    store.create_project('demo', '网页操作')
    store.close()

    with running_server(db_path) as port:
        status, _, page = request(port, 'GET', '/')
        assert status == 200
        assert 'data-csrf="test-csrf"' in page
        assert 'data-create="task"' in page

        task_payload = json.dumps({
            'project': 'demo', 'title': '网页任务', 'detail': '**说明**\n\n- 步骤',
            'accept': '通过 `pytest`', 'owner': '我',
        }, ensure_ascii=False)
        status, _, value = request(
            port, 'POST', '/api/tasks', task_payload.encode(), write_headers(port),
        )
        assert status == 201 and value['ref'] == 1

        note_payload = json.dumps({
            'project': 'demo', 'title': '网页结论', 'body': '> 已验证',
            'metric': '54 passed', 'category': '交付状态',
        }, ensure_ascii=False)
        status, _, value = request(
            port, 'POST', '/api/notes', note_payload.encode(), write_headers(port),
        )
        assert status == 201 and value['id'] == 1

        status, _, detail = request(port, 'GET', '/api/tasks/demo/1')
        assert status == 200
        assert detail['task']['title'] == '网页任务'
        assert '<strong>说明</strong>' in detail['detail_html']
        assert '<code>pytest</code>' in detail['accept_html']

        status, _, value = request(
            port, 'POST', '/api/tasks/demo/1/status',
            json.dumps({'status': 'dropped'}), write_headers(port),
        )
        assert status == 400 and '网页只允许' in value['error']

    store = Store(db_path)
    assert store.get_task('demo', 1)['owner'] == '我'
    assert store.get_note(1)['metric'] == '54 passed'
    assert store.get_note(1)['category'] == '交付状态'
    store.close()


def test_live_create_task_requires_repository_for_multi_repo_workstream(tmp_path):
    backend = tmp_path / 'coinex_backend'
    admin = tmp_path / 'coinex_admin_frontend'
    backend.mkdir()
    admin.mkdir()
    db_path = tmp_path / 'multi.db'
    store = Store(db_path)
    store.create_project(
        'multi', '跨仓库需求', repositories=[str(backend), str(admin)],
    )
    store.close()

    with running_server(db_path) as port:
        payload = {
            'project': 'multi', 'title': '后端任务', 'detail': '',
            'accept': '', 'owner': '我', 'repositories': [],
        }
        status, _, value = request(
            port, 'POST', '/api/tasks', json.dumps(payload).encode(), write_headers(port),
        )
        assert status == 400 and '选择本任务关联仓库' in value['error']

        payload['repositories'] = ['coinex_backend']
        status, _, value = request(
            port, 'POST', '/api/tasks', json.dumps(payload).encode(), write_headers(port),
        )
        assert status == 201 and value['ref'] == 1

    store = Store(db_path)
    try:
        assert [repo['name'] for repo in store.task_repositories('multi', 1)] == [
            'coinex_backend',
        ]
    finally:
        store.close()


def test_done_records_head_from_target_project_repo(tmp_path):
    repo = tmp_path / 'target-repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@example.com'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'commit.gpgsign', 'false'], check=True)
    (repo / 'proof.txt').write_text('target repo\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(repo), 'add', 'proof.txt'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'target head'], check=True)
    expected = subprocess.run(
        ['git', '-C', str(repo), 'rev-parse', '--short', 'HEAD'],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    db_path = tmp_path / 'done.db'
    store = Store(db_path)
    store.create_project('target', '目标项目', repo=str(repo))
    store.add_task('target', '完成我', accept='目标仓库 HEAD 已记录')
    store.close()

    with running_server(db_path) as port:
        payload = json.dumps({'status': 'done'})
        status, _, value = request(
            port, 'POST', '/api/tasks/target/1/status', payload, write_headers(port),
        )
        assert status == 200
        assert value['status'] == 'done' and value['commit'] == expected

    store = Store(db_path)
    events = [dict(row) for row in store.events(project='target')]
    store.close()
    status_event = next(event for event in events if event['action'] == 'status_changed')
    assert json.loads(status_event['payload'])['commit'] == expected


def test_view_prefs_api_roundtrip_and_page_embedding(tmp_path):
    db_path = tmp_path / 'view.db'
    store = Store(db_path)
    store.create_project('demo', '视图偏好')
    store.create_project('other', '另一个')
    store.close()

    with running_server(db_path) as port:
        status, _, page = request(port, 'GET', '/')
        assert status == 200
        assert 'window.__BOARD_VIEW__ = {' not in page  # 偏好文件不存在时不嵌入
        assert 'data-write="1"' in page

        payload = json.dumps({'order': ['other', 'demo'], 'pinned': ['demo'], 'extra': ['x']})
        status, _, value = request(port, 'POST', '/api/view', payload, write_headers(port))
        assert status == 200
        assert value['view'] == {'order': ['other', 'demo'], 'pinned': ['demo']}

        status, _, _ = request(port, 'POST', '/api/view', payload, {
            'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json',
        })
        assert status == 403  # 缺 CSRF

        status, _, page = request(port, 'GET', '/')
        assert status == 200
        assert 'window.__BOARD_VIEW__ = {"order": ["other", "demo"], "pinned": ["demo"]};' in page

    with running_server(db_path, write_enabled=False) as port:
        status, _, page = request(port, 'GET', '/')
        assert status == 200 and 'data-write="1"' not in page
        status, _, _ = request(port, 'POST', '/api/view', payload, write_headers(port))
        assert status == 403  # 非本机监听只读
