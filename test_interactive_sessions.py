"""
Tests for interactive session preservation and handoff behavior.

Run with: pytest test_interactive_sessions.py -v
"""

import os
import sys
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestInteractiveSessionDetection:
    def test_detects_meterpreter_session_open_banner(self):
        from mcp_kali import _looks_like_interactive_session

        stdout = "[*] Meterpreter session 1 opened (10.0.0.1:4444 -> 10.0.0.2:5555)"
        assert _looks_like_interactive_session("msf_run", ["msfconsole"], stdout, "") is True

    def test_detects_meterpreter_prompt(self):
        from mcp_kali import _looks_like_interactive_session

        stdout = "meterpreter > "
        assert _looks_like_interactive_session("msf_run", ["msfconsole"], stdout, "") is True

    def test_ignores_normal_noninteractive_output(self):
        from mcp_kali import _looks_like_interactive_session

        stdout = "[*] Exploit completed, but no session was created."
        assert _looks_like_interactive_session("msf_run", ["msfconsole"], stdout, "") is False

    def test_plain_msf_prompt_is_not_treated_as_preservable_session(self):
        from mcp_kali import _looks_like_preservable_interactive_session

        stdout = "msf6 exploit(multi/handler) > "
        assert _looks_like_preservable_interactive_session("msf_run", stdout, "") is False

    def test_meterpreter_prompt_is_treated_as_preservable_session(self):
        from mcp_kali import _looks_like_preservable_interactive_session

        stdout = "meterpreter > "
        assert _looks_like_preservable_interactive_session("msf_run", stdout, "") is True

    def test_unix_shell_prompt_is_treated_as_preservable_session(self):
        from mcp_kali import _looks_like_preservable_interactive_session

        stdout = "root@target:/tmp# "
        assert _looks_like_preservable_interactive_session("shell_dangerous", stdout, "") is True

    def test_plain_msf_prompt_is_treated_as_preservable_for_shell_dangerous(self):
        from mcp_kali import _looks_like_preservable_interactive_session

        stdout = "msf > "
        assert _looks_like_preservable_interactive_session("shell_dangerous", stdout, "") is True

    def test_msf_prompt_with_stty_warning_is_treated_as_preservable_for_shell_dangerous(self):
        from mcp_kali import _looks_like_preservable_interactive_session

        stdout = """stty: 'standard input': Inappropriate ioctl for device
stty: 'standard input': Inappropriate ioctl for device
msf exploit(linux/http/webmin_backdoor) > stty: 'standard input': Inappropriate ioctl for device"""
        assert _looks_like_preservable_interactive_session("shell_dangerous", stdout, "") is True

    def test_msf_run_prompt_with_stty_warning_is_still_not_preservable_without_session(self):
        from mcp_kali import _looks_like_preservable_interactive_session

        stdout = """stty: 'standard input': Inappropriate ioctl for device
msf exploit(linux/http/webmin_backdoor) > stty: 'standard input': Inappropriate ioctl for device"""
        assert _looks_like_preservable_interactive_session("msf_run", stdout, "") is False

    def test_reverse_perl_session_open_is_detected(self):
        from mcp_kali import _looks_like_interactive_session, _looks_like_preservable_interactive_session

        stdout = "[*] Perl session 1 opened (10.0.0.1:4444 -> 10.0.0.2:5555)\nmeterpreter > "
        assert _looks_like_interactive_session("msf_run", ["msfconsole"], stdout, "") is True
        assert _looks_like_preservable_interactive_session("msf_run", stdout, "") is True

    def test_reverse_python_session_open_is_detected(self):
        from mcp_kali import _looks_like_interactive_session, _looks_like_preservable_interactive_session

        stdout = "[*] Python session 1 opened (10.0.0.1:4444 -> 10.0.0.2:5555)\nshell > "
        assert _looks_like_interactive_session("msf_run", ["msfconsole"], stdout, "") is True
        assert _looks_like_preservable_interactive_session("msf_run", stdout, "") is True

    def test_generic_session_opened_is_detected(self):
        from mcp_kali import _looks_like_interactive_session, _looks_like_preservable_interactive_session

        stdout = "[*] Session 1 created in the background."
        assert _looks_like_interactive_session("msf_run", ["msfconsole"], stdout, "") is True
        assert _looks_like_preservable_interactive_session("msf_run", stdout, "") is True

    def test_bash_session_open_is_detected(self):
        from mcp_kali import _looks_like_interactive_session, _looks_like_preservable_interactive_session

        stdout = "[*] Bash session 1 opened (10.0.0.1:4444 -> 10.0.0.2:5555)\nroot@target:/tmp# "
        assert _looks_like_interactive_session("msf_run", ["msfconsole"], stdout, "") is True
        assert _looks_like_preservable_interactive_session("msf_run", stdout, "") is True


