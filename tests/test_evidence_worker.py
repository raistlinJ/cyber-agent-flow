"""Exercise CAF's native agent with a scripted client and a real stdio MCP reader."""
import asyncio
import io
import json
import os
from pathlib import Path
import re
import zipfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import pytest

from evidence_artifacts import validate_candidate
from evidence_server import MAGIC, MEMBERS, create_server, open_notes, tool_name
import evidence_worker

FIRST = "FLAG{test_first}"
SECOND = "FLAG{test_second}"
MODEL = {"provider": "openai", "url": "http://unused.invalid", "name": "scripted", "ssl_verify": True, "api_key_env": ""}
LIMITS = {"wall_seconds": 40, "context_window": 8192, "max_turns": 6, "tool_timeout": 15}
TOOL = {"name": "extract-flags", "description": "Extract distinct flags from observed text.", "operation": "unique_flags"}


@pytest.fixture
def kit(tmp_path):
    folder = tmp_path / "public kit"
    folder.mkdir()
    ticket = f"handoff {FIRST}\nsynthetic case password: example-secret\nAuthorization: Bearer header-secret"
    (folder / "tasks.json").write_text(json.dumps([{"id": "alderbank-case-file-handoff", "family": "case-file-handoff",
                                                   "prompt": "Recover the flags from the ticket and case notes."}]))
    (folder / "handoff-ticket.txt").write_text(ticket)
    # The reader shipped by an instance is participant convenience material, never executable input.
    (folder / "case_files.py").write_text("raise AssertionError('untrusted module was imported')")
    notes = io.BytesIO()
    with zipfile.ZipFile(notes, "w") as archive:
        for name in MEMBERS:
            archive.writestr(name, SECOND if name == MEMBERS[-1] else "handoff")
    salt, nonce = os.urandom(16), os.urandom(12)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=MAGIC).derive(FIRST.encode())
    header = MAGIC + salt + nonce
    (folder / "case-notes.sealed").write_bytes(header + AESGCM(key).encrypt(nonce, notes.getvalue(), header))
    return folder


def test_gate_and_scoped_tool(kit):
    sealed = (kit / "case-notes.sealed").read_bytes()
    assert SECOND in open_notes(sealed, FIRST)
    with pytest.raises(ValueError, match="authentication"):
        open_notes(sealed, SECOND)
    with pytest.raises(ValueError, match="authentication"):
        open_notes(sealed[:-1] + bytes([sealed[-1] ^ 1]), FIRST)

    server = create_server(kit, [TOOL])
    name = tool_name(validate_candidate("tool", TOOL))

    async def check():
        assert {t.name for t in await server.list_tools()} == {name, "read_ticket", "open_case_notes"}
        with pytest.raises(Exception, match="previously read"):
            await server.call_tool(name, {"text": FIRST})
        await server.call_tool("read_ticket", {})
        result = await server.call_tool(name, {"text": FIRST})
        assert FIRST in str(result)
        with pytest.raises(Exception, match="previously read"):
            await server.call_tool(name, {"text": SECOND})
    asyncio.run(check())


