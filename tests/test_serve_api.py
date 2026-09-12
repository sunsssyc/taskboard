import json
import subprocess
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from taskboard.serve import MAX_JSON_BODY, make_handler
from taskboard.store import Store


def fake_web_dir(root):
    """模拟 npm run build:web 的产物:index.html + assets/。"""
    web = root / 'web'
    (web / 'assets').mkdir(parents=True, exist_ok=True)
    (web / 'index.html').write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>任务看板</title>'
        '<script type="module" src="/assets/app.js"></script></head>'
        '<body><div id="app"></div></body></html>', encoding='utf-8',
    )
    (web / 'assets' / 'app.js').write_text('console.log("vue")', encoding='utf-8')
    return web


@contextmanager
def running_server(db_path, *, token='test-csrf', write_enabled=True, web_dir=None):
    handler = make_handler(
        str(db_path), '测试看板', include_archived=False,
        csrf_token=token, write_enabled=write_enabled, web_dir=web_dir,
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

    with running_server(db_path, write_enabled=False, web_dir=fake_web_dir(tmp_path)) as port:
        status, _, page = request(port, 'GET', '/')
        assert status == 200 and '"writeEnabled": false' in page
        status, _, _ = request(
            port, 'POST', '/api/tasks', payload, write_headers(port),
        )
        assert status == 403


def test_live_page_create_task_finding_and_read_detail(tmp_path):
    db_path = tmp_path / 'write.db'
    store = Store(db_path)
    store.create_project('demo', '网页操作')
    store.close()

    with running_server(db_path, web_dir=fake_web_dir(tmp_path)) as port:
        status, _, page = request(port, 'GET', '/')
        assert status == 200
        assert 'window.__TASKBOARD_WEB__ = {' in page and '"csrf": "test-csrf"' in page
        assert '<title>测试看板</title>' in page

        task_payload = json.dumps({
            'project': 'demo', 'title': '网页任务', 'detail': '**说明**\n\n- 步骤',
            'accept': '通过 `pytest`', 'owner': '我', 'priority': 0,
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
        assert detail['task']['priority'] == 0
        assert '<strong>说明</strong>' in detail['detail_html']
        assert '<code>pytest</code>' in detail['accept_html']

        status, _, value = request(
            port, 'POST', '/api/tasks/demo/1/status',
            json.dumps({'status': 'dropped'}), write_headers(port),
        )
        assert status == 400 and '网页只允许' in value['error']

    store = Store(db_path)
    assert store.get_task('demo', 1)['owner'] == '我'
    assert store.get_task('demo', 1)['priority'] == 0
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

    with running_server(db_path, web_dir=fake_web_dir(tmp_path)) as port:
        status, _, board = request(port, 'GET', '/api/board')
        assert status == 200
        assert board['viewPrefs'] == {'order': [], 'pinned': []}
        assert board['writeEnabled'] is True
        assert [project['key'] for project in board['snapshot']['projects']] == ['demo', 'other']

        payload = json.dumps({'order': ['other', 'demo'], 'pinned': ['demo'], 'extra': ['x']})
        status, _, value = request(port, 'POST', '/api/view', payload, write_headers(port))
        assert status == 200
        assert value['view'] == {'order': ['other', 'demo'], 'pinned': ['demo']}

        status, _, _ = request(port, 'POST', '/api/view', payload, {
            'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json',
        })
        assert status == 403  # 缺 CSRF

        status, _, board = request(port, 'GET', '/api/board')
        assert status == 200
        assert board['viewPrefs'] == {'order': ['other', 'demo'], 'pinned': ['demo']}

    with running_server(db_path, write_enabled=False, web_dir=fake_web_dir(tmp_path)) as port:
        status, _, board = request(port, 'GET', '/api/board')
        assert status == 200 and board['writeEnabled'] is False
        status, _, _ = request(port, 'POST', '/api/view', payload, write_headers(port))
        assert status == 403  # 非本机监听只读


def test_serve_hosts_vue_build_and_refuses_paths_outside_it(tmp_path):
    db_path = tmp_path / 'static.db'
    store = Store(db_path)
    store.create_project('demo', '静态资源')
    store.close()
    secret = tmp_path / 'secret.txt'
    secret.write_text('不该被读到', encoding='utf-8')

    with running_server(db_path, web_dir=fake_web_dir(tmp_path)) as port:
        status, headers, body = request(port, 'GET', '/assets/app.js')
        assert status == 200 and body == 'console.log("vue")'
        assert dict(headers)['Content-Type'].startswith('text/javascript')
        status, _, _ = request(port, 'GET', '/assets/../secret.txt')
        assert status == 404
        status, _, _ = request(port, 'GET', '/assets/%2e%2e/secret.txt')
        assert status == 404
        status, _, value = request(port, 'GET', '/api/version')
        assert status == 200 and value['board'] and value['page']

    with running_server(db_path, web_dir=tmp_path / 'missing') as port:
        status, _, page = request(port, 'GET', '/')
        assert status == 503 and 'npm run build:web' in page
        status, _, board = request(port, 'GET', '/api/board')
        assert status == 200 and board['snapshot']['projects'][0]['key'] == 'demo'


def test_task_owner_priority_and_project_archive_apis(tmp_path):
    db_path = tmp_path / 'edit.db'
    store = Store(db_path)
    store.create_project('demo', '任务编辑')
    store.add_task('demo', '改我')
    store.close()

    with running_server(db_path) as port:
        status, _, value = request(
            port, 'POST', '/api/tasks/demo/1/owner',
            json.dumps({'owner': '双方'}), write_headers(port),
        )
        assert status == 200 and value['owner'] == '双方'
        status, _, value = request(
            port, 'POST', '/api/tasks/demo/1/owner',
            json.dumps({'owner': '路人'}), write_headers(port),
        )
        assert status == 400 and '网页只允许' in value['error']
        status, _, value = request(
            port, 'POST', '/api/tasks/demo/1/priority',
            json.dumps({'priority': 0}), write_headers(port),
        )
        assert status == 200 and value['priority'] == 0
        status, _, value = request(
            port, 'POST', '/api/tasks/demo/1/priority',
            json.dumps({'priority': 'P0'}), write_headers(port),
        )
        assert status == 400
        status, _, value = request(
            port, 'POST', '/api/projects/demo/archived',
            json.dumps({'archived': True}), write_headers(port),
        )
        assert status == 200 and value['archived'] is True
        status, _, board = request(port, 'GET', '/api/board')
        assert board['snapshot']['projects'] == []  # 默认不含已归档
        status, _, value = request(
            port, 'POST', '/api/projects/demo/archived',
            json.dumps({'archived': 'yes'}), write_headers(port),
        )
        assert status == 400

    store = Store(db_path)
    task = store.get_task('demo', 1)
    assert (task['owner'], task['priority']) == ('双方', 0)
    assert store.get_project('demo')['archived'] == 1
    store.close()


def test_concept_cards_flow_over_http(tmp_path):
    repo = tmp_path / 'svc'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@example.com'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'commit.gpgsign', 'false'], check=True)
    (repo / 'sync.py').write_text('def sync(): pass\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', '基线'], check=True)

    db_path = tmp_path / 'concept.db'
    store = Store(db_path)
    store.create_project('alpha', '需求A', repositories=[str(repo)])
    store.create_project('beta', '需求B', repositories=[str(repo)])
    store.add_task('alpha', '引入水位线')
    code = store.add_concept(
        str(repo), '增量对账用水位线', body='全量扫描随数据增长', files=['sync.py:sync'],
        project='alpha', task_ref=1,
    )
    method = store.add_concept(None, '结论比任务更容易丢', body='所以结论单独落库', project='beta')
    store.close()

    with running_server(db_path) as port:
        status, _, board = request(port, 'GET', '/api/board')
        assert status == 200
        by_key = {project['key']: project for project in board['snapshot']['projects']}
        # 代码概念按仓库共享:alpha 提的,beta 同样看得到;需求概念只在自己的需求里
        assert [c['id'] for c in by_key['alpha']['concepts']] == [code['id']]
        assert {c['id'] for c in by_key['beta']['concepts']} == {code['id'], method['id']}
        card = by_key['alpha']['concepts'][0]
        assert card['state'] == 'proposed' and card['task_ref'] == 1
        assert card['repository'] == 'svc'
        assert [(item['path'], item['symbol']) for item in card['files']] == [('sync.py', 'sync')]

        status, _, value = request(
            port, 'POST', f'/api/concepts/{code["id"]}',
            json.dumps({'title': '增量对账靠水位线,不靠全量扫描'}, ensure_ascii=False).encode(),
            write_headers(port),
        )
        assert status == 200 and value['concept']['title'] == '增量对账靠水位线,不靠全量扫描'

        status, _, value = request(
            port, 'POST', f'/api/concepts/{code["id"]}/align',
            json.dumps({'note': '看过了'}), write_headers(port),
        )
        assert status == 200 and value['concept']['state'] == 'aligned'
        assert value['concept']['aligned_commit']

        # 对齐后改措辞会退回待对齐,并明确告知
        status, _, value = request(
            port, 'POST', f'/api/concepts/{code["id"]}',
            json.dumps({'body': '换个说法'}, ensure_ascii=False).encode(), write_headers(port),
        )
        assert status == 200
        assert value['concept']['state'] == 'proposed' and value['concept']['alignment_reset']

        status, _, value = request(
            port, 'POST', f'/api/concepts/{method["id"]}/reject',
            json.dumps({'reason': ''}), write_headers(port),
        )
        assert status == 400 and 'reason' in value['error']
        status, _, value = request(
            port, 'POST', f'/api/concepts/{method["id"]}/reject',
            json.dumps({'reason': '不算新概念'}, ensure_ascii=False).encode(), write_headers(port),
        )
        assert status == 200 and value['concept']['state'] == 'rejected'

        status, _, _ = request(
            port, 'POST', '/api/concepts/999/align', json.dumps({}), write_headers(port),
        )
        assert status == 400
        status, _, _ = request(
            port, 'POST', '/api/concepts/abc/align', json.dumps({}), write_headers(port),
        )
        assert status == 404

        status, _, board = request(port, 'GET', '/api/board')
        states = {c['id']: c['state'] for c in
                  {p['key']: p for p in board['snapshot']['projects']}['beta']['concepts']}
        assert states == {code['id']: 'proposed', method['id']: 'rejected'}
