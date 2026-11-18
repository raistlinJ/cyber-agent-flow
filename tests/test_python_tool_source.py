import asyncio
import shlex
import sys

import mcp_kali


def test_python_tool_executes_raw_source_with_dash_c(monkeypatch):
    captured = {}
    code = "import socket\ns=socket.create_connection(('10.51.24.2',2121),timeout=5)\ns.close()"
    monkeypatch.setattr(mcp_kali, '_NETWORK_POLICY', {'allow':['10.51.24.0/24'],'disallow':[]})
    monkeypatch.setattr(mcp_kali, '_get_tools_config', lambda: {'tools':[{
        'name':'python3', 'command':sys.executable, 'allow_args':True, 'timeout_seconds':30,
    }]})

    def execute(cmd, *args, **kwargs):
        captured['cmd'] = cmd
        return {'stdout':'ok\n','stderr':'','returncode':0,'duration_ms':1}

    monkeypatch.setattr(mcp_kali, '_run_subprocess_with_timeout_prompt', execute)
    result = asyncio.run(mcp_kali.call_tool('python3', {'args':code}))
    assert captured['cmd'] == [sys.executable, '-c', code]
    assert result.content[0].text.strip() == 'ok'


def test_python_tool_normalizes_quoted_dash_c(monkeypatch):
    captured = {}
    code = "print('ok')"
    monkeypatch.setattr(mcp_kali, '_NETWORK_POLICY', {'allow':['*'],'disallow':[]})
    monkeypatch.setattr(mcp_kali, '_get_tools_config', lambda: {'tools':[{
        'name':'python3', 'command':sys.executable, 'allow_args':True, 'timeout_seconds':30,
    }]})

    def execute(cmd, *args, **kwargs):
        captured['cmd'] = cmd
        return {'stdout':'ok\n','stderr':'','returncode':0,'duration_ms':1}

    monkeypatch.setattr(mcp_kali, '_run_subprocess_with_timeout_prompt', execute)
    asyncio.run(mcp_kali.call_tool('python3', {'args':'-c "print(\'ok\')"'}))
    assert captured['cmd'] == [sys.executable, '-c', code]


def test_python_tool_normalizes_redundant_executable_and_dash_c(monkeypatch):
    captured = {}
    code = "import socket\ns=socket.create_connection(('10.51.24.2',2121),timeout=5)\ns.close()"
    monkeypatch.setattr(mcp_kali, '_NETWORK_POLICY', {'allow':['10.51.24.0/24'],'disallow':[]})
    monkeypatch.setattr(mcp_kali, '_get_tools_config', lambda: {'tools':[{
        'name':'python3', 'command':sys.executable, 'allow_args':True, 'timeout_seconds':30,
    }]})

    def execute(cmd, *args, **kwargs):
        captured['cmd'] = cmd
        return {'stdout':'ok\n','stderr':'','returncode':0,'duration_ms':1}

    monkeypatch.setattr(mcp_kali, '_run_subprocess_with_timeout_prompt', execute)
    quoted = 'python3 -c ' + shlex.quote(code)
    asyncio.run(mcp_kali.call_tool('python3', {'args': quoted}))
    assert captured['cmd'] == [sys.executable, '-c', code]


def test_python_tool_normalizes_redundant_executable_and_heredoc(monkeypatch):
    captured = {}
    code = "import socket\ns=socket.create_connection(('10.51.24.2',2121),timeout=5)\ns.close()"
    monkeypatch.setattr(mcp_kali, '_NETWORK_POLICY', {'allow':['10.51.24.0/24'],'disallow':[]})
    monkeypatch.setattr(mcp_kali, '_get_tools_config', lambda: {'tools':[{
        'name':'python3', 'command':sys.executable, 'allow_args':True, 'timeout_seconds':30,
    }]})

    def execute(cmd, *args, **kwargs):
        captured['cmd'] = cmd
        return {'stdout':'ok\n','stderr':'','returncode':0,'duration_ms':1}

    monkeypatch.setattr(mcp_kali, '_run_subprocess_with_timeout_prompt', execute)
    wrapped = "python3 - <<'PY'\n" + code + "\nPY"
    asyncio.run(mcp_kali.call_tool('python3', {'args': wrapped}))
    assert captured['cmd'] == [sys.executable, '-c', code]
