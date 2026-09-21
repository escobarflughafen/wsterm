"""The MCP surface: off by default, its own token, and never a way to fetch, rebuild or import."""
import json

import pytest
from fastapi.testclient import TestClient

import mcp
import server

TOKEN = 'a' * 40
H = {'Authorization': f'Bearer {TOKEN}'}


def call(client, method, params=None, mid=1):
    body = dict(jsonrpc='2.0', id=mid, method=method)
    if params is not None:
        body['params'] = params
    return client.post('/mcp', json=body, headers=H)


@pytest.fixture
def mcp_client(monkeypatch):
    monkeypatch.setattr(server, 'MCP_TOKEN', TOKEN)
    return TestClient(server.app)


def test_endpoint_is_absent_until_a_token_is_set(monkeypatch):
    monkeypatch.setattr(server, 'MCP_TOKEN', '')
    assert TestClient(server.app).post('/mcp', json={}).status_code == 404


def test_the_app_password_does_not_open_it(mcp_client):
    assert mcp_client.post('/mcp', json={}).status_code == 401
    assert mcp_client.post('/mcp', json={}, auth=('tester', 'secret')).status_code == 401
    assert mcp_client.post('/mcp', json={}, headers={'Authorization': 'Bearer ' + 'b' * 40}).status_code == 401


def test_initialize_and_tool_list(mcp_client):
    r = call(mcp_client, 'initialize').json()
    assert r['result']['serverInfo']['name'] == 'portfolio-terminal'
    names = [t['name'] for t in call(mcp_client, 'tools/list').json()['result']['tools']]
    assert 'portfolio_snapshot' in names and 'what_if_frozen' in names


def test_nothing_that_fetches_rebuilds_or_imports_is_exposed():
    """The owner keeps those. An agent that can fetch can get the account rate limited."""
    names = {t['name'] for t in mcp.TOOLS}
    assert not {n for n in names if any(w in n for w in ('fetch', 'rebuild', 'import', 'commit', 'upload'))}
    for t in mcp.TOOLS:                      # every tool must be declared, callable and schema'd
        assert callable(t['handler']) and t['inputSchema']['type'] == 'object'


def test_an_unknown_tool_is_an_error_not_a_crash(mcp_client):
    r = call(mcp_client, 'tools/call', dict(name='delete_everything')).json()
    assert r['error']['code'] == -32602


def test_a_tool_failure_comes_back_as_content_not_a_transport_error(mcp_client):
    r = call(mcp_client, 'tools/call', dict(name='position', arguments=dict(symbol='!!bad'))).json()
    assert r['result']['isError'] is True
    assert 'plain ticker' in r['result']['content'][0]['text']


def test_notifications_get_no_response_body(mcp_client):
    r = mcp_client.post('/mcp', json=dict(jsonrpc='2.0', method='notifications/initialized'), headers=H)
    assert r.status_code == 202


def test_methodology_resource_reads(mcp_client):
    r = call(mcp_client, 'resources/read', dict(uri='portfolio://methodology')).json()
    assert 'activity ledger' in r['result']['contents'][0]['text']
    assert call(mcp_client, 'resources/read', dict(uri='portfolio://secrets')).json()['error']['code'] == -32602


def test_prompt_arguments_are_substituted(mcp_client):
    r = call(mcp_client, 'prompts/get', dict(name='explain_position', arguments=dict(symbol='XEQT'))).json()
    assert 'XEQT' in r['result']['messages'][0]['content']['text']


def test_series_is_downsampled(synthetic_market, fixture_bytes):
    import build_app
    import store
    store.commit(store.preview([fixture_bytes('activities_rrsp.csv')])['id'])
    build_app.main()
    out = mcp.series('VOO', field='value', range='ALL')
    assert len(out['values']) == len(out['dates']) <= 120