class TestManualRecreationInstructions:
    def test_msf_manual_recreation_mentions_msfconsole(self):
        from mcp_kali import _manual_recreation_instructions

        message = _manual_recreation_instructions(
            "msf_run",
            {"args": "use exploit/multi/handler; set payload windows/meterpreter/reverse_tcp; run"},
            ["msfconsole", "-q", "-x", "use exploit/multi/handler; run -z"],
        )

        assert "start `msfconsole`" in message
        assert "remove it if you want to keep the session attached" in message

    def test_generic_manual_recreation_uses_shell_join(self):
        from mcp_kali import _manual_recreation_instructions

        message = _manual_recreation_instructions("custom_tool", {}, ["python3", "-m", "http.server", "8080"])
        assert "python3 -m http.server 8080" in message


class TestMsfRunArgsNormalization:
    def test_exploit_workflow_defaults_autocheck_false(self):
        from mcp_kali import _prepare_msf_run_args

        prepared = _prepare_msf_run_args("use exploit/linux/http/webmin_backdoor; set RHOSTS 10.0.0.1; exploit")

        assert "set AutoCheck false" in prepared
        assert prepared.count("set AutoCheck false") == 1
        assert "exploit -z" in prepared

    def test_exploit_workflow_respects_explicit_autocheck_setting(self):
        from mcp_kali import _prepare_msf_run_args

        prepared = _prepare_msf_run_args("use exploit/linux/http/webmin_backdoor; set AutoCheck true; exploit")

        assert "set AutoCheck false" not in prepared
        assert "set AutoCheck true" in prepared

    def test_auxiliary_workflow_does_not_inject_autocheck(self):
        from mcp_kali import _prepare_msf_run_args

        prepared = _prepare_msf_run_args("use auxiliary/scanner/http/http_version; run")

        assert "set AutoCheck false" not in prepared


