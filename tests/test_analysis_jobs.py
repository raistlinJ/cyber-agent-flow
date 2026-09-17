import json
import sys
import types

import pytest


def test_analysis_markdown_bundle_is_local_and_loaded_before_consumers():
    from html.parser import HTMLParser
    from urllib.parse import urlsplit
    import app

    scripts = []

    class Scripts(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "script" and dict(attrs).get("src"):
                scripts.append(dict(attrs)["src"])

    client = app.app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    Scripts().feed(page.get_data(as_text=True))
    paths = [urlsplit(src).path for src in scripts]
    dependencies = ["/static/vendor/marked/marked.umd.js", "/static/js/analysis-markdown.js",
                    "/static/js/main.js", "/static/js/recommendations.js"]
    positions = [paths.index(path) for path in dependencies]
    assert positions == sorted(positions)
    assert not any(urlsplit(src).netloc for src in scripts if "marked" in src)
    for position in positions:
        assert "v=" in scripts[position]
        assert client.get(scripts[position]).status_code == 200


@pytest.mark.parametrize("span", ["Entire Session", "Last 10 Minutes"])
@pytest.mark.parametrize("prefix", ["", "# ", "## ", "###### "])
def test_analysis_accepts_required_markdown_headings(span, prefix):
    import app

    response = "\n\n".join(
        prefix + section + "\n- Evidence-backed finding."
        for section in app._analysis_required_sections(span, ["tooling_assets"])
    )
    assert app._analysis_response_is_valid(response, span, ["tooling_assets"])


@pytest.mark.parametrize("invalid_passes", [0, 1, 2, 3])
def test_analysis_retry_validation(monkeypatch, tmp_path, invalid_passes):
    import app

    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path))
    run_dir = tmp_path / "run_review"
    run_dir.mkdir()
    (run_dir / "transcript.md").write_text("Operator requested a review of collected logs.")
    valid = "\n\n".join(
        "## " + section + "\n- Review finding."
        for section in app._analysis_required_sections("Entire Session")
    )
    responses = iter(["Off-format response"] * invalid_passes + [valid])
    calls = []

    def fake_chat(*args, **kwargs):
        calls.append(args)
        return {"choices": [{"message": {"content": next(responses)}}]}

    monkeypatch.setattr(app, "_analysis_chat_request", fake_chat)
    kwargs = dict(model_override="test-model", llm_provider_override="openai")
    if invalid_passes == 3:
        with pytest.raises(ValueError, match="required format"):
            app._perform_llm_analysis("run_review", "Entire Session", **kwargs)
        assert len(calls) == 3
    else:
        result = app._perform_llm_analysis("run_review", "Entire Session", **kwargs)
        assert result["response"] == valid
        assert result["completion_path"] == ["initial", "rewrite", "fallback"][invalid_passes]
        assert "api_key" not in result
        assert len(calls) == invalid_passes + 1


@pytest.mark.parametrize("kind", ["playbook", "mcp_tool"])
def test_analysis_scaffold_to_generated_artifact(monkeypatch, tmp_path, kind):
    import app

    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path / "runs"))
    recommendation = (
        "## Recommended Tooling Assets\n"
        f"- Type: {'markdown playbook' if kind == 'playbook' else 'new MCP tool'}\n"
        "- Name: Log Review\n"
        "- Problem: Repeated manual log review\n"
        "- Expected Gain: Save two manual steps\n"
        "- AI Scaffolding Details: Summarize local log files.\n"
        "## Recommended Next Changes\n- Review the result.\n"
    )
    app._create_scaffolding_from_analysis("run_review", recommendation)
    response = app.app.test_client().get("/api/sessions/run_review/scaffolding")
    asset, = response.get_json()["assets"]
    assert asset["name"] == "Log_Review"
    assert "Summarize local log files." in asset["prompt_content"]
    assert "Recommended Next Changes" not in asset["prompt_content"]
    assert app._infer_plugin_kind(None, asset["prompt_content"]) == kind

    generated = "# Log Review\n\nRead the supplied logs."
    if kind == "mcp_tool":
        generated = (
            '### FILE: manifest.json\n```json\n'
            '{"name":"log_review","description":"Review logs","command":"python3","args":["review.py"]}\n```\n'
            '### FILE: review.py\n```python\nprint("Review logs")\n```\n'
            '### FILE: tests/suite.json\n```json\n'
            '{"version":1,"template":"python-files","cases":[{"name":"smoke","args":[],"exit_code":0,"stdout_contains":["Review logs"]}]}\n```\n'
        )
    import claude_generation
    from generated_artifacts import parse_tool_files
    monkeypatch.setattr(claude_generation, "claude_executable", lambda: "claude")
    def fake_cli(workspace, *args, **kwargs):
        files = {"playbook.md": generated} if kind == "playbook" else parse_tool_files(generated)
        for name, content in files.items():
            path = workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return {"num_turns": 1}
    monkeypatch.setattr(claude_generation, "run_claude", fake_cli)
    monkeypatch.setattr(claude_generation.TestRun, "execute", lambda self, **kw: self.finish("blocked", "Test runtime unavailable"))
    target = tmp_path / ("review.md" if kind == "playbook" else "review")
    app._perform_plugin_generation(
        kind, str(target), [{"role": "user", "content": asset["prompt_content"]}],
        "openai", "http://provider.test/v1", None, "test-model", True,
    )
    if kind == "playbook":
        assert target.read_text() == generated
    else:
        assert json.loads((target / "manifest.json").read_text())["name"] == "log_review"
        assert (target / "review.py").read_text().strip() == 'print("Review logs")'


