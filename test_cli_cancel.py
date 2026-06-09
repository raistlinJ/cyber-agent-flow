"""Tests for CLI cancel/interrupt handling, persistent prompt, config loading, and MCPSession cancellation."""

import asyncio
import argparse
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 1. Config: api_key_env must not clobber explicit api_key
# ---------------------------------------------------------------------------

class TestConfigApiKey:
    def test_api_key_env_does_not_overwrite_when_env_unset(self, monkeypatch):
        """api_key_env pointing to a non-existent env var must NOT blank out an existing api_key."""
        import cli

        resolved = dict(cli.BUILTIN_SESSION_DEFAULTS)
        # Simulate a config file setting api_key first, then api_key_env
        cli._apply_config_value(resolved, "api_key", "sk-hardcoded-secret")
        # The env var does not exist
        monkeypatch.delenv("NONEXISTENT_KEY_VAR", raising=False)
        cli._apply_config_value(resolved, "api_key_env", "NONEXISTENT_KEY_VAR")

        assert resolved["api_key"] == "sk-hardcoded-secret"

    def test_api_key_env_overwrites_when_env_is_set(self, monkeypatch):
        """api_key_env pointing to a real env var should override api_key."""
        import cli

        resolved = dict(cli.BUILTIN_SESSION_DEFAULTS)
        cli._apply_config_value(resolved, "api_key", "sk-hardcoded-secret")
        monkeypatch.setenv("MY_API_KEY", "sk-from-env")
        cli._apply_config_value(resolved, "api_key_env", "MY_API_KEY")

        assert resolved["api_key"] == "sk-from-env"

    def test_api_key_env_empty_string_env_does_not_overwrite(self, monkeypatch):
        """api_key_env pointing to an empty env var should NOT overwrite."""
        import cli

        resolved = dict(cli.BUILTIN_SESSION_DEFAULTS)
        cli._apply_config_value(resolved, "api_key", "sk-hardcoded-secret")
        monkeypatch.setenv("EMPTY_KEY", "")
        cli._apply_config_value(resolved, "api_key_env", "EMPTY_KEY")

        assert resolved["api_key"] == "sk-hardcoded-secret"

    def test_config_file_api_key_loads_correctly(self, tmp_path, monkeypatch):
        """End-to-end: api_key in config file is picked up by _resolve_session_args."""
        import cli

        config = {
            "provider": "openai",
            "url": "https://api.openai.com",
            "model": "gpt-4",
            "api_key": "sk-from-config-file",
            "context_window": 8192,
            "max_turns": 20,
            "tool_timeout": 120,
        }
        config_path = tmp_path / "test_config.json"
        config_path.write_text(json.dumps(config))

        parser = argparse.ArgumentParser()
        cli._add_session_args(parser)
        args = parser.parse_args(["--config", str(config_path)])
        resolved = cli._resolve_session_args(args)

        assert resolved.api_key == "sk-from-config-file"


# ---------------------------------------------------------------------------
# 2. Persistent prompt (TerminalEventHandler scroll region)
# ---------------------------------------------------------------------------