class TestInteractiveSessionToolResult:
    def test_interactive_session_list_returns_status_lines(self):
        from mcp_kali import _interactive_session_tool_result

        fake_proc = Mock()
        fake_proc.poll.return_value = None
        session = {
            "id": "isess-001",
            "tool": "msf_run",
            "command": ["msfconsole", "-q"],
            "proc": fake_proc,
            "master_fd": None,
            "history": "",
            "pending_output": "",
            "created_at": 0,
            "last_output_at": 0,
            "closed": False,
            "closed_at": None,
            "returncode": None,
        }

        with patch.dict("mcp_kali._interactive_sessions", {"isess-001": session}, clear=True):
            output, exit_code = _interactive_session_tool_result("interactive_session_list", {})

        assert exit_code == 0
        assert "isess-001: active" in output

    def test_interactive_session_read_drains_pending_output(self):
        from mcp_kali import _interactive_session_tool_result

        fake_proc = Mock()
        fake_proc.poll.return_value = None
        session = {
            "id": "isess-001",
            "tool": "msf_run",
            "command": ["msfconsole", "-q"],
            "proc": fake_proc,
            "master_fd": None,
            "history": "already seen",
            "pending_output": "new output",
            "created_at": 0,
            "last_output_at": 0,
            "closed": False,
            "closed_at": None,
            "returncode": None,
        }

        with patch.dict("mcp_kali._interactive_sessions", {"isess-001": session}, clear=True):
            output, exit_code = _interactive_session_tool_result("interactive_session_read", {"session_id": "isess-001"})

        assert exit_code == 0
        assert output == "new output"
        assert session["pending_output"] == ""

    def test_interactive_session_write_rejects_closed_session(self):
        from mcp_kali import _interactive_session_tool_result

        fake_proc = Mock()
        fake_proc.poll.return_value = 0
        session = {
            "id": "isess-001",
            "tool": "msf_run",
            "command": ["msfconsole", "-q"],
            "proc": fake_proc,
            "master_fd": None,
            "history": "",
            "pending_output": "",
            "created_at": 0,
            "last_output_at": 0,
            "closed": True,
            "closed_at": 0,
            "returncode": 0,
        }

        with patch.dict("mcp_kali._interactive_sessions", {"isess-001": session}, clear=True):
            output, exit_code = _interactive_session_tool_result(
                "interactive_session_write",
                {"session_id": "isess-001", "input": "help"},
            )

        assert exit_code == -1
        assert "already closed" in output

    def test_interactive_session_write_rejects_read_only_background_session(self):
        from mcp_kali import _interactive_session_tool_result

        fake_proc = Mock()
        fake_proc.poll.return_value = None
        session = {
            "id": "isess-001",
            "tool": "tcpdump",
            "command": ["tcpdump", "-ni", "eth0"],
            "proc": fake_proc,
            "master_fd": None,
            "stdout_fd": None,
            "stderr_fd": None,
            "writable": False,
            "session_kind": "background",
            "history": "",
            "pending_output": "",
            "created_at": 0,
            "last_output_at": 0,
            "closed": False,
            "closed_at": None,
            "returncode": None,
        }

        with patch.dict("mcp_kali._interactive_sessions", {"isess-001": session}, clear=True):
            output, exit_code = _interactive_session_tool_result(
                "interactive_session_write",
                {"session_id": "isess-001", "input": "help"},
            )

        assert exit_code == -1
        assert "read-only" in output


class TestInteractiveSessionConfig:
    def test_msf_run_is_interactive_capable_by_default(self):
        from mcp_kali import _tool_supports_interactive_sessions

        assert _tool_supports_interactive_sessions("msf_run", {}) is True

    def test_shell_dangerous_is_interactive_capable_by_default(self):
        from mcp_kali import _tool_supports_interactive_sessions

        assert _tool_supports_interactive_sessions("shell_dangerous", {}) is True

    def test_config_can_enable_interactive_capable_for_other_tools(self):
        from mcp_kali import _tool_supports_interactive_sessions

        assert _tool_supports_interactive_sessions("shell_dangerous", {"interactive_capable": True}) is True
        assert _tool_supports_interactive_sessions("shell_dangerous", {"interactive_capable": False}) is False


class TestInteractiveSubprocessSpawn:
    def test_interactive_subprocess_gives_child_a_controlling_tty(self):
        from mcp_kali import _run_interactive_subprocess_with_timeout_prompt

        result = _run_interactive_subprocess_with_timeout_prompt(
            ["/bin/sh", "-lc", "stty -a >/dev/null && printf 'TTY_OK\\n'"],
            timeout_seconds=5,
            tool_name="shell_dangerous",
            arguments={"args": "stty -a >/dev/null && printf 'TTY_OK\\n'"},
            first_checkpoint_seconds=5,
            idle_timeout_seconds=5,
        )

        assert result["returncode"] == 0
        assert "TTY_OK" in result["stdout"]
        assert "Inappropriate ioctl for device" not in result["stdout"]