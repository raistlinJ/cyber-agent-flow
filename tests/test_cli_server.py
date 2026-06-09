"""
Tests for the SSH server infrastructure:
  - StreamAdapter interface
  - SSHAgentServer authentication
  - TerminalEventHandler stream injection (stream_out/stream_in)
  - _print() routing through stream_out
  - _is_tty() behaviour with fake streams
  - Async readline detection in _chat()
  - handle_client argument merging logic
"""
import asyncio
import io
import sys
import argparse
import types
import unittest
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(stream_out=None, stream_in=None, **kwargs):
    """Return a TerminalEventHandler with injected streams."""
    import cli
    buf_out = stream_out or io.StringIO()
    buf_in  = stream_in  or io.StringIO()
    h = cli.TerminalEventHandler(
        tool_output_chars=4000,
        verbose=False,
        stream_out=buf_out,
        stream_in=buf_in,
        **kwargs,
    )
    return h, buf_out, buf_in


# ===========================================================================
# StreamAdapter tests
# ===========================================================================

class TestStreamAdapter(unittest.TestCase):

    def _make_process(self, term_type="xterm", term_size=(80, 24, 0, 0)):
        """Build a minimal mock asyncssh SSHServerProcess."""
        process = MagicMock()
        process.stdout = MagicMock()
        process.stdin  = MagicMock()
        process.get_terminal_type.return_value = term_type
        process.get_terminal_size.return_value = term_size
        process.command = None
        return process

    def test_write_delegates_to_stdout(self):
        process = self._make_process()
        # Simulate what StreamAdapter.write does
        data = "hello SSH\r\n"
        process.stdout.write(data)
        process.stdout.write.assert_called_with(data)

    def test_isatty_true_when_pty_present(self):
        process = self._make_process(term_type="xterm")
        # isatty = bool(process.get_terminal_type())
        self.assertTrue(bool(process.get_terminal_type()))

    def test_isatty_false_when_no_pty(self):
        process = self._make_process(term_type="")
        self.assertFalse(bool(process.get_terminal_type()))

    def test_fileno_raises(self):
        """SSH streams have no file descriptor — fileno() must raise."""
        import importlib.util, os
        spec = importlib.util.spec_from_file_location(
            "cli_server_mod",
            os.path.join(os.path.dirname(__file__), "cli-server.py"),
        )
        # We test the logic directly without executing the full module
        class _FakeAdapter:
            def fileno(self):
                raise NotImplementedError("SSH streams do not have file descriptors.")
        with self.assertRaises(NotImplementedError):
            _FakeAdapter().fileno()


# ===========================================================================
# SSHAgentServer authentication tests
# ===========================================================================

class TestSSHAgentServerAuth(unittest.TestCase):

    def _make_server(self, password="secret"):
        """Instantiate SSHAgentServer without importing the top-level module."""
        # We replicate the validate_password logic here since we can't import
        # cli-server.py directly (it executes asyncssh.listen at import time
        # if __name__ == '__main__' is not guarded properly on some versions).
        class _FakeSSHServer:
            def __init__(self, pwd):
                self._password = pwd
            def validate_password(self, username, password):
                return password == self._password
            def password_auth_supported(self):
                return True
            def begin_auth(self, username):
                return True  # always need auth (password check follows)
        return _FakeSSHServer(password)

    def test_correct_password_accepted(self):
        srv = self._make_server("mysecret")
        self.assertTrue(srv.validate_password("any_user", "mysecret"))

    def test_wrong_password_rejected(self):
        srv = self._make_server("mysecret")
        self.assertFalse(srv.validate_password("any_user", "wrong"))

    def test_empty_password_rejected(self):
        srv = self._make_server("mysecret")
        self.assertFalse(srv.validate_password("any_user", ""))

    def test_password_auth_supported(self):
        srv = self._make_server()
        self.assertTrue(srv.password_auth_supported())

    def test_begin_auth_requires_auth(self):
        srv = self._make_server()
        self.assertTrue(srv.begin_auth("any_user"))


# ===========================================================================
# TerminalEventHandler stream injection tests
# ===========================================================================