class TestPersistentPrompt:
    def _make_handler(self):
        import cli
        return cli.TerminalEventHandler(tool_output_chars=4000, verbose=False)

    def test_bar_starts_inactive(self):
        handler = self._make_handler()
        assert handler._bar_active is False

    def test_activate_sets_bar_active(self):
        handler = self._make_handler()
        # Redirect stdout so escape codes don't mess up test output
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            handler.activate_bar()
            assert handler._bar_active is True
        finally:
            sys.stdout = old_stdout
            handler._bar_active = False  # cleanup

    def test_deactivate_clears_bar_active(self):
        handler = self._make_handler()
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            handler.activate_bar()
            handler.deactivate_bar()
            assert handler._bar_active is False
        finally:
            sys.stdout = old_stdout

    def test_deactivate_when_not_active_is_noop(self):
        handler = self._make_handler()
        # Should not raise
        handler.deactivate_bar()
        assert handler._bar_active is False

    def test_activate_twice_is_idempotent(self):
        handler = self._make_handler()
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            handler.activate_bar()
            handler.activate_bar()
            assert handler._bar_active is True
        finally:
            sys.stdout = old_stdout
            handler._bar_active = False

    def test_output_when_bar_inactive_uses_print(self, capsys):
        handler = self._make_handler()
        handler._output("hello world")
        captured = capsys.readouterr()
        assert "hello world" in captured.out

    def test_output_when_bar_active_writes_to_stdout(self):
        handler = self._make_handler()
        old_stdout = sys.stdout
        buf = io.StringIO()
        sys.stdout = buf
        try:
            handler._bar_active = True
            handler._output("test output")
            output = buf.getvalue()
            assert "test output" in output
        finally:
            sys.stdout = old_stdout
            handler._bar_active = False

    def test_prompt_prefix_updates(self):
        import cli
        handler = self._make_handler()
        handler.prompt_prefix = f"{cli.Colors.ACCENT_PRIMARY}caf[isess-001]>{cli.Colors.RESET} "
        assert "isess-001" in handler.prompt_prefix


# ---------------------------------------------------------------------------
# 3. Event handler routes events through _output
# ---------------------------------------------------------------------------

class TestEventHandlerRouting:
    def _make_handler(self):
        import cli
        return cli.TerminalEventHandler(tool_output_chars=4000, verbose=True)

    def test_status_event_routes_through_output(self, capsys):
        handler = self._make_handler()
        handler({"type": "status", "message": "Calling model..."})
        captured = capsys.readouterr()
        assert "Calling model..." in captured.out

    def test_tool_call_event_tracks_active_tool(self):
        handler = self._make_handler()
        handler({"type": "tool_call", "tool": "nmap", "args": {}})
        assert handler._active_tool_name == "nmap"

    def test_tool_result_event_clears_active_tool(self):
        handler = self._make_handler()
        handler({"type": "tool_call", "tool": "nmap", "args": {}})
        assert handler._active_tool_name == "nmap"
        handler({"type": "tool_result", "tool": "nmap", "result": "done", "exit_code": 0, "duration_ms": 100})
        assert handler._active_tool_name is None

    def test_error_event_clears_active_tool(self):
        handler = self._make_handler()
        handler({"type": "tool_call", "tool": "bash", "args": {}})
        handler({"type": "error", "message": "Something broke"})
        assert handler._active_tool_name is None

    def test_chat_done_event_clears_active_tool(self):
        handler = self._make_handler()
        handler({"type": "tool_call", "tool": "bash", "args": {}})
        handler({"type": "chat_done", "message": "Ready"})
        assert handler._active_tool_name is None

    def test_response_event_outputs_text(self, capsys):
        handler = self._make_handler()
        handler({"type": "response", "text": "Here is my analysis."})
        captured = capsys.readouterr()
        assert "Here is my analysis." in captured.out

    def test_context_usage_event_verbose(self, capsys):
        handler = self._make_handler()
        handler.verbose = True
        handler({"type": "context_usage", "used": 1000, "budget": 8192, "model_max": 128000})
        captured = capsys.readouterr()
        assert "1000" in captured.out
        assert "8192" in captured.out

    def test_context_usage_event_not_verbose(self, capsys):
        handler = self._make_handler()
        handler.verbose = False
        handler({"type": "context_usage", "used": 1000, "budget": 8192, "model_max": 128000})
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_isess_created_adds_to_known_ids(self):
        known = set()
        import cli
        handler = cli.TerminalEventHandler(tool_output_chars=4000, known_session_ids=known)
        handler({"type": "isess_created", "session_id": "isess-abc", "session_kind": "interactive"})
        assert "isess-abc" in known

    def test_isess_closed_removes_from_known_ids(self):
        known = {"isess-abc"}
        import cli
        handler = cli.TerminalEventHandler(tool_output_chars=4000, known_session_ids=known)
        handler({"type": "isess_closed", "session_id": "isess-abc"})
        assert "isess-abc" not in known


