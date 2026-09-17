import json

import pytest

from generated_artifacts import parse_tool_files, publish_artifact


def block(name, content):
    return f"### FILE: {name}\n```\n{content}\n```\n"


def manifest_block(**overrides):
    manifest = dict(name="review", description="Review logs", command="python3", args=["src/review.py"])
    manifest.update(overrides)
    return block("manifest.json", json.dumps(manifest))


def test_preserves_nested_files_and_backticks(tmp_path):
    source = 'print("```embedded```")'
    files = parse_tool_files(manifest_block() + block("src/review.py", source))
    target = tmp_path / "tool"
    publish_artifact(str(target), files)
    assert (target / "src/review.py").read_text().strip() == source
    assert not (target / "review.py").exists()


@pytest.mark.parametrize("name", ["../outside.py", "/tmp/outside.py", "a/../../outside.py", "a\\b.py", "C:/a.py", "./a.py", "a//b.py", "PROVENANCE.md"])
def test_rejects_unsafe_or_reserved_paths(name):
    with pytest.raises(ValueError):
        parse_tool_files(manifest_block() + block(name, "content"))


@pytest.mark.parametrize("response", [
    block("readme.md", "No manifest"),
    block("manifest.json", "invalid JSON"),
    block("manifest.json", "[]"),
    manifest_block(name=""),
    manifest_block(args="not a list"),
    manifest_block(allow_args="yes"),
    manifest_block() + manifest_block(),
    manifest_block() + block("src", "file") + block("src/review.py", "pass"),
    manifest_block() + block("src/review.py", "def broken("),
])
def test_rejects_invalid_tool_output(response):
    with pytest.raises(ValueError):
        parse_tool_files(response)


def test_cancellation_preserves_existing_artifact(tmp_path):
    target = tmp_path / "tool"
    target.mkdir()
    (target / "old.txt").write_text("old")

    def cancelled():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        publish_artifact(str(target), {"new.txt": "new"}, before_publish=cancelled)
    assert (target / "old.txt").read_text() == "old"
    assert not (target / "new.txt").exists()
    assert list(tmp_path.iterdir()) == [target]