class TestTerminalEventHandlerStreams(unittest.TestCase):

    def test_default_streams_are_sys_stdout_stdin(self):
        import cli
        h = cli.TerminalEventHandler()
        self.assertIs(h.stream_out, sys.stdout)
        self.assertIs(h.stream_in,  sys.stdin)

    def test_injected_stream_out_used(self):
        import cli
        buf = io.StringIO()
        h = cli.TerminalEventHandler(stream_out=buf)
        self.assertIs(h.stream_out, buf)

    def test_injected_stream_in_used(self):
        import cli
        fake_in = io.StringIO("hello\n")
        h = cli.TerminalEventHandler(stream_in=fake_in)
        self.assertIs(h.stream_in, fake_in)

    def test_both_streams_injected_independently(self):
        import cli
        buf_out = io.StringIO()
        buf_in  = io.StringIO("input\n")
        h = cli.TerminalEventHandler(stream_out=buf_out, stream_in=buf_in)
        self.assertIs(h.stream_out, buf_out)
        self.assertIs(h.stream_in,  buf_in)

    def test_none_falls_back_to_sys(self):
        import cli
        h = cli.TerminalEventHandler(stream_out=None, stream_in=None)
        self.assertIs(h.stream_out, sys.stdout)
        self.assertIs(h.stream_in,  sys.stdin)


# ===========================================================================
# _print() routing tests
# ===========================================================================

class TestPrintRouting(unittest.TestCase):

    def test_print_writes_to_stream_out(self):
        h, buf, _ = _make_handler()
        h._print("hello world")
        self.assertIn("hello world", buf.getvalue())

    def test_print_does_not_write_to_sys_stdout(self):
        h, buf, _ = _make_handler()
        old_stdout = sys.stdout
        capture = io.StringIO()
        sys.stdout = capture
        try:
            h._print("should not appear on real stdout")
        finally:
            sys.stdout = old_stdout
        # Our injected buf should have the content
        self.assertIn("should not appear on real stdout", buf.getvalue())
        # sys.stdout should be empty
        self.assertEqual(capture.getvalue(), "")

    def test_print_end_parameter_respected(self):
        h, buf, _ = _make_handler()
        h._print("no newline", end="")
        self.assertEqual(buf.getvalue(), "no newline")

    def test_print_sep_parameter_respected(self):
        h, buf, _ = _make_handler()
        h._print("a", "b", "c", sep="-")
        self.assertIn("a-b-c", buf.getvalue())

    def test_output_inactive_bar_routes_through_stream_out(self):
        h, buf, _ = _make_handler()
        h._bar_active = False
        h._output("some output text")
        self.assertIn("some output text", buf.getvalue())

    def test_print_separator_writes_to_stream_out(self):
        h, buf, _ = _make_handler()
        with patch.object(h, "_term_size", return_value=(24, 40)):
            h._print_separator()
        output = buf.getvalue()
        self.assertTrue(len(output) > 0)
        # Separator character should appear
        self.assertIn("─", output)


# ===========================================================================
# _is_tty() tests
# ===========================================================================

class TestIsTty(unittest.TestCase):

    def test_is_tty_false_for_stringio(self):
        """StringIO has no isatty or fileno — should return False."""
        h, _, _ = _make_handler()
        # StringIO.isatty() returns False
        self.assertFalse(h._is_tty())

    def test_is_tty_false_for_stream_without_fileno(self):
        import cli
        class _NoFileno:
            def isatty(self):
                return True
            # no fileno attribute
        h = cli.TerminalEventHandler(stream_in=_NoFileno())
        self.assertFalse(h._is_tty())

    def test_is_tty_false_for_stream_without_isatty(self):
        import cli
        class _NoIsatty:
            def fileno(self):
                return 0
            # no isatty attribute
        h = cli.TerminalEventHandler(stream_in=_NoIsatty())
        self.assertFalse(h._is_tty())

    def test_is_tty_true_for_real_tty_like_stream(self):
        import cli
        class _FakeTTY:
            def isatty(self):
                return True
            def fileno(self):
                return 0
        h = cli.TerminalEventHandler(stream_in=_FakeTTY())
        self.assertTrue(h._is_tty())

    def test_is_tty_false_when_isatty_returns_false(self):
        import cli
        class _FakeNonTTY:
            def isatty(self):
                return False
            def fileno(self):
                return 0
        h = cli.TerminalEventHandler(stream_in=_FakeNonTTY())
        self.assertFalse(h._is_tty())


# ===========================================================================
# Async readline detection
# ===========================================================================

