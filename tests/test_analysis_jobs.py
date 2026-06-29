import json
import sys
import types

import pytest


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