# ---------------------------------------------------------------------------
# 4. MCPSession._current_tool_task tracking and cancel
# ---------------------------------------------------------------------------

class TestMCPSessionCancelTracking:
    def test_current_tool_task_initialized_to_none(self):
        import mcp_client
        session = mcp_client.MCPSession(
            ollama_url="http://localhost:11434",
            model="test-model",
            server_command="python mcp_kali.py",
            run_id="test-run",
        )
        assert session._current_tool_task is None

    def test_chat_clears_current_tool_task_in_finally(self):
        """After chat() finishes (even with error), _current_tool_task should be None."""
        import mcp_client

        events = []
        session = mcp_client.MCPSession(
            ollama_url="http://localhost:11434",
            model="test-model",
            server_command="python mcp_kali.py",
            run_id="test-run",
            event_callback=events.append,
        )
        # Simulate started state so chat() doesn't short-circuit
        session._started = True
        session._current_tool_task = asyncio.Future()  # simulate leftover

        async def _fake_agent_loop(*args, **kwargs):
            raise RuntimeError("Simulated crash")

        session._run_agent_loop = _fake_agent_loop

        asyncio.run(session.chat("test prompt"))

        assert session._current_tool_task is None

    def test_cancel_event_checked_at_loop_top(self):
        """When cancel_event is pre-set, _run_agent_loop should return immediately."""
        import mcp_client

        events = []
        session = mcp_client.MCPSession(
            ollama_url="http://localhost:11434",
            model="test-model",
            server_command="python mcp_kali.py",
            run_id="test-run",
            event_callback=events.append,
        )
        session._started = True

        # We need a logger for _run_agent_loop
        from session_logger import SessionLogger
        session._logger = SessionLogger(run_id="test-cancel-check", metadata={"model": "test"})

        cancel = asyncio.Event()
        cancel.set()  # pre-set so it cancels immediately

        asyncio.run(session._run_agent_loop("test", cancel))

        event_types = [e.get("type") for e in events]
        assert "chat_done" in event_types
        # Should see "cancelled" messaging
        done_msgs = [e.get("message", "") for e in events if e.get("type") == "chat_done"]
        assert any("cancelled" in m.lower() or "cancel" in m.lower() for m in done_msgs)


# ---------------------------------------------------------------------------
# 5. Cancel idempotency guard (_cancel_fired pattern)
# ---------------------------------------------------------------------------

class TestCancelIdempotency:
    def test_cancel_fired_prevents_double_cancel(self):
        """Simulate the _cancel_fired guard logic used in both _run_prompt and _chat."""
        cancel_event = asyncio.Event()
        _cancel_fired = False
        cancel_count = 0

        def sigint_handler():
            nonlocal _cancel_fired, cancel_count
            if _cancel_fired:
                return  # swallowed
            _cancel_fired = True
            cancel_count += 1
            cancel_event.set()

        # First press
        sigint_handler()
        assert cancel_count == 1
        assert cancel_event.is_set()

        # Second press — should be swallowed
        sigint_handler()
        assert cancel_count == 1  # unchanged

        # Third press — still swallowed
        sigint_handler()
        assert cancel_count == 1

    def test_cancel_and_force_analyze_exclusive(self):
        """If cancel fires first, force_analyze should be swallowed."""
        _cancel_fired = False
        next_prompt_override = None

        def stdin_handler(cmd):
            nonlocal _cancel_fired, next_prompt_override
            if cmd in {"/force_analyze", "/cancel", "/exit"}:
                if _cancel_fired:
                    return "swallowed"
                _cancel_fired = True
                if cmd == "/force_analyze":
                    next_prompt_override = "analyze prompt"
                return "fired"

        result1 = stdin_handler("/cancel")
        assert result1 == "fired"
        assert next_prompt_override is None

        result2 = stdin_handler("/force_analyze")
        assert result2 == "swallowed"
        assert next_prompt_override is None  # should NOT have been set

    def test_force_analyze_sets_next_prompt(self):
        """If force_analyze fires first, it should set next_prompt_override."""
        _cancel_fired = False
        next_prompt_override = None

        def stdin_handler(cmd):
            nonlocal _cancel_fired, next_prompt_override
            if cmd in {"/force_analyze", "/cancel", "/exit"}:
                if _cancel_fired:
                    return "swallowed"
                _cancel_fired = True
                if cmd == "/force_analyze":
                    next_prompt_override = "Stop And Analyze"
                return "fired"

        result = stdin_handler("/force_analyze")
        assert result == "fired"
        assert next_prompt_override == "Stop And Analyze"


# ---------------------------------------------------------------------------
# 6. Slash command list includes new commands
# ---------------------------------------------------------------------------

class TestSlashCommands:
    def test_cancel_in_slash_commands(self):
        import cli
        assert "/cancel" in cli.SLASH_COMMANDS

    def test_force_analyze_in_slash_commands(self):
        import cli
        assert "/force_analyze" in cli.SLASH_COMMANDS

    def test_stop_not_in_slash_commands(self):
        """We removed /stop."""
        import cli
        assert "/stop" not in cli.SLASH_COMMANDS

    def test_kill_not_in_slash_commands(self):
        """We removed /kill (from SLASH_COMMANDS, keep in timeout prompt)."""
        import cli
        assert "/kill" not in cli.SLASH_COMMANDS


# ---------------------------------------------------------------------------
# 7. _prompt_choice temporarily deactivates bar
# ---------------------------------------------------------------------------

class TestPromptChoiceBarDeactivation:
    def test_prompt_choice_deactivates_and_reactivates_bar(self, monkeypatch):
        import cli

        handler = cli.TerminalEventHandler(tool_output_chars=4000)
        handler._bar_active = True

        deactivate_called = False
        activate_called = False

        def mock_deactivate():
            nonlocal deactivate_called
            deactivate_called = True
            handler._bar_active = False

        def mock_activate():
            nonlocal activate_called
            activate_called = True
            handler._bar_active = True

        handler.deactivate_bar = mock_deactivate
        handler.activate_bar = mock_activate

        # Mock input() to return the default and isatty to return True
        monkeypatch.setattr("builtins.input", lambda prompt: "")
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        result = handler._prompt_choice("Test?", ("yes", "no"), "yes")

        assert result == "yes"
        assert deactivate_called is True
        assert activate_called is True

    def test_prompt_choice_no_deactivate_when_bar_inactive(self, monkeypatch):
        import cli

        handler = cli.TerminalEventHandler(tool_output_chars=4000)
        handler._bar_active = False

        deactivate_called = False

        def mock_deactivate():
            nonlocal deactivate_called
            deactivate_called = True
            handler._bar_active = False

        handler.deactivate_bar = mock_deactivate
        monkeypatch.setattr("builtins.input", lambda prompt: "")

        result = handler._prompt_choice("Test?", ("yes", "no"), "no")

        assert result == "no"
        assert deactivate_called is False


# ---------------------------------------------------------------------------
# 8. Timer behavior with bar active vs inactive
# ---------------------------------------------------------------------------

class TestTimerBehavior:
    def test_clear_timer_line_noop_when_bar_active(self):
        """When bar is active, _clear_timer_line should not write escape codes."""
        import cli

        handler = cli.TerminalEventHandler(tool_output_chars=4000)
        handler._bar_active = True
        handler._active_tool_name = "nmap"

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            handler._clear_timer_line()
            output = buf.getvalue()
            assert output == ""  # no inline clear when bar is active
        finally:
            sys.stdout = old_stdout

    def test_clear_timer_line_clears_when_bar_inactive_and_tool_active(self):
        """When bar is inactive and tool is running, _clear_timer_line should clear."""
        import cli

        handler = cli.TerminalEventHandler(tool_output_chars=4000)
        handler._bar_active = False
        handler._active_tool_name = "nmap"

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            handler._clear_timer_line()
            output = buf.getvalue()
            assert "\r" in output or "\033[K" in output
        finally:
            sys.stdout = old_stdout


# ---------------------------------------------------------------------------
# 9. _emit_chat_cancelled emits correct events
# ---------------------------------------------------------------------------

class TestEmitChatCancelled:
    def test_emits_status_and_chat_done(self):
        import mcp_client

        events = []
        mcp_client._emit_chat_cancelled(events.append)

        assert len(events) == 2
        assert events[0]["type"] == "status"
        assert "cancelled" in events[0]["message"].lower()
        assert events[1]["type"] == "chat_done"


# ---------------------------------------------------------------------------
# 10. Config loading edge cases
# ---------------------------------------------------------------------------

class TestConfigLoading:
    def test_load_nonexistent_config_raises(self):
        import cli
        import pytest

        with pytest.raises(FileNotFoundError):
            cli._load_session_config("/nonexistent/path/config.json")

    def test_load_valid_config(self, tmp_path):
        import cli

        config = {"provider": "openai", "model": "gpt-4", "api_key": "sk-test"}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        result = cli._load_session_config(str(config_path))
        assert result["provider"] == "openai"
        assert result["api_key"] == "sk-test"

    def test_apply_config_value_tool_timeout(self):
        import cli

        resolved = dict(cli.BUILTIN_SESSION_DEFAULTS)
        cli._apply_config_value(resolved, "tool_timeout", "300")
        assert resolved["tool_timeout"] == 300

    def test_apply_config_value_unknown_key_raises(self):
        import cli
        import pytest

        resolved = dict(cli.BUILTIN_SESSION_DEFAULTS)
        with pytest.raises(ValueError, match="Unsupported"):
            cli._apply_config_value(resolved, "unknown_key", "value")


# ---------------------------------------------------------------------------
# 11. _InputBuffer character-by-character input
# ---------------------------------------------------------------------------

class TestInputBuffer:
    def _make(self):
        import cli
        return cli._InputBuffer()

    def test_regular_chars_build_text(self):
        buf = self._make()
        assert buf.add_char("h") is None
        assert buf.add_char("i") is None
        assert buf.text == "hi"

    def test_enter_returns_line_and_clears(self):
        buf = self._make()
        buf.add_char("/")
        buf.add_char("c")
        buf.add_char("a")
        line = buf.add_char("\n")
        assert line == "/ca"
        assert buf.text == ""

    def test_carriage_return_also_submits(self):
        buf = self._make()
        buf.add_char("x")
        assert buf.add_char("\r") == "x"

    def test_backspace_deletes_last_char(self):
        buf = self._make()
        buf.add_char("a")
        buf.add_char("b")
        buf.add_char("\x7f")  # backspace
        assert buf.text == "a"

    def test_backspace_on_empty_is_noop(self):
        buf = self._make()
        buf.add_char("\x7f")
        assert buf.text == ""

    def test_ctrl_h_also_deletes(self):
        buf = self._make()
        buf.add_char("x")
        buf.add_char("\x08")  # ctrl-h
        assert buf.text == ""

    def test_ctrl_u_clears_line(self):
        buf = self._make()
        buf.add_char("h")
        buf.add_char("e")
        buf.add_char("l")
        buf.add_char("\x15")  # ctrl-u
        assert buf.text == ""

    def test_ctrl_w_deletes_last_word(self):
        buf = self._make()
        for ch in "/force ":
            buf.add_char(ch)
        buf.add_char("x")
        buf.add_char("\x17")  # ctrl-w
        assert buf.text == "/force "

    def test_ctrl_w_on_single_word_clears_all(self):
        buf = self._make()
        for ch in "/cancel":
            buf.add_char(ch)
        buf.add_char("\x17")
        assert buf.text == ""

    def test_escape_sequence_swallowed(self):
        """Arrow keys (\033[A) should be silently consumed."""
        buf = self._make()
        buf.add_char("x")
        buf.add_char("\033")  # ESC
        buf.add_char("[")    # bracket
        buf.add_char("A")    # up arrow
        assert buf.text == "x"  # no extra characters

    def test_escape_sequence_with_tilde(self):
        """Delete key (\033[3~) should be consumed."""
        buf = self._make()
        buf.add_char("y")
        buf.add_char("\033")
        buf.add_char("[")
        buf.add_char("3")
        buf.add_char("~")
        assert buf.text == "y"

    def test_non_printable_ignored(self):
        buf = self._make()
        buf.add_char("a")
        buf.add_char("\x01")  # ctrl-a
        buf.add_char("\x05")  # ctrl-e
        assert buf.text == "a"

    def test_clear_resets_everything(self):
        buf = self._make()
        buf.add_char("x")
        buf.add_char("\033")  # start escape
        buf.clear()
        assert buf.text == ""
        assert buf._in_escape is False


