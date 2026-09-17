import json
from pathlib import Path

import pytest

import claude_generation
from gen_tool_tests import TestRun as ToolTestRun, fingerprint


@pytest.fixture
def conversation_app(tmp_path, monkeypatch):
    import app
    root = tmp_path / "plugins"
    target = root / "mcp_tools/hello"
    (target / "tests").mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps({"name": "hello", "description": "Say hello", "command": "python3", "base_args": ["hello.py"]}))
    (target / "hello.py").write_text('print("wrong")\n')
    (target / "tests/suite.json").write_text(json.dumps({"version": 1, "template": "python-files", "cases": [
        {"name": "hello", "args": [], "exit_code": 0, "stdout_contains": ["hello"]}]}))
    (target / "PROVENANCE.md").write_text("Original provenance")
    ToolTestRun(root, "hello").finish("failed", cases=[{"name": "hello", "failures": ["Missing hello"]}])
    monkeypatch.setattr(app, "PLUGINS_DIR", str(root))
    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(app, "_plugin_jobs", {})
    monkeypatch.setattr(app, "_plugin_generation_targets", set())
    monkeypatch.setattr(app, "claude_executable", lambda: "claude")
    root_job = {"job_id": "original", "run_id": "run_test", "asset_name": "hello", "safe_name": "hello", "kind": "mcp_tool",
                "status": "success", "start_time": "2026-01-01T00:00:00", "model": "own-model", "base_url": "http://localhost:8080",
                "generation_messages": [{"role": "user", "content": "Make a hello tool"}]}
    app._write_plugin_job_record("run_test", "original", root_job)
    queued = []
    class DeferredThread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args
        def start(self):
            queued.append(lambda: self.target(*self.args))
    monkeypatch.setattr(app.threading, "Thread", DeferredThread)
    prompts = []
    def cli(workspace, prompt, *args, **kwargs):
        assert kwargs["lock_tests"]
        prompts.append(prompt)
        (workspace / "manifest.json").write_text((target / "manifest.json").read_text())
        (workspace / "hello.py").write_text('print("hello")\n')
        return {"response": "Fixed the greeting.", "num_turns": 2}
    monkeypatch.setattr(claude_generation, "run_claude", cli)
    return app, target, queued, prompts


def submit(client, **changes):
    context = client.get("/api/plugins/mcp-tools/hello/conversation").get_json()
    payload = {"prompt": "Print hello instead of wrong", "revision": context["revision"], "artifact_sha256": context["artifact_sha256"], **changes}
    return client.post("/api/plugins/mcp-tools/hello/conversation", json=payload)


def test_continue_then_manual_test_and_persistent_history(conversation_app, monkeypatch):
    app, target, queued, prompts = conversation_app
    client = app.app.test_client()
    url = "/api/plugins/mcp-tools/hello/conversation"
    initial = client.get(url).get_json()
    assert initial["original_messages"][0]["content"] == "Make a hello tool"
    assert not initial["can_test"]
    started = submit(client, api_key="ephemeral-key")
    assert started.status_code == 202
    assert client.get(url).get_json()["busy"]
    assert not client.get(url).get_json()["can_test"]
    assert client.post("/api/plugins/mcp-tools/hello/tests").status_code == 409
    assert submit(client).status_code == 409
    # No container test is launched while processing a user prompt.
    monkeypatch.setattr(claude_generation.TestRun, "execute", lambda *a, **kw: pytest.fail("Unexpected automatic test"))
    queued.pop(0)()
    completed = client.get(url).get_json()
    assert completed["can_test"] and not completed["busy"]
    assert completed["test_report"]["outdated"]
    assert completed["turns"][0]["response"] == "Fixed the greeting."
    assert (target / "hello.py").read_text() == 'print("hello")\n'
    assert (target / "PROVENANCE.md").read_text() == "Original provenance"
    assert "Make a hello tool" in prompts[0] and "Missing hello" in prompts[0]
    assert "Print hello instead of wrong" in prompts[0]
    assert "ephemeral-key" not in json.dumps(completed)
    assert "ephemeral-key" not in "".join(path.read_text() for path in Path(app.RUNS_DIR).rglob("*.json"))
    # The explicit Test button uses the shared test endpoint.
    monkeypatch.setattr(app, "_start_plugin_tests", lambda name, trigger: ToolTestRun(app.PLUGINS_DIR, name, trigger).finish("passed", cases=[]))
    assert client.post("/api/plugins/mcp-tools/hello/tests").status_code == 202
    assert client.get(url).get_json()["test_report"]["status"] == "passed"
    assert not client.get(url).get_json()["test_report"]["outdated"]
    app._plugin_jobs.clear()  # Simulate reloading saved history after app restart.
    assert client.get(url).get_json()["can_test"]
    assert submit(client, prompt="Keep that greeting and improve the implementation").status_code == 202
    queued.pop(0)()
    assert "Fixed the greeting." in prompts[1]
    assert len(client.get(url).get_json()["turns"]) == 2


