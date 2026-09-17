import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import claude_generation as generation


@pytest.fixture
def files():
    return {
        "manifest.json": json.dumps({"name": "hello", "description": "Say hello", "command": "python3", "base_args": ["hello.py"]}),
        "hello.py": 'print("hello")\n',
        "tests/suite.json": json.dumps({"version": 1, "template": "python-files", "cases": [{"name": "hello", "args": [], "exit_code": 0, "stdout_contains": ["hello"]}]}),
    }


def write_files(workspace, files):
    for name, content in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_generation_repairs_code_and_preserves_test_contract(monkeypatch, tmp_path, files):
    monkeypatch.setattr(generation, "claude_executable", lambda: "claude")
    calls = []
    def cli(workspace, prompt, *args, **kwargs):
        calls.append((prompt, kwargs))
        write_files(workspace, files)
        if len(calls) == 1:
            (workspace / "hello.py").write_text('print("wrong")')
        return {"num_turns": 2}
    monkeypatch.setattr(generation, "run_claude", cli)
    def tests(self, **kwargs):
        code = (self.artifact / "hello.py").read_text()
        return self.finish("failed" if "wrong" in code else "passed", cases=[{"name": "hello", "failures": ["missing hello"] if "wrong" in code else []}])
    monkeypatch.setattr(generation.TestRun, "execute", tests)
    target = tmp_path / "output"
    result = generation.generate_artifact("mcp_tool", str(target), [{"content": "Say hello"}], "http://localhost:8080/v1", None, "own-model")
    assert len(calls) == 2
    assert calls[1][1]["lock_tests"] is True
    assert "missing hello" in calls[1][0]
    assert [report["status"] for report in result["test_reports"]] == ["failed", "passed"]
    assert (target / "hello.py").read_text() == files["hello.py"]


def test_repair_cannot_change_tests(monkeypatch, tmp_path, files):
    monkeypatch.setattr(generation, "claude_executable", lambda: "claude")
    count = 0
    def cli(workspace, *args, **kwargs):
        nonlocal count
        count += 1
        write_files(workspace, files)
        if count == 2:
            (workspace / "tests/suite.json").write_text("changed")
        return {}
    monkeypatch.setattr(generation, "run_claude", cli)
    monkeypatch.setattr(generation.TestRun, "execute", lambda self, **kw: self.finish("failed", cases=[]))
    target = tmp_path / "output"
    with pytest.raises(ValueError, match="frozen test"):
        generation.generate_artifact("mcp_tool", str(target), [], "http://localhost:8080", None, "own-model")
    assert not target.exists()


def test_missing_test_runtime_does_not_trigger_repairs(monkeypatch, tmp_path, files):
    monkeypatch.setattr(generation, "claude_executable", lambda: "claude")
    calls = []
    def cli(workspace, *args, **kwargs):
        calls.append(1)
        write_files(workspace, files)
        return {}
    monkeypatch.setattr(generation, "run_claude", cli)
    monkeypatch.setattr(generation.TestRun, "execute", lambda self, **kw: self.finish("blocked"))
    result = generation.generate_artifact("mcp_tool", str(tmp_path / "output"), [], "http://localhost:8080", None, "own-model")
    assert len(calls) == 1
    assert result["test_reports"][0]["status"] == "blocked"


def test_cancel_keeps_existing_artifact(monkeypatch, tmp_path, files):
    monkeypatch.setattr(generation, "claude_executable", lambda: "claude")
    canceled = False
    def cli(workspace, *args, **kwargs):
        nonlocal canceled
        write_files(workspace, files)
        canceled = True
        return {}
    monkeypatch.setattr(generation, "run_claude", cli)
    target = tmp_path / "output"
    target.mkdir()
    (target / "old.txt").write_text("old")
    with pytest.raises(generation.GenerationCancelled):
        generation.generate_artifact("mcp_tool", str(target), [], "http://localhost:8080", None, "own-model", cancel_check=lambda: canceled)
    assert [p.name for p in target.iterdir()] == ["old.txt"]


@pytest.mark.parametrize("endpoint", ["", "file:///tmp/server", "http://user:secret@server", "http://server?token=secret"])
def test_invalid_endpoints_are_rejected(endpoint):
    with pytest.raises(ValueError):
        generation.normalize_endpoint(endpoint)


def test_native_process_credentials_and_cancellation(monkeypatch, tmp_path):
    executable = tmp_path / "fake-claude"
    executable.write_text(f'''#!{sys.executable}
import json, os, sys, time
from pathlib import Path
Path("captured.json").write_text(json.dumps({{"args":sys.argv[1:],"env":dict(os.environ),"prompt":sys.stdin.read()}}))
time.sleep(60)
''')
    executable.chmod(0o755)
    monkeypatch.setenv("CYBER_AGENT_FLOW_CLAUDE_BIN", str(executable))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://wrong-server.test")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-secret")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(generation.GenerationCancelled):
        generation.run_claude(workspace, "Build a tool", "http://localhost:8080/v1", "test-secret", "own-model", cancel_check=lambda: (workspace / "captured.json").exists())
    captured = json.loads((workspace / "captured.json").read_text())
    assert captured["env"]["ANTHROPIC_BASE_URL"] == "http://localhost:8080"
    assert captured["env"]["ANTHROPIC_API_KEY"] == "test-secret"
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "test-secret" not in " ".join(captured["args"])
    assert captured["args"][captured["args"].index("--tools") + 1] == "Edit"
    assert captured["prompt"] == "Build a tool"


def test_installer_check_mode_is_repeatable(tmp_path):
    executable = tmp_path / "fake-claude"
    executable.write_text('#!/bin/sh\nif [ "$1" = "--help" ]; then echo "--bare --tools --settings --setting-sources --permission-mode --no-session-persistence"; else echo "test version"; fi\n')
    executable.chmod(0o755)
    env = {**os.environ, "CYBER_AGENT_FLOW_CLAUDE_BIN": str(executable)}
    script = str(Path(__file__).parents[1] / "install_claude.sh")
    for _ in range(2):
        result = subprocess.run(["bash", script, "--check"], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    env["CYBER_AGENT_FLOW_CLAUDE_BIN"] = str(tmp_path / "missing")
    assert subprocess.run(["bash", script, "--check"], env=env, capture_output=True).returncode == 1


@pytest.mark.parametrize("output", ['not json: test-secret', '{"is_error":true,"result":"test-secret"}', '[]'])
def test_cli_invalid_or_error_result_fails_without_exposing_key(tmp_path, monkeypatch, output):
    executable = tmp_path / "fake-claude"
    executable.write_text(f'#!{sys.executable}\nprint({output!r})\n')
    executable.chmod(0o755)
    monkeypatch.setenv("CYBER_AGENT_FLOW_CLAUDE_BIN", str(executable))
    with pytest.raises(ValueError) as error:
        generation.run_claude(tmp_path, "Generate", "http://localhost:8080", "test-secret", "own-model")
    assert "test-secret" not in str(error.value)


@pytest.fixture
def local_messages_server():
    requests = []
    state = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            if self.path.startswith("/v1/messages/count_tokens"):
                body = json.dumps({"input_tokens": 100}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            has_results = any(isinstance(message.get("content"), list) and any(part.get("type") == "tool_result" for part in message["content"]) for message in payload.get("messages", []))
            content = ([{"type": "text", "text": "Files created."}] if has_results else state["calls"]())
            stop = "end_turn" if has_results else "tool_use"
            message = {"id": "msg_test", "type": "message", "role": "assistant", "model": payload.get("model"), "content": content, "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 100, "output_tokens": 100}}
            self.send_response(200)
            if not payload.get("stream"):
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(message).encode())
                return
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            def event(name, data):
                self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
            event("message_start", {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}})
            for index, part in enumerate(content):
                event("content_block_start", {"type": "content_block_start", "index": index, "content_block": {**part, **({"input": {}} if part["type"] == "tool_use" else {"text": ""})}})
                delta = {"type": "input_json_delta", "partial_json": json.dumps(part["input"])} if part["type"] == "tool_use" else {"type": "text_delta", "text": part["text"]}
                event("content_block_delta", {"type": "content_block_delta", "index": index, "delta": delta})
                event("content_block_stop", {"type": "content_block_stop", "index": index})
            event("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 100}})
            event("message_stop", {"type": "message_stop"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def edit_calls(workspace, files):
    return [{"type": "tool_use", "id": f"tool_{index}", "name": "Edit",
             "input": {"file_path": str(workspace / name), "old_string": "", "new_string": text}}
            for index, (name, text) in enumerate(files.items())]


@pytest.mark.skipif(os.environ.get("CAF_TEST_CLAUDE") != "1", reason="Set CAF_TEST_CLAUDE=1 to exercise the installed native CLI")
def test_real_cli_file_permissions(tmp_path, monkeypatch, files, local_messages_server):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tests").mkdir()
    frozen = workspace / "tests/suite.json"
    frozen.write_text(files["tests/suite.json"])
    endpoint, requests, state = local_messages_server
    state["calls"] = lambda: edit_calls(workspace, {**files, "../escape.txt": "must not be written"})
    monkeypatch.setattr(generation, "CLI_TIMEOUT_SECONDS", 30)
    result = generation.run_claude(workspace, "Create the hello tool files using Edit.", endpoint, None, "local-test-model", lock_tests=True)
    assert result["num_turns"] >= 1
    results = [part for request in requests for message in request.get("messages", []) if isinstance(message.get("content"), list) for part in message["content"] if part.get("type") == "tool_result"]
    assert (workspace / "hello.py").read_text() == files["hello.py"], results
    assert frozen.read_text() == files["tests/suite.json"]
    assert not (tmp_path / "escape.txt").exists()
    assert sum(bool(part.get("is_error")) for part in results) >= 2
    assert all(request["model"] == "local-test-model" for request in requests)
    assert {tool["name"] for request in requests for tool in request.get("tools", [])} == {"Edit"}


@pytest.mark.skipif(os.environ.get("CAF_TEST_CLAUDE") != "1" or os.environ.get("CAF_TEST_DOCKER") != "1", reason="Set CAF_TEST_CLAUDE=1 CAF_TEST_DOCKER=1 for native generation and container repair")
def test_real_cli_and_docker_repair_then_publish(tmp_path, monkeypatch, files, local_messages_server):
    endpoint, requests, state = local_messages_server
    native_run = generation.run_claude
    attempts = []
    def run(workspace, *args, **kwargs):
        attempts.append(1)
        output = dict(files)
        if len(attempts) == 1:
            output["hello.py"] = 'print("wrong")\n'
        else:
            assert not (workspace / "hello.py").exists()
            del output["tests/suite.json"]
        state["calls"] = lambda: edit_calls(workspace, output)
        return native_run(workspace, *args, **kwargs)
    monkeypatch.setattr(generation, "run_claude", run)
    monkeypatch.setattr(generation, "CLI_TIMEOUT_SECONDS", 30)
    target = tmp_path / "output"
    result = generation.generate_artifact("mcp_tool", str(target), [{"content": "Build a hello tool"}], endpoint, None, "local-test-model")
    assert len(attempts) == 2
    assert [report["status"] for report in result["test_reports"]] == ["failed", "passed"]
    assert (target / "hello.py").read_text() == files["hello.py"]
    assert (target / "tests/suite.json").read_text() == files["tests/suite.json"]


@pytest.mark.skipif(os.environ.get("CAF_TEST_CLAUDE") != "1", reason="Set CAF_TEST_CLAUDE=1 for native interactive refinement")
def test_real_cli_interactive_refinement_does_not_run_tests(tmp_path, monkeypatch, files, local_messages_server):
    endpoint, requests, state = local_messages_server
    target = tmp_path / "hello"
    write_files(target, {**files, "hello.py": 'print("wrong")\n'})
    native_run = generation.run_claude
    def run(workspace, *args, **kwargs):
        state["calls"] = lambda: edit_calls(workspace, {name: content for name, content in files.items() if not name.startswith("tests/")})
        return native_run(workspace, *args, **kwargs)
    monkeypatch.setattr(generation, "run_claude", run)
    monkeypatch.setattr(generation.TestRun, "execute", lambda *a, **kw: pytest.fail("User must choose Test"))
    monkeypatch.setattr(generation, "CLI_TIMEOUT_SECONDS", 30)
    result = generation.refine_artifact(target, [{"role": "user", "content": "Print hello"}], {"status": "failed"},
                                        generation.fingerprint(target), endpoint, None, "own-model")
    assert result["response"] == "Files created."
    assert (target / "hello.py").read_text() == files["hello.py"]
    assert (target / "tests/suite.json").read_text() == files["tests/suite.json"]


@pytest.mark.skipif(os.environ.get("CAF_TEST_CLAUDE") != "1", reason="Set CAF_TEST_CLAUDE=1 for native document generation")
@pytest.mark.parametrize("kind", ["markdown", "skill", "rag_document", "template", "structured_data", "playbook"])
def test_real_cli_generates_document_artifacts(tmp_path, monkeypatch, local_messages_server, kind):
    from test_document_artifacts import sample_files
    from artifact_store import document_path, validate_document
    endpoint, _, state = local_messages_server
    native_run = generation.run_claude
    def run(workspace, *args, **kwargs):
        state["calls"] = lambda: edit_calls(workspace, sample_files(kind))
        return native_run(workspace, *args, **kwargs)
    monkeypatch.setattr(generation, "run_claude", run)
    monkeypatch.setattr(generation, "CLI_TIMEOUT_SECONDS", 30)
    target = document_path(tmp_path, kind, "security-review", must_exist=False)
    result = generation.generate_artifact(kind, target, [{"content": "Create a reusable artifact"}], endpoint, None, "own-model")
    assert not result["test_reports"]
    assert validate_document(tmp_path, kind, "security-review")["status"] == "passed"