def test_publish_failure_restores_previous_artifact(monkeypatch, tmp_path):
    import generated_artifacts

    target = tmp_path / "tool"
    target.mkdir()
    (target / "old.txt").write_text("old")
    replace = generated_artifacts.os.replace

    def failing_replace(src, dst):
        if str(src).endswith("/artifact"):
            raise OSError("disk error")
        return replace(src, dst)

    monkeypatch.setattr(generated_artifacts.os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk error"):
        publish_artifact(str(target), {"new.txt": "new"})
    assert (target / "old.txt").read_text() == "old"


def test_overwrite_removes_obsolete_files(tmp_path):
    target = tmp_path / "tool"
    target.mkdir()
    (target / "obsolete.py").write_text("pass")
    publish_artifact(str(target), {"new.py": "pass"})
    assert [entry.name for entry in target.iterdir()] == ["new.py"]


@pytest.fixture
def generation_app(monkeypatch, tmp_path):
    import app

    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(app, "_plugin_jobs", {})
    monkeypatch.setattr(app, "claude_executable", lambda: "claude")
    monkeypatch.setattr(app, "_plugin_generation_targets", set())
    monkeypatch.setattr(app, "_plugin_target_path", lambda kind, name: str(tmp_path / "plugins" / name))
    for name in ["first", "second"]:
        prompt = tmp_path / "runs/run_test/scaffolding" / name / "CLAUDE_PROMPT.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("**Type**: markdown playbook\nReview local logs.")

    class DeferredThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(app.threading, "Thread", DeferredThread)
    return app


def test_generation_reserves_target_and_uses_unique_jobs(generation_app):
    app = generation_app
    client = app.app.test_client()
    payload = dict(run_id="run_test", asset_name="first", model="test", provider="openai")
    first = client.post("/api/scaffolding/generate", json=payload)
    assert first.status_code == 200
    duplicate = client.post("/api/scaffolding/generate", json=payload)
    assert duplicate.status_code == 409
    job_id = first.get_json()["job_id"]
    assert client.post(f"/api/plugins/jobs/{job_id}/cancel").status_code == 200
    # Soft cancellation must not release the target before the worker exits.
    assert client.post("/api/scaffolding/generate", json=payload).status_code == 409
    payload["asset_name"] = "second"
    second = client.post("/api/scaffolding/generate", json=payload)
    assert second.status_code == 200
    assert second.get_json()["job_id"] != job_id


@pytest.mark.parametrize("field,value", [("run_id", ".."), ("run_id", "."), ("run_id", []), ("asset_name", "../first"), ("asset_name", "/tmp/first"), ("asset_name", 1)])
def test_generation_rejects_invalid_identifiers(generation_app, field, value):
    payload = dict(run_id="run_test", asset_name="first", model="test")
    payload[field] = value
    assert generation_app.app.test_client().post("/api/scaffolding/generate", json=payload).status_code == 400


def test_invalid_output_does_not_modify_existing_plugin(monkeypatch, tmp_path):
    import app

    target = tmp_path / "tool"
    target.mkdir()
    (target / "old.txt").write_text("old")
    import claude_generation
    monkeypatch.setattr(claude_generation, "claude_executable", lambda: "claude")
    def invalid_files(workspace, *args, **kwargs):
        (workspace / "manifest.json").write_text("broken")
        return {}
    monkeypatch.setattr(claude_generation, "run_claude", invalid_files)
    with pytest.raises(ValueError, match="valid JSON"):
        app._perform_plugin_generation("mcp_tool", str(target), [], "openai", "http://test", None, "test", True)
    assert [entry.name for entry in target.iterdir()] == ["old.txt"]


@pytest.mark.parametrize("field", ["args", "base_args"])
def test_loaded_plugin_uses_runtime_schema_and_bundled_paths(monkeypatch, tmp_path, field):
    import app
    import subprocess
    import sys

    tools_dir = tmp_path / "tools"
    plugin = tools_dir / "review"
    (plugin / "src").mkdir(parents=True)
    script = plugin / "src/review.py"
    script.write_text('import sys; print("review:" + sys.argv[1])')
    manifest = dict(name="review", description="Review logs", command=sys.executable)
    manifest[field] = ["src/review.py", "sample"]
    (plugin / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(app, "_plugin_mcp_tools_dir", lambda: str(tools_dir))
    entry, = app._load_plugin_mcp_tools()
    config = entry["manifest"]
    assert "args" not in config
    assert config["base_args"] == [str(script), "sample"]
    result = subprocess.run([config["command"], *config["base_args"]], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "review:sample"


def test_late_analysis_completion_cannot_overwrite_cancellation(monkeypatch, tmp_path):
    import app

    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(app, "_analysis_jobs", {})
    app._update_analysis_job_state("run_test", "job_test", status="running")
    app._mark_analysis_job_cancelled("run_test", "job_test")
    assert not app._update_analysis_job_state("run_test", "job_test", status="success", response="late answer")
    stored = json.loads((tmp_path / "run_test/analysis_jobs/job_test.json").read_text())
    assert stored["status"] == "canceled"
    assert "late answer" not in (tmp_path / "run_test/analysis_jobs/job_test.md").read_text()


def test_live_job_state_takes_precedence_over_disk(generation_app):
    app = generation_app
    record = dict(job_id="job_test", run_id="run_test", status="running")
    app._write_plugin_job_record("run_test", "job_test", record)
    app._plugin_jobs["job_test"] = {**record, "status": "canceled"}
    jobs = app.app.test_client().get("/api/plugins/jobs").get_json()["jobs"]
    assert jobs[0]["status"] == "canceled"


def test_analysis_endpoint_publishes_scaffolds_before_success(monkeypatch, tmp_path):
    import app

    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(app, "_analysis_jobs", {})
    (tmp_path / "run_test").mkdir()
    response = (
        "## Recommended Tooling Assets\n- Type: markdown playbook\n"
        "- Name: review\n- Problem: repeated review\n- Expected Gain: save steps\n"
        "- AI Scaffolding Details: Review local logs."
    )
    monkeypatch.setattr(app, "_perform_llm_analysis", lambda *a, **k: {
        "run_id": "run_test", "response": response, "completion_path": "initial",
    })

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(app.threading, "Thread", ImmediateThread)
    client = app.app.test_client()
    started = client.post("/api/sessions/run_test/analyze", json={})
    assert started.status_code == 200
    job = client.get('/api/analysis/jobs/' + started.get_json()['job_id']).get_json()
    # The detail endpoint returns the job directly.
    assert job["status"] == "success"
    assert (tmp_path / "run_test/scaffolding/review/CLAUDE_PROMPT.md").exists()


def test_generation_worker_start_failure_releases_target(generation_app, monkeypatch):
    app = generation_app

    class FailingThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("no worker")

    monkeypatch.setattr(app.threading, "Thread", FailingThread)
    response = app.app.test_client().post("/api/scaffolding/generate", json={
        "run_id": "run_test", "asset_name": "first", "model": "test",
    })
    assert response.status_code == 500
    assert not app._plugin_generation_targets
    assert all(job["status"] == "failed" for job in app._plugin_jobs.values())


def test_string_false_does_not_authorize_overwrite(generation_app):
    response = generation_app.app.test_client().post("/api/scaffolding/generate", json={
        "run_id": "run_test", "asset_name": "first", "model": "test", "overwrite": "false",
    })
    assert response.status_code == 400


def test_generation_missing_cli_returns_setup_instructions(generation_app, monkeypatch):
    def missing():
        raise ValueError("Claude Code is not installed. Run ./install_claude.sh")
    monkeypatch.setattr(generation_app, "claude_executable", missing)
    response = generation_app.app.test_client().post("/api/scaffolding/generate", json={
        "run_id": "run_test", "asset_name": "first", "model": "own-model",
    })
    assert response.status_code == 400
    assert "install_claude.sh" in response.get_json()["error"]
    assert not generation_app._plugin_jobs


def test_generation_routes_selected_endpoint_and_model(generation_app, monkeypatch):
    calls = []
    class CaptureThread:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def start(self):
            pass
    monkeypatch.setattr(generation_app.threading, "Thread", CaptureThread)
    response = generation_app.app.test_client().post("/api/scaffolding/generate", json={
        "run_id": "run_test", "asset_name": "first", "model": "own-model",
        "base_url": "http://inference.local:8080/v1", "api_key": "test-key",
    })
    assert response.status_code == 200
    assert calls[0]["args"][-4:] == ("http://inference.local:8080", "test-key", "own-model", True)
    job = generation_app._plugin_jobs[response.get_json()["job_id"]]
    assert job["generation_backend"] == "claude_cli"
    assert "test-key" not in json.dumps(job)


def test_generation_worker_persists_attempt_reports(generation_app, monkeypatch, tmp_path):
    app = generation_app
    monkeypatch.setattr(app, "PLUGINS_DIR", str(tmp_path / "plugins"))
    monkeypatch.setattr(app, "_write_plugin_provenance", lambda *a: None)
    monkeypatch.setattr(app, "_perform_plugin_generation", lambda *a, **kw: {
        "backend": "claude_cli", "attempts": [{"attempt": 1, "test_status": "passed"}],
        "test_reports": [{"test_id": "test_local", "status": "passed", "tool": "artifact"}],
    })
    app._plugin_jobs["job_local"] = {"status": "running"}
    app._plugin_job_wrapper("job_local", "run_test", "mcp_tool", "hello", str(tmp_path / "hello"),
                            "hello", [{"content": "Build hello"}], "openai", "http://localhost:8080", None, "own-model", True)
    job = app._plugin_jobs["job_local"]
    assert job["status"] == "success"
    assert job["test_id"] == "test_local"
    assert job["generation"]["backend"] == "claude_cli"
    report = json.loads((tmp_path / "plugins/test_results/hello/test_local.json").read_text())
    assert report["tool"] == "hello"
    assert report["generation_job_id"] == "job_local"


def test_atomic_job_write_preserves_previous_record_on_failure(monkeypatch, tmp_path):
    import app

    path = tmp_path / "job.json"
    path.write_text('{"status":"running"}')

    def fail_replace(*args):
        raise OSError("write failed")

    monkeypatch.setattr(app.os, "replace", fail_replace)
    with pytest.raises(OSError):
        app._atomic_write_text(str(path), '{"status":"success"}')
    assert json.loads(path.read_text()) == {"status": "running"}
    assert list(tmp_path.iterdir()) == [path]
