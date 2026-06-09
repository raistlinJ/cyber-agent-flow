"""Regression tests for shell_extended command normalization."""

from mcp_kali import _build_shell_command


def test_shell_extended_curl_injects_default_timeouts():
    cmd, error = _build_shell_command("shell_extended", {"args": "curl -s http://10.0.4.10"})

    assert error is None
    assert cmd is not None
    assert "--connect-timeout" in cmd
    assert "5" in cmd
    assert "--max-time" in cmd
    assert "30" in cmd


def test_shell_extended_curl_rejects_output_flag():
    cmd, error = _build_shell_command("shell_extended", {"args": "curl -s http://10.0.4.10 -o /tmp/out"})

    assert cmd is None
    assert error is not None
    assert "Disallowed flags" in error


def test_shell_extended_curl_rejects_excessive_max_time():
    cmd, error = _build_shell_command("shell_extended", {"args": "curl -s --max-time 999 http://10.0.4.10"})

    assert cmd is None
    assert error is not None
    assert "must be between 1 and" in error
