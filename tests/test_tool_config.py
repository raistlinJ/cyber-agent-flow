import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tool_config import default_tools_path, session_tools_path


def test_session_catalogs_are_private_and_do_not_mutate_defaults(tmp_path):
    shipped = tmp_path / 'kali_tools.default.json'
    shipped.write_text('{"tools": [{"name": "base"}]}')
    first = Path(session_tools_path(tmp_path, 'run-one', {'tools': [{'name': 'first'}]}))
    second = Path(session_tools_path(tmp_path, 'run-two', {'tools': [{'name': 'second'}]}))
    assert json.loads(first.read_text())['tools'][0]['name'] == 'first'
    assert json.loads(second.read_text())['tools'][0]['name'] == 'second'
    assert first.stat().st_mode & 0o777 == 0o600
    assert shipped.read_text() == '{"tools": [{"name": "base"}]}'
    assert default_tools_path(tmp_path) == shipped
    local = tmp_path / 'kali_tools.json'
    local.write_text('{"tools": []}')
    assert default_tools_path(tmp_path) == local
    with pytest.raises(ValueError):
        session_tools_path(tmp_path, '../escape', {'tools': []})


def test_cli_reads_explicit_and_migrated_settings_without_copying(tmp_path, monkeypatch):
    import cli
    monkeypatch.setattr(cli, 'PROJECT_DIR', tmp_path)
    (tmp_path / 'kali_tools.default.json').write_text('{"tools": [{"name": "base"}]}')
    local = tmp_path / 'kali_tools.json'
    local.write_text('{"tools": [{"name": "custom"}]}')
    assert cli._read_tools_config('kali_tools.json')[1] == ['custom']
    assert cli._read_tools_config(str(tmp_path / 'kali_tools.default.json'))[1] == ['base']
    assert cli._read_tools_config(str(local))[1] == ['custom']
    assert 'base' in (tmp_path / 'kali_tools.default.json').read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [True, False])
async def test_mcp_child_receives_session_catalog_and_preserves_eval_override(tmp_path, monkeypatch, explicit):
    import mcp_client
    monkeypatch.setenv('CAF_RUN_BASE_DIR', str(tmp_path))
    monkeypatch.setenv('CAF_TOOLS_CONFIG_PATH', '/evaluation/catalog.json')
    session = mcp_client.MCPSession(ollama_url='http://localhost', model='test', server_command='python mcp_kali.py',
                                    tools_config_path='/session/catalog.json' if explicit else None)
    captured = {}
    def params(**kwargs):
        captured.update(kwargs)
        raise RuntimeError('stop before transport')
    monkeypatch.setattr(mcp_client, 'StdioServerParameters', params)
    with pytest.raises(RuntimeError, match='stop before transport'):
        await session.start()
    assert captured['env']['CAF_TOOLS_CONFIG_PATH'] == ('/session/catalog.json' if explicit else '/evaluation/catalog.json')
    assert mcp_client.os.environ['CAF_TOOLS_CONFIG_PATH'] == '/evaluation/catalog.json'


def test_web_start_preserves_shipped_catalog_and_passes_snapshot(tmp_path, monkeypatch):
    import app
    import mcp_client
    monkeypatch.setattr(app, '__file__', str(tmp_path / 'app.py'))
    monkeypatch.setattr(app, '_event_store', MagicMock())
    monkeypatch.setattr(app, '_session_state', dict(app._session_state, status='idle', session=None, thread=None))
    shipped = tmp_path / 'kali_tools.default.json'
    shipped.write_text('{"tools": [{"name": "base"}]}')
    received = {}
    class Session:
        def __init__(self, **kwargs): received.update(kwargs)
        async def start(self): raise RuntimeError('stop before network')
    monkeypatch.setattr(mcp_client, 'MCPSession', Session)
    response = app.app.test_client().post('/api/session/start', json={
        'model': 'test', 'server_command': 'python mcp_kali.py', 'tools_config': {'tools': [{'name': 'chosen'}]},
    })
    assert response.status_code == 500
    assert json.loads(Path(received['tools_config_path']).read_text()) == {'tools': [{'name': 'chosen'}]}
    assert shipped.read_text() == '{"tools": [{"name": "base"}]}'
    app._session_state['thread'].join(timeout=3)


def test_native_server_falls_back_to_shipped_defaults_but_honors_override(tmp_path, monkeypatch):
    import mcp_kali
    monkeypatch.setattr(mcp_kali, '__file__', str(tmp_path / 'mcp_kali.py'))
    monkeypatch.delenv('CAF_TOOLS_CONFIG_PATH', raising=False)
    shipped = tmp_path / 'kali_tools.default.json'
    shipped.write_text('{"tools": []}')
    assert mcp_kali._tools_config_path() == str(shipped)
    local = tmp_path / 'kali_tools.json'
    local.write_text('{"tools": [{"name": "local"}]}')
    assert mcp_kali._tools_config_path() == str(local)
    monkeypatch.setenv('CAF_TOOLS_CONFIG_PATH', '/evaluation/catalog.json')
    assert mcp_kali._tools_config_path() == '/evaluation/catalog.json'
