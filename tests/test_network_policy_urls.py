"""Numeric URL hosts must obey the same allow/deny scope as bare IPs."""
import importlib

import pytest


@pytest.mark.parametrize('module_name', ['mcp_client', 'mcp_kali'])
@pytest.mark.parametrize('allow,disallow,url,expected', [
    (['10.78.0.10'], [], 'http://10.78.0.10:8080/', True),
    (['10.78.0.0/24'], [], 'https://10.78.0.10/path', True),
    (['10.78.0.0/24'], [], 'http://10.79.0.10/', False),
    (['10.78.0.0/24'], ['10.78.0.128/25'], 'http://10.78.0.200/', False),
    (['*'], ['10.78.0.10'], 'http://10.78.0.10:8080/', False),
    (['*'], ['10.78.0.0/24'], 'http://10.78.0.10/', False),
    (['10.78.0.0/24'], [], 'http://lab.example/', False),
    (['10.78.0.0/24'], [], 'http://10.78.0.10@198.51.100.8/', False),
    (['http://10.78.0.10:8080/demo/'], [], 'http://10.78.0.10:8080/demo/page', True),
    (['http://10.78.0.10:8080/demo/'], [], 'http://10.78.0.10:8080/other/', False),
    (['2001:db8::/64'], [], 'http://[2001:db8::1]:8080/', True),
    (['*'], ['2001:db8::/64'], 'http://[2001:db8::1]:8080/', False),
])
def test_numeric_url_scope(module_name, allow, disallow, url, expected):
    module = importlib.import_module(module_name)
    allowed, message = module._evaluate_network_policy({'allow': allow, 'disallow': disallow}, {'args': url})
    assert allowed is expected
    if not allowed:
        assert message == 'Target is not permitted by the execution policy.'


@pytest.mark.parametrize('module_name',['mcp_client','mcp_kali'])
def test_python_literal_targets_do_not_treat_methods_as_hosts(module_name):
    module=importlib.import_module(module_name)
    code='import socket\nfor host,port in [("10.51.24.2",11521),("10.46.25.2",4505)]:\n s=socket.create_connection((host,port),timeout=5)\n s.close()'
    policy={'allow':['10.51.24.0/24','10.46.25.0/24'],'disallow':['192.168.0.53/32']}
    assert module._evaluate_network_policy(policy,{'args':code},'python3')==(True,None)
    assert module._evaluate_network_policy(policy,{'args':code.replace('10.46.25.2','192.168.0.53')},'python3')[0] is False
    assert module._evaluate_network_policy(policy,{'args':code.replace('10.46.25.2','203.0.113.5')},'python3')[0] is False
    assert module._evaluate_network_policy(policy,{'args':'syntax ???'},'python3')[0] is False


@pytest.mark.parametrize('module_name',['mcp_client','mcp_kali'])
def test_python_network_policy_accepts_quoted_dash_c_source(module_name):
    module=importlib.import_module(module_name)
    policy={'allow':['10.51.24.0/24'],'disallow':[]}
    args='-c "import socket; socket.create_connection((\'10.51.24.2\', 2121), timeout=5)"'
    assert module._evaluate_network_policy(policy,{'args':args},'python3')==(True,None)


@pytest.mark.parametrize('module_name',['mcp_client','mcp_kali'])
def test_python_network_policy_rejects_malformed_dash_c(module_name):
    module=importlib.import_module(module_name)
    allowed,message=module._evaluate_network_policy({'allow':['*'],'disallow':[]},{'args':'-c import socket'},'python3')
    assert allowed is False
    assert 'exactly one source string' in message


@pytest.mark.parametrize('module_name', ['mcp_client', 'mcp_kali'])
def test_python_policy_ignores_dotted_protocol_paths_and_labels(module_name):
    module = importlib.import_module(module_name)
    policy = {'allow': ['10.187.219.0/24'], 'disallow': []}
    code = '''import socket
s = socket.create_connection(("10.187.219.2", 2121), timeout=6)
print("GET README.txt:", repr("GET finance/q2-close.txt"))
s.close()
'''
    assert module._evaluate_network_policy(policy, {'args': code}, 'python3') == (True, None)


@pytest.mark.parametrize('module_name', ['mcp_client', 'mcp_kali'])
def test_python_policy_still_enforces_hostname_destinations(module_name):
    module = importlib.import_module(module_name)
    code = '''import socket
host = "outside.example"
s = socket.create_connection((host, 443), timeout=6)
s.close()
'''
    allowed = {'allow': ['outside.example'], 'disallow': []}
    denied = {'allow': ['inside.example'], 'disallow': []}
    assert module._evaluate_network_policy(allowed, {'args': code}, 'python3') == (True, None)
    assert module._evaluate_network_policy(denied, {'args': code}, 'python3')[0] is False


@pytest.mark.parametrize('module_name', ['mcp_client', 'mcp_kali'])
def test_python_policy_tracks_hostname_destinations_from_loops(module_name):
    module = importlib.import_module(module_name)
    code = '''import socket
for host, port in [("inside.example", 443), ("outside.example", 443)]:
    s = socket.create_connection((host, port), timeout=6)
    s.close()
'''
    policy = {'allow': ['inside.example'], 'disallow': []}
    assert module._evaluate_network_policy(policy, {'args': code}, 'python3')[0] is False
