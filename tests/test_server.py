import pytest
from fastapi.testclient import TestClient

import jobs
import server

AUTH = ('tester', 'secret')
H = {'X-Requested-With': 'portfolio'}


@pytest.fixture
def client(monkeypatch):
    started = []
    monkeypatch.setattr(jobs, 'start', lambda kind, **kw: started.append(kind))
    server._release_guest_session()
    c = TestClient(server.app)
    c.started = started
    yield c
    server._release_guest_session()


def test_healthz_is_public(client):
    r = client.get('/healthz')
    assert r.status_code == 200 and r.json()['ok']


def test_everything_else_requires_auth(client):
    assert client.get('/').status_code == 401
    assert client.get('/api/status').status_code == 401
    assert client.get('/', auth=('tester', 'wrong')).status_code == 401
    r = client.get('/', auth=AUTH)
    assert r.status_code == 200 and 'script-src' in r.headers['content-security-policy']


def test_guest_url_token_becomes_cookie_and_cleans_url(client, monkeypatch):
    monkeypatch.setattr(server, 'GUEST_MODE', True)
    monkeypatch.setattr(server, 'GUEST_TOKEN', 'guest-secret-token')
    monkeypatch.setattr(server, 'GUEST_COOKIE_SECURE', False)
    assert client.get('/').status_code == 401
    assert 'www-authenticate' not in client.get('/').headers
    assert client.get('/?token=wrong').status_code == 401

    login = client.get('/?token=guest-secret-token&lang=zh', follow_redirects=False)
    assert login.status_code == 303 and login.headers['location'] == '/?lang=zh'
    cookie = login.headers['set-cookie']
    assert 'pt_guest_session=' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie
    assert 'guest-secret-token' not in cookie
    assert client.get('/').status_code == 200


def test_guest_mode_ignores_basic_auth(client, monkeypatch):
    monkeypatch.setattr(server, 'GUEST_MODE', True)
    monkeypatch.setattr(server, 'GUEST_TOKEN', 'guest-secret-token')
    monkeypatch.setattr(server, 'GUEST_COOKIE_SECURE', False)
    client.cookies.clear()
    assert client.get('/', auth=AUTH).status_code == 401


def test_guest_workspace_is_bound_to_one_browser(client, monkeypatch):
    monkeypatch.setattr(server, 'GUEST_MODE', True)
    monkeypatch.setattr(server, 'GUEST_TOKEN', 'guest-secret-token')
    monkeypatch.setattr(server, 'GUEST_COOKIE_SECURE', False)
    assert client.get('/?token=guest-secret-token', follow_redirects=False).status_code == 303
    assert client.get('/').status_code == 200

    other = TestClient(server.app)
    denied = other.get('/?token=guest-secret-token', follow_redirects=False)
    assert denied.status_code == 409
    assert 'another browser' in denied.text
    assert other.get('/').status_code == 401


def test_expired_browser_session_erases_before_token_reuse(client, monkeypatch, fixture_bytes):
    monkeypatch.setattr(server, 'GUEST_MODE', True)
    monkeypatch.setattr(server, 'GUEST_TOKEN', 'guest-secret-token')
    monkeypatch.setattr(server, 'GUEST_COOKIE_SECURE', False)
    assert client.get('/?token=guest-secret-token', follow_redirects=False).status_code == 303
    server.store.ACTIVITIES.write_bytes(fixture_bytes('activities_jan.csv')[1])
    with server._guest_session_lock:
        server._guest_active['expires'] = 0

    other = TestClient(server.app)
    assert other.get('/?token=guest-secret-token', follow_redirects=False).status_code == 303
    assert not server.store.ACTIVITIES.exists()
    assert client.get('/').status_code == 401


def test_posts_need_csrf_header(client):
    assert client.post('/api/rebuild', auth=AUTH).status_code == 403
    assert client.post('/api/rebuild', auth=AUTH, headers=H).status_code == 409


def test_price_route_rejects_traversal(client):
    assert client.get('/prices/..%2F..%2Fsettings.csv', auth=AUTH).status_code == 404


def test_upload_preview_and_commit(client, fixture_bytes):
    files = [('files', fixture_bytes('activities_jan.csv')), ('files', fixture_bytes('holdings_jan.csv'))]
    p = client.post('/api/import/preview', auth=AUTH, headers=H, files=files)
    assert p.status_code == 200, p.text
    body = p.json()
    assert body['added'] == 4 and body['committable']
    c = client.post('/api/import/commit', auth=AUTH, headers=H, json=dict(id=body['id'], fetch=True))
    assert c.status_code == 200 and c.json()['added'] == 4
    assert client.started == ['import-fetch']  # VOO is a new symbol, so prices get fetched
    assert client.get('/api/status', auth=AUTH).json()['exports']['activities']['rows'] == 4


def test_partial_import_waits_for_other_required_export(client, fixture_bytes):
    p = client.post('/api/import/preview', auth=AUTH, headers=H,
                    files=[('files', fixture_bytes('activities_jan.csv'))])
    assert p.status_code == 200
    c = client.post('/api/import/commit', auth=AUTH, headers=H,
                    json=dict(id=p.json()['id'], fetch=True))
    assert c.status_code == 200
    body = c.json()
    assert body['ok'] and body['job'] == 'import-fetch'
    assert body['missing_exports'] == ['holdings']
    assert body['estimated_holdings']
    assert client.started == ['import-fetch']


def test_rebuild_accepts_activity_only_import(client, fixture_bytes):
    store_preview = client.post('/api/import/preview', auth=AUTH, headers=H,
                                files=[('files', fixture_bytes('activities_jan.csv'))]).json()
    client.post('/api/import/commit', auth=AUTH, headers=H, json=dict(id=store_preview['id'], fetch=False))
    r = client.post('/api/rebuild', auth=AUTH, headers=H)
    assert r.status_code == 202
    assert client.started == ['rebuild', 'rebuild']


def test_end_guest_session_erases_private_data_and_cookie(client, monkeypatch, fixture_bytes):
    import server
    monkeypatch.setattr(server, 'GUEST_MODE', True)
    monkeypatch.setattr(server, 'GUEST_TOKEN', 'guest-secret-token')
    monkeypatch.setattr(server, 'GUEST_COOKIE_SECURE', False)
    login = client.get('/?token=guest-secret-token', follow_redirects=False)
    assert login.status_code == 303
    preview = client.post('/api/import/preview', headers=H,
                          files=[('files', fixture_bytes('activities_jan.csv'))]).json()
    client.post('/api/import/commit', headers=H, json=dict(id=preview['id'], fetch=False))

    r = client.post('/api/session/end', headers=H)
    assert r.status_code == 200 and r.json()['erased']
    assert 'pt_guest_session=""' in r.headers['set-cookie']
    assert not server.store.ACTIVITIES.exists()
    assert client.get('/').status_code == 401
    other = TestClient(server.app)
    assert other.get('/?token=guest-secret-token', follow_redirects=False).status_code == 303


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(server, 'MAX_UPLOAD_MB', 0.0001)
    r = client.post('/api/import/preview', auth=AUTH, headers=H, files=[('files', ('big.csv', b'x' * 1000))])
    assert r.status_code == 413