@pytest.mark.parametrize("failure", ["invalid", "tests_changed", "cancel", "concurrent_edit"])
def test_unsuccessful_prompt_preserves_artifact(conversation_app, monkeypatch, failure):
    app, target, queued, _ = conversation_app
    client = app.app.test_client()
    original_sha = fingerprint(target)
    def cli(workspace, *args, **kwargs):
        (workspace / "manifest.json").write_text((target / "manifest.json").read_text())
        (workspace / "hello.py").write_text('print("hello")\n')
        if failure == "invalid":
            (workspace / "hello.py").write_text("def broken(")
        elif failure == "tests_changed":
            (workspace / "tests/suite.json").write_text("changed")
        elif failure == "cancel":
            client.post(f"/api/plugins/jobs/{job_id}/cancel")
        elif failure == "concurrent_edit":
            (target / "hello.py").write_text("# external edit")
        return {"response": "Done"}
    monkeypatch.setattr(claude_generation, "run_claude", cli)
    started = submit(client)
    job_id = started.get_json()["job_id"]
    queued.pop(0)()
    context = client.get("/api/plugins/mcp-tools/hello/conversation").get_json()
    assert not context["busy"] and not context["can_test"]
    assert context["turns"][-1]["status"] == ("canceled" if failure == "cancel" else "failed")
    if failure == "concurrent_edit":
        assert (target / "hello.py").read_text() == "# external edit"
    else:
        assert fingerprint(target) == original_sha


def test_stale_conversation_and_active_tests_block_edits(conversation_app):
    app, target, queued, _ = conversation_app
    client = app.app.test_client()
    assert submit(client, revision="old-tab").status_code == 409
    assert submit(client, artifact_sha256="old-files").status_code == 409
    test = ToolTestRun(app.PLUGINS_DIR, "hello")
    try:
        assert submit(client).status_code == 409
    finally:
        test.finish("failed")
    assert not queued


def test_interrupted_prompt_can_be_retried(conversation_app):
    app, _, _, _ = conversation_app
    client = app.app.test_client()
    assert submit(client).status_code == 202
    app._plugin_jobs.clear()
    app._plugin_generation_targets.clear()
    context = client.get("/api/plugins/mcp-tools/hello/conversation").get_json()
    assert not context["can_test"]
    assert context["turns"][-1]["status"] == "failed"
    assert submit(client).status_code == 202


@pytest.mark.parametrize("prompt", ["", "   ", 1, "x" * 12001])
def test_invalid_user_prompt_rejected(conversation_app, prompt):
    app, _, queued, _ = conversation_app
    assert submit(app.app.test_client(), prompt=prompt).status_code == 400
    assert not queued


def test_legacy_generation_recovers_scaffold_prompt(conversation_app):
    app, _, _, _ = conversation_app
    path = Path(app.RUNS_DIR) / "run_test/plugin_jobs/original.json"
    record = json.loads(path.read_text())
    del record["generation_messages"]
    path.write_text(json.dumps(record))
    prompt = Path(app.RUNS_DIR) / "run_test/scaffolding/hello/CLAUDE_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Legacy generation instructions")
    context = app.app.test_client().get("/api/plugins/mcp-tools/hello/conversation").get_json()
    assert context["original_messages"][0]["content"] == "Legacy generation instructions"


def test_question_can_complete_without_modifying_files(conversation_app, monkeypatch):
    app, target, queued, _ = conversation_app
    original_sha = fingerprint(target)
    monkeypatch.setattr(claude_generation, "run_claude", lambda *a, **kw: {"response": "The output does not contain hello."})
    client = app.app.test_client()
    assert submit(client, prompt="Why is the test failing?").status_code == 202
    queued.pop(0)()
    context = client.get("/api/plugins/mcp-tools/hello/conversation").get_json()
    assert context["can_test"]
    assert "No files were changed" in context["turns"][-1]["response"]
    assert fingerprint(target) == original_sha


def test_existing_syntax_error_can_be_repaired(conversation_app):
    app, target, queued, _ = conversation_app
    (target / "hello.py").write_text("def broken(")
    client = app.app.test_client()
    assert submit(client, prompt="Fix the syntax error").status_code == 202
    queued.pop(0)()
    assert client.get("/api/plugins/mcp-tools/hello/conversation").get_json()["can_test"]
    assert (target / "hello.py").read_text() == 'print("hello")\n'