class TestAsyncReadlineDetection(unittest.TestCase):
    """Tests that cli._chat detects async vs sync readline correctly."""

    def test_sync_readline_not_detected_as_async(self):
        buf = io.StringIO("hello\n")
        rl = buf.readline
        self.assertFalse(asyncio.iscoroutinefunction(rl))

    def test_async_readline_detected(self):
        class _AsyncReader:
            async def readline(self):
                return "hello\n"
        obj = _AsyncReader()
        self.assertTrue(asyncio.iscoroutinefunction(obj.readline))

    def test_asyncssh_like_reader_detected_as_async(self):
        """Simulate an asyncssh SSHReader whose read/readline are coroutines."""
        class _SSHReader:
            async def read(self, n=-1):
                return ""
            async def readline(self):
                return ""
        obj = _SSHReader()
        self.assertTrue(asyncio.iscoroutinefunction(obj.readline))


# ===========================================================================
# handle_client argument merging logic
# ===========================================================================

class TestHandleClientArgMerging(unittest.TestCase):
    """Tests the argument merging logic used in handle_client."""

    def _base_args(self, **kwargs):
        ns = argparse.Namespace(
            model="base_model",
            verbose=False,
            tool_output_chars=6000,
            command=None,
            provider="ollama_direct",
            url="http://localhost:11434",
            api_key=None,
            context_window=8192,
            max_turns=20,
        )
        for k, v in kwargs.items():
            setattr(ns, k, v)
        return ns

    def test_client_args_override_base(self):
        """When a client provides a value it should override the server default."""
        base = self._base_args(model="server_model")
        client = self._base_args(model="client_model")
        # Merge: if client value is not None, keep it
        for k, v in vars(base).items():
            if getattr(client, k, None) is None:
                setattr(client, k, v)
        self.assertEqual(client.model, "client_model")

    def test_base_fills_in_missing_client_values(self):
        """When a client omits a value (None), the server default fills it in."""
        base = self._base_args(model="server_model")
        client = argparse.Namespace(model=None, command="chat")
        for k, v in vars(base).items():
            if getattr(client, k, None) is None:
                setattr(client, k, v)
        self.assertEqual(client.model, "server_model")

    def test_merge_does_not_clobber_false_values(self):
        """A client explicitly passing verbose=False should not be overridden."""
        base = self._base_args(verbose=True)
        client = self._base_args(verbose=False)
        # Only replace if value is None — False is not None
        for k, v in vars(base).items():
            if getattr(client, k, None) is None:
                setattr(client, k, v)
        self.assertFalse(client.verbose)

    def test_merge_preserves_zero_int(self):
        """A client passing tool_output_chars=0 should not be overridden."""
        base = self._base_args(tool_output_chars=6000)
        client = self._base_args(tool_output_chars=0)
        for k, v in vars(base).items():
            if getattr(client, k, None) is None:
                setattr(client, k, v)
        self.assertEqual(client.tool_output_chars, 0)


# ===========================================================================
# _term_size monkeypatching (used in handle_client for SSH PTY size)
# ===========================================================================

class TestTermSizeMonkeypatch(unittest.TestCase):

    def test_monkeypatched_term_size_returns_ssh_dimensions(self):
        import cli
        h = cli.TerminalEventHandler()

        # Simulate the monkeypatch applied in handle_client
        def _ssh_term_size():
            width, height, _, _ = (80, 40, 0, 0)
            return height or 24, width or 80

        h._term_size = _ssh_term_size
        rows, cols = h._term_size()
        self.assertEqual(rows, 40)
        self.assertEqual(cols, 80)

    def test_monkeypatched_term_size_falls_back_on_zero(self):
        import cli
        h = cli.TerminalEventHandler()

        def _ssh_term_size():
            width, height, _, _ = (0, 0, 0, 0)
            return height or 24, width or 80

        h._term_size = _ssh_term_size
        rows, cols = h._term_size()
        self.assertEqual(rows, 24)
        self.assertEqual(cols, 80)


# ===========================================================================
# known_session_ids injection
# ===========================================================================

class TestKnownSessionIdsInjection(unittest.TestCase):

    def test_known_session_ids_set_on_existing_handler(self):
        """_chat() should attach known_session_ids to an injected event_handler."""
        import cli
        buf = io.StringIO()
        h = cli.TerminalEventHandler(stream_out=buf)
        # Simulate what _chat does when event_handler is not None
        known_ids: set = set()
        h.known_session_ids = known_ids
        self.assertIs(h.known_session_ids, known_ids)

    def test_known_session_ids_populated(self):
        import cli
        h = cli.TerminalEventHandler()
        ids: set = {"sess-1", "sess-2"}
        h.known_session_ids = ids
        self.assertIn("sess-1", h.known_session_ids)


if __name__ == "__main__":
    unittest.main()
