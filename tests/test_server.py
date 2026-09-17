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
    c = TestClient(server.app)
    c.started = started
    return c


def test_healthz_is_public(client):
    r = client.get('/healthz')
    assert r.status_code == 200 and r.json()['ok']


def test_everything_else_requires_auth(client):
    assert client.get('/').status_code == 401
    assert client.get('/api/status').status_code == 401
    assert client.get('/', auth=('tester', 'wrong')).status_code == 401
    r = client.get('/', auth=AUTH)
    assert r.status_code == 200 and 'script-src' in r.headers['content-security-policy']


def test_posts_need_csrf_header(client):
    assert client.post('/api/rebuild', auth=AUTH).status_code == 403
    assert client.post('/api/rebuild', auth=AUTH, headers=H).status_code == 202


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


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(server, 'MAX_UPLOAD_MB', 0.0001)
    r = client.post('/api/import/preview', auth=AUTH, headers=H, files=[('files', ('big.csv', b'x' * 1000))])
    assert r.status_code == 413
