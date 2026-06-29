"""
Tests for the prompt_toolkit integration:
  - SlashCompleter produces correct completions from _completion_candidates
  - SlashCompleter works with prompt_toolkit Document objects
  - SlashCompleter handles edge cases (empty input, cursor mid-line)
  - PromptSession creation in _chat loop attaches to event_handler
  - CyberAgentFlowSSHSession (cli-server.py) can be instantiated
  - _install_slash_completion is a safe no-op
"""
import asyncio
import io
import sys
import argparse
import unittest
from unittest.mock import MagicMock, patch

import cli
from cli import SlashCompleter, _completion_candidates, _install_slash_completion

from prompt_toolkit.document import Document


# ===========================================================================
# SlashCompleter unit tests
# ===========================================================================

class TestSlashCompleterBasic(unittest.TestCase):
    """Test SlashCompleter produces the right completions."""

    def _get_completions(self, text, get_session_ids=None):
        """Helper: create a Document and collect completions."""
        getter = get_session_ids or (lambda: [])
        completer = SlashCompleter(getter)
        doc = Document(text, cursor_position=len(text))
        # complete_event is not used by our completer, pass a mock
        return list(completer.get_completions(doc, MagicMock()))

    def test_empty_input_returns_all_commands(self):
        completions = self._get_completions("/")
        texts = [c.text for c in completions]
        # Should include common slash commands
        self.assertIn("/help", texts)
        self.assertIn("/exit", texts)
        self.assertIn("/set", texts)

    def test_partial_slash_command(self):
        completions = self._get_completions("/he")
        texts = [c.text for c in completions]
        self.assertIn("/help", texts)
        # Should NOT include unrelated commands
        self.assertNotIn("/exit", texts)

    def test_set_key_completions(self):
        completions = self._get_completions("/set ")
        texts = [c.text for c in completions]
        # Should include settable config keys
        self.assertIn("scope", texts)
        self.assertIn("urgency", texts)
        self.assertIn("verbose", texts)

    def test_set_scope_value_completions(self):
        completions = self._get_completions("/set scope ")
        texts = [c.text for c in completions]
        self.assertIn("broad", texts)
        self.assertIn("narrow", texts)
        self.assertIn("off", texts)

    def test_set_urgency_value_completions(self):
        completions = self._get_completions("/set urgency ")
        texts = [c.text for c in completions]
        self.assertIn("stealthy", texts)
        self.assertIn("speed", texts)
        self.assertIn("off", texts)

    def test_set_verbose_value_completions(self):
        completions = self._get_completions("/set verbose ")
        texts = [c.text for c in completions]
        self.assertIn("true", texts)
        self.assertIn("false", texts)

    def test_set_provider_value_completions(self):
        completions = self._get_completions("/set provider ")
        texts = [c.text for c in completions]
        self.assertIn("ollama", texts)
        self.assertIn("openai", texts)

    def test_no_completions_for_plain_text(self):
        completions = self._get_completions("hello world")
        self.assertEqual(completions, [])

    def test_session_ids_for_enter_command(self):
        completions = self._get_completions(
            "/enter ",
            get_session_ids=lambda: ["sess-abc", "sess-def"],
        )
        texts = [c.text for c in completions]
        self.assertIn("sess-abc", texts)
        self.assertIn("sess-def", texts)

    def test_session_ids_filtered_by_prefix(self):
        completions = self._get_completions(
            "/enter sess-a",
            get_session_ids=lambda: ["sess-abc", "sess-def"],
        )
        texts = [c.text for c in completions]
        self.assertIn("sess-abc", texts)
        self.assertNotIn("sess-def", texts)


# ===========================================================================
# SlashCompleter Document / cursor edge cases
# ===========================================================================

class TestSlashCompleterEdgeCases(unittest.TestCase):

    def _get_completions_at(self, text, cursor_position, get_session_ids=None):
        """Get completions with cursor at a specific position."""
        getter = get_session_ids or (lambda: [])
        completer = SlashCompleter(getter)
        doc = Document(text, cursor_position=cursor_position)
        return list(completer.get_completions(doc, MagicMock()))

    def test_cursor_at_beginning(self):
        completions = self._get_completions_at("/set scope broad", 0)
        # Cursor at position 0, text before cursor is empty — _completion_candidates
        # sees no tokens_before and returns all commands matching empty prefix
        texts = [c.text for c in completions]
        self.assertIn("/help", texts)

    def test_cursor_mid_first_token(self):
        completions = self._get_completions_at("/se", 3)
        texts = [c.text for c in completions]
        self.assertIn("/set", texts)

    def test_start_position_negative_offset(self):
        """Completion start_position should be negative len of partial text."""
        getter = lambda: []
        completer = SlashCompleter(getter)
        doc = Document("/he", cursor_position=3)
        completions = list(completer.get_completions(doc, MagicMock()))
        for c in completions:
            self.assertEqual(c.start_position, -3)

    def test_start_position_for_value_completion(self):
        getter = lambda: []
        completer = SlashCompleter(getter)
        doc = Document("/set scope br", cursor_position=13)
        completions = list(completer.get_completions(doc, MagicMock()))
        for c in completions:
            # "br" is 2 chars
            self.assertEqual(c.start_position, -2)


# ===========================================================================
# _install_slash_completion is a safe no-op
# ===========================================================================

