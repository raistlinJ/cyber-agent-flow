import json


def test_gateway_defaults_are_exposed_and_applied_to_saved_session_policy(tmp_path, monkeypatch):
    import app

    monkeypatch.setattr(app, '__file__', str(tmp_path / 'app.py'))
    (tmp_path / 'configs').mkdir()
    config_path = tmp_path / 'configs' / 'cli.json'
    config = {
        'url': 'http://203.0.113.20:11434', 'api_key': 'secret',
        'llm_route_gateway': '192.168.80.2', 'llm_route_gateway_managed': True,
        'network_policy': {'allow': ['10.0.0.0/24'], 'disallow': ['192.168.80.2']},
    }
    config_path.write_text(json.dumps(config))
    defaults = app._web_cli_defaults()
    assert defaults['policyDraft'] == config['network_policy']
    assert defaults['llmRouteGateway'] == '192.168.80.2'
    assert defaults['llmRouteGatewayAdded'] is True
    assert 'secret' not in json.dumps(defaults)
    saved = {'allow': ['*'], 'disallow': ['10.0.0.10']}
    assert app._session_network_policy(saved) == {
        'allow': ['*'], 'disallow': ['10.0.0.10', '192.168.80.2'],
    }
    assert saved['disallow'] == ['10.0.0.10']
    # A desktop update is picked up without restarting the web server.
    config['llm_route_gateway'] = '192.168.80.3'
    config_path.write_text(json.dumps(config))
    assert app._session_network_policy(saved)['disallow'] == ['10.0.0.10', '192.168.80.3']


def test_logging_defaults_enable_every_channel_except_capture():
    from html.parser import HTMLParser
    import app

    inputs = {}

    class Inputs(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == 'input':
                values = dict(attrs)
                inputs[values.get('id')] = values

    Inputs().feed(app.app.test_client().get('/').get_data(as_text=True))
    for name in ('keylogger-enable-toggle', 'log-syscalls-toggle', 'log-prompts-toggle',
                 'log-tools-toggle', 'log-artifacts-toggle', 'log-analysis-toggle', 'log-metadata-toggle'):
        assert 'checked' in inputs[name]
    assert 'checked' not in inputs['log-network-capture-toggle']
