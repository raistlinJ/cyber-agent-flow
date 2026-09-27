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