class TestInstallSlashCompletionNoop(unittest.TestCase):

    def test_install_slash_completion_does_nothing(self):
        """Calling _install_slash_completion should not raise."""
        _install_slash_completion()
        _install_slash_completion(get_session_ids=lambda: ["a", "b"])


# ===========================================================================
# PromptSession attachment to TerminalEventHandler
# ===========================================================================

class TestPromptSessionCreation(unittest.TestCase):

    def test_event_handler_can_have_prompt_session_attached(self):
        """Verify the pattern used in _chat: attaching prompt_session to handler."""
        from prompt_toolkit import PromptSession
        h = cli.TerminalEventHandler(stream_out=io.StringIO(), stream_in=io.StringIO())
        self.assertFalse(hasattr(h, "prompt_session"))

        # Simulate what _chat does
        h.prompt_session = PromptSession(
            completer=SlashCompleter(lambda: []),
        )
        self.assertTrue(hasattr(h, "prompt_session"))
        self.assertIsInstance(h.prompt_session, PromptSession)

    def test_slash_completer_attached_to_prompt_session(self):
        """Verify the PromptSession has a SlashCompleter."""
        from prompt_toolkit import PromptSession
        getter = lambda: ["sess-1"]
        ps = PromptSession(completer=SlashCompleter(getter))
        self.assertIsInstance(ps.completer, SlashCompleter)
        self.assertIs(ps.completer.get_session_ids, getter)


# ===========================================================================
# CyberAgentFlowSSHSession instantiation
# ===========================================================================

class TestCyberAgentFlowSSHSession(unittest.TestCase):
    """Test that cli-server.py's SSH session class can be instantiated."""

    def _make_base_args(self):
        return argparse.Namespace(
            model="test_model",
            verbose=False,
            tool_output_chars=6000,
            command=None,
            provider="ollama_direct",
            url="http://localhost:11434",
            api_key=None,
            context_window=8192,
            max_turns=20,
            tool_timeout=120,
            scope="broad",
            no_scope=False,
            urgency="balanced",
            no_urgency=False,
            prompt=[],
            ssl_verify=True,
            server_command="python mcp_kali.py",
            tools_config=None,
            continue_run=None,
            dangerous_no_prompt=False,
            network_policy=None,
        )

    def test_session_can_be_instantiated(self):
        """CyberAgentFlowSSHSession should instantiate without errors."""
        # We need to import the module dynamically since it has a hyphen in the name
        import importlib.util, os
        spec = importlib.util.spec_from_file_location(
            "cli_server",
            os.path.join(os.path.dirname(__file__), "..", "cli-server.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # Temporarily prevent __main__ block from executing
        mod.__name__ = "cli_server"
        spec.loader.exec_module(mod)

        base_args = self._make_base_args()
        session = mod.CyberAgentFlowSSHSession(base_args)
        self.assertIs(session.base_args, base_args)
        self.assertIsNone(session.client_cmd)

    def test_exec_requested_stores_command(self):
        import importlib.util, os
        spec = importlib.util.spec_from_file_location(
            "cli_server",
            os.path.join(os.path.dirname(__file__), "..", "cli-server.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        mod.__name__ = "cli_server"
        spec.loader.exec_module(mod)

        base_args = self._make_base_args()
        session = mod.CyberAgentFlowSSHSession(base_args)
        result = session.exec_requested("chat --model gpt-4")
        self.assertTrue(result)
        self.assertEqual(session.client_cmd, "chat --model gpt-4")


# ===========================================================================
# _completion_candidates still works correctly (regression)
# ===========================================================================

class TestCompletionCandidatesRegression(unittest.TestCase):
    """Ensure the underlying _completion_candidates function behaves correctly."""

    def test_slash_command_completion(self):
        result = _completion_candidates(
            buffer="/",
            text="/",
            start_idx=0,
            get_session_ids=lambda: [],
        )
        self.assertIn("/help", result)
        self.assertIn("/exit", result)
        self.assertIn("/set", result)

    def test_set_key_completion(self):
        result = _completion_candidates(
            buffer="/set ",
            text="",
            start_idx=5,
            get_session_ids=lambda: [],
        )
        self.assertIn("scope", result)
        self.assertIn("urgency", result)

    def test_set_scope_value_completion(self):
        result = _completion_candidates(
            buffer="/set scope ",
            text="",
            start_idx=11,
            get_session_ids=lambda: [],
        )
        self.assertIn("broad", result)
        self.assertIn("off", result)

    def test_scope_command_completion(self):
        result = _completion_candidates(
            buffer="/scope ",
            text="",
            start_idx=7,
            get_session_ids=lambda: [],
        )
        self.assertIn("broad", result)
        self.assertIn("narrow", result)

    def test_enter_session_id_completion(self):
        result = _completion_candidates(
            buffer="/enter ",
            text="",
            start_idx=7,
            get_session_ids=lambda: ["sess-1", "sess-2"],
        )
        self.assertIn("sess-1", result)
        self.assertIn("sess-2", result)

    def test_no_completion_for_unknown_command(self):
        result = _completion_candidates(
            buffer="/nonexistent ",
            text="",
            start_idx=13,
            get_session_ids=lambda: [],
        )
        self.assertEqual(result, [])

    def test_partial_prefix_filters_results(self):
        result = _completion_candidates(
            buffer="/set scope br",
            text="br",
            start_idx=11,
            get_session_ids=lambda: [],
        )
        self.assertIn("broad", result)
        self.assertNotIn("narrow", result)


if __name__ == "__main__":
    unittest.main()