@pytest.fixture(autouse=True)
def clear_analysis_jobs():
    import app

    with app._analysis_lock:
        app._analysis_jobs.clear()
    yield
    with app._analysis_lock:
        app._analysis_jobs.clear()


def test_analysis_chat_request_keeps_read_open_for_openai_compatible_provider(monkeypatch):
    import app

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        return FakeResponse()

    monkeypatch.setattr(app.requests, "post", fake_post)

    app._analysis_chat_request(
        "openai",
        "http://provider.test/v1",
        "token",
        "model-a",
        [{"role": "user", "content": "Analyze this."}],
    )

    assert captured["url"] == "http://provider.test/v1/chat/completions"
    assert captured["timeout"] == (app._ANALYSIS_CONNECT_TIMEOUT_SECONDS, None)


def test_analysis_chat_request_keeps_read_open_for_ollama(monkeypatch):
    import app

    captured = {}

    class FakeOllamaClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def chat(self, **kwargs):
            return {"message": {"content": "ok"}}

    fake_ollama = types.SimpleNamespace(Client=FakeOllamaClient)
    monkeypatch.setitem(sys.modules, "ollama", fake_ollama)

    app._analysis_chat_request(
        "ollama_direct",
        "http://localhost:11434",
        None,
        "model-a",
        [{"role": "user", "content": "Analyze this."}],
        ssl_verify=False,
    )

    assert captured["host"] == "http://localhost:11434"
    assert captured["timeout"].connect == app._ANALYSIS_CONNECT_TIMEOUT_SECONDS
    assert captured["timeout"].read is None
    assert captured["verify"] is False


def test_cancel_running_analysis_job_marks_record_canceled(monkeypatch, tmp_path):
    import app

    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path))
    run_id = "run_cancel_test"
    job_id = "job_cancel_test"
    run_dir = tmp_path / run_id
    run_dir.mkdir()

    record = {
        "job_id": job_id,
        "run_id": run_id,
        "status": "running",
        "status_detail": "Initial analysis pass sent to model-a; model is generating",
        "completion_path": None,
        "start_time": "2026-01-01T00:00:00",
        "last_update_time": "2026-01-01T00:00:00",
        "end_time": None,
        "model": "model-a",
    }

    with app._analysis_lock:
        app._analysis_jobs.clear()
        app._analysis_jobs[job_id] = dict(record)
    app._write_analysis_job_record(run_id, job_id, record)

    client = app.app.test_client()
    response = client.post(f"/api/analysis/jobs/{job_id}/cancel")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True

    with app._analysis_lock:
        live_record = app._analysis_jobs[job_id]
    assert live_record["status"] == "canceled"
    assert live_record["completion_path"] == "canceled"
    assert live_record["cancel_requested"] is True

    with open(tmp_path / run_id / app.ANALYSIS_JOBS_DIRNAME / f"{job_id}.json", "r") as f:
        stored_record = json.load(f)
    assert stored_record["status"] == "canceled"
    assert stored_record["status_detail"] == "Canceled by user; ignoring any late model response"


def test_cancel_completed_analysis_job_is_rejected(monkeypatch, tmp_path):
    import app

    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path))
    run_id = "run_complete_test"
    job_id = "job_complete_test"
    (tmp_path / run_id).mkdir()

    record = {
        "job_id": job_id,
        "run_id": run_id,
        "status": "success",
        "status_detail": "Completed via initial pass",
        "completion_path": "initial",
        "start_time": "2026-01-01T00:00:00",
        "last_update_time": "2026-01-01T00:00:01",
        "end_time": "2026-01-01T00:00:01",
    }

    with app._analysis_lock:
        app._analysis_jobs.clear()
        app._analysis_jobs[job_id] = dict(record)
    app._write_analysis_job_record(run_id, job_id, record)

    client = app.app.test_client()
    response = client.post(f"/api/analysis/jobs/{job_id}/cancel")
    payload = response.get_json()

    assert response.status_code == 409
    assert payload["success"] is False