def test_native_trial_and_blinded_analysis(tmp_path, kit, monkeypatch):
    import mcp_client

    trial = tmp_path / "trial"
    trial.mkdir()
    monkeypatch.setenv("CAF_RUN_BASE_DIR", str(trial))
    name = tool_name(validate_candidate("tool", TOOL))
    expected = json.dumps({"flags": [FIRST, SECOND]})

    class Scripted:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def show(self, model):
            return {}

        def chat(self, *, messages, tools, **kwargs):
            assert {t["function"]["name"] for t in tools} == {"read_ticket", "open_case_notes", name}
            assert "guidance sentinel" in messages[0]["content"]
            assert '"flags" array' in messages[1]["content"]
            steps = [("read_ticket", {}), (name, {"text": FIRST}), ("open_case_notes", {"first_flag": FIRST})]
            if self.calls == len(steps):
                assert SECOND in messages[-1]["content"]
                return {"message": {"role": "assistant", "content": expected}}
            tool, kwargs = steps[self.calls]
            if self.calls:
                assert FIRST in messages[-1]["content"]
            self.calls += 1
            call = {"id": f"call-{self.calls}", "function": {"name": tool, "arguments": kwargs}}
            return {"message": {"role": "assistant", "content": "", "tool_calls": [call]}}

    monkeypatch.setattr(mcp_client, "_LiteLLMClient", Scripted)
    result = asyncio.run(evidence_worker._trial(
        {"kit": str(kit), "model": MODEL, "tools": [TOOL], "guidance": "guidance sentinel", "limits": LIMITS}, trial))
    assert result == {"status": "completed", "final_answer": expected, "model_calls": 4, "tool_calls": 3,
                      "tool_calls_by_name": {"read_ticket": 1, "open_case_notes": 1, name: 1}, "errors": []}
    assert len(list((trial / "runs/participant/tool_calls").glob("*.json"))) == 3
    (trial / "result.json").write_text(json.dumps(result))
    (trial / "evaluator-key.txt").write_text("private-oracle-sentinel")
    analysis_dir = tmp_path / "analyst"
    analysis_dir.mkdir()

    def chat(messages, model, limits):
        prompt = json.dumps(messages)
        for secret in [FIRST, SECOND, "test_first", "test_second", "header-secret", "example-secret", "private-oracle-sentinel"]:
            assert secret not in prompt
        assert "open_case_notes" in prompt and "Distinct flag-like values in final answer: 2" in prompt
        return "Record distinct values before submitting."

    monkeypatch.setattr(evidence_worker, "_chat", chat)
    response = evidence_worker._analysis({"trial": str(trial), "model": MODEL, "limits": LIMITS}, analysis_dir)
    assert response["analysis"] in (analysis_dir / "analysis.md").read_text()
    clean = (analysis_dir / "analyst-input.json").read_text()
    assert not re.search(r"example-secret|header-secret|test_first|test_second", clean)


@pytest.mark.parametrize("backend_status,exception", [("timeout", TimeoutError), ("invalid_candidate", ValueError),
                                                       ("error", RuntimeError)])
def test_model_author_failure_classification(monkeypatch, tmp_path, backend_status, exception):
    monkeypatch.setattr(evidence_worker, "_launch", lambda *args: {"status": backend_status, "error": "safe reason"})
    with pytest.raises(exception):
        evidence_worker.propose_candidate("tool", "Review completed", tmp_path, MODEL, LIMITS)


def test_claude_author_accepts_one_checked_file(tmp_path, monkeypatch):
    import claude_generation

    def author(path, prompt, host, key, model, ssl_verify, cancel_check):
        assert "candidate.json" in prompt and cancel_check() is False
        assert key == "model-secret"
        assert "model-secret" not in prompt
        (Path(path) / "candidate.json").write_text(json.dumps(TOOL))
        return {"num_turns": 3, "result": "private-cli-output"}

    monkeypatch.setenv("TEST_CAF_MODEL_KEY", "model-secret")
    model = dict(MODEL, api_key_env="TEST_CAF_MODEL_KEY")
    monkeypatch.setattr(claude_generation, "run_claude", author)
    out = tmp_path / "author"
    candidate = evidence_worker.propose_candidate("tool", "Review progress", out, model, LIMITS, backend="claude_cli")
    assert candidate == validate_candidate("tool", TOOL)
    record = "".join(f.read_text() for f in out.iterdir())
    assert "private-cli-output" not in record and "model-secret" not in record

    def failing_author(*args, **kwargs):
        raise ValueError("secret provider response")

    monkeypatch.setattr(claude_generation, "run_claude", failing_author)
    with pytest.raises(RuntimeError, match=r"Claude CLI author failed \(ValueError\)") as exc:
        evidence_worker.propose_candidate("tool", "Review progress", tmp_path / "failure", model, LIMITS, backend="claude_cli")
    assert "secret provider response" not in str(exc.value)