# ---------------------------------------------------------------------------
# 12. _InputBuffer tab completion
# ---------------------------------------------------------------------------

class TestInputBufferTabCompletion:
    def _make(self):
        import cli
        return cli._InputBuffer()

    def test_tab_on_empty_shows_all_completions(self):
        buf = self._make()
        matches = buf.tab_complete()
        assert matches is not None
        assert "/cancel" in matches
        assert "/force_analyze" in matches
        assert "/exit" in matches

    def test_tab_unique_match_completes_fully(self):
        buf = self._make()
        for ch in "/ca":
            buf.add_char(ch)
        matches = buf.tab_complete()
        assert matches is None  # uniquely completed
        assert buf.text == "/cancel"

    def test_tab_ambiguous_match_extends_common_prefix(self):
        buf = self._make()
        buf.add_char("/")
        matches = buf.tab_complete()
        # All start with "/" so prefix is "/" — no extension possible
        assert matches is not None
        assert len(matches) >= 2

    def test_tab_no_match_returns_none(self):
        buf = self._make()
        for ch in "/zzz":
            buf.add_char(ch)
        matches = buf.tab_complete()
        assert matches is None
        assert buf.text == "/zzz"  # unchanged

    def test_tab_force_prefix_completes(self):
        buf = self._make()
        for ch in "/f":
            buf.add_char(ch)
        matches = buf.tab_complete()
        # Only /force_analyze starts with /f
        assert matches is None
        assert buf.text == "/force_analyze"

    def test_tab_exit_prefix(self):
        buf = self._make()
        for ch in "/e":
            buf.add_char(ch)
        matches = buf.tab_complete()
        assert matches is None
        assert buf.text == "/exit"


# ---------------------------------------------------------------------------
# 13. Separator always visible
# ---------------------------------------------------------------------------

class TestSeparatorAlwaysVisible:
    def test_print_separator_outputs_line(self, capsys):
        import cli
        handler = cli.TerminalEventHandler(tool_output_chars=4000)
        handler._print_separator()
        captured = capsys.readouterr()
        assert "─" in captured.out

    def test_deactivate_bar_clears_all_bottom_lines(self):
        """When deactivating, all 3 bottom lines should be cleared.
        The REPL's _print_separator() draws a fresh one before the next prompt."""
        import cli
        handler = cli.TerminalEventHandler(tool_output_chars=4000)
        old_stdout = sys.stdout
        buf = io.StringIO()
        sys.stdout = buf
        try:
            handler._bar_active = True
            handler.deactivate_bar()
            output = buf.getvalue()
            # All 3 lines should be cleared (status + separator + prompt)
            clear_count = output.count("\\033[K") if "\\033[K" in output else output.count("\033[K")
            assert clear_count == 3
        finally:
            sys.stdout = old_stdout

    def test_handler_has_print_separator_method(self):
        import cli
        handler = cli.TerminalEventHandler(tool_output_chars=4000)
        assert hasattr(handler, "_print_separator")
        assert callable(handler._print_separator)

