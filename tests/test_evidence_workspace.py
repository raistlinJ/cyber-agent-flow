import argparse
import asyncio
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import evidence_workspace as ws


@pytest.fixture
def registry(tmp_path, monkeypatch):
    p = tmp_path / "profiles.json"
    ws.write(
        tmp_path / "model.json",
        {
            "model": {"provider": "openai", "url": "https://example.invalid", "name": "test"},
            "candidates": {},
            "version": 1,
        },
    )
    ws.write(p, {"case": {"instance": "package", "config": "model.json", "source": "previous"}})
    monkeypatch.setenv("CAF_EVIDENCE_PROFILES", str(p))
    monkeypatch.setenv("CAF_EVIDENCE_WORKSPACE", str(tmp_path / "jobs"))
    return tmp_path


def test_web_cli_ssh_share_registry(registry, capsys, monkeypatch):
    from app import app
    import cli

    client = app.test_client()
    response = client.get("/api/evidence-studies")
    assert response.status_code == 200
    data = response.get_json()
    assert data["profiles"] == ["case"]
    assert data["items"][0]["id"] == "source-case"
    assert str(registry) not in str(data)
    assert "evidence-studies" in client.get("/").get_data(as_text=True)
    assert "Runnable experiments" in client.get("/evidence-studies").get_data(as_text=True)
    monkeypatch.chdir(registry)
    assert cli.main(["artifacts", "list"]) == 0
    assert "source-case" in capsys.readouterr().out

    spec = importlib.util.spec_from_file_location(
        "ssh_impl_for_evidence", Path(cli.__file__).with_name("cli-server.py")
    )
    ssh_impl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ssh_impl)
    connection = SimpleNamespace(client_cmd="artifacts list", base_args=argparse.Namespace(command=None))
    with patch.object(
        cli, "_start_session", side_effect=AssertionError("SSH evidence command started an agent")
    ):
        asyncio.run(ssh_impl.CyberAgentFlowSSHSession.handle_client(connection))
    assert "source-case" in capsys.readouterr().out

    handler = cli.TerminalEventHandler(stream_out=io.StringIO(), tool_output_chars=4000, verbose=False)
    asyncio.run(cli._handle_repl_command("/artifacts list", None, None, None, None, handler, {}, "", set()))
    assert "source-case" in handler.stream_out.getvalue()


def test_input_validation_and_plan(registry):
    from app import app

    client = app.test_client()
    base = "/api/evidence-studies/actions/"
    assert client.post(base + "baseline", json={"profile": "../../private"}).status_code == 400
    assert (
        client.post(base + "baseline", json={"profile": "case", "config": "/private/model"}).status_code
        == 400
    )
    assert client.post(base + "compare", json={"ids": [{}, {}]}).status_code == 400
    cfg = {
        "profile": "case",
        "counts": {"playbook": 2, "lora_suggestion": 5},
        "selection": "improve",
        "repetitions": 2,
        "keep_top": 1,
    }
    assert client.post(base + "plan", json=cfg).get_json()["max_participant_trials"] == 8
    assert client.post(base + "plan", json=dict(cfg, selection="custom")).status_code == 400
    assert client.post(base + "plan", json=dict(cfg, counts={"playbook": True})).status_code == 400
    assert client.get("/api/evidence-studies/items/not-a-job").status_code == 400


def test_workflow_shapes_and_comparison(registry, monkeypatch):
    import evidence_review as core
    from app import app

    client = app.test_client()

    def synchronous(argv, **kwargs):
        ws.execute(argv[-1])
        return object()

    monkeypatch.setattr(ws.subprocess, "Popen", synchronous)
    base = {
        "case": "case",
        "package_hash": "same",
        "baseline": {"flags_recovered": 1, "flags_available": 2, "incorrect_submissions": 0},
        "baseline_rows": [{"valid_format": True}],
        "confirmation": None,
        "candidates": [],
    }
    eligible = {"id": "tool-001", "eligible": True}
    advice = {"id": "lora_suggestion-001", "eligible": False}

    def analyze(source, instance, config, review):
        assert source == registry / "previous"
        review.mkdir()
        ws.write(review / "review.json", dict(base, analysis=["Review the evidence."]))

    def generate(source, instance, config, review, counts):
        assert ws.read(review / "review.json")["analysis"]
        assert counts == {"tool": 1}
        ws.write(review / "review.json", dict(base, candidates=[eligible, advice]))

    def save(review, enabled, experiment, name):
        assert enabled == ["tool-001"]
        experiment.mkdir()
        return {"name": name, "enabled": enabled}

    def run(exp, instance, config, output):
        output.mkdir()
        ws.write(
            output / "report.json", dict(base, baseline_rows=[{"flags_in_answer": 2, "valid_format": False}])
        )

    monkeypatch.setattr(core, "analyze_study", analyze)
    monkeypatch.setattr(core, "generate_review", generate)
    monkeypatch.setattr(core, "inspect_review", lambda d: ws.read(d / "review.json"))
    monkeypatch.setattr(
        core, "inspect_study", lambda d: base if d == registry / "previous" else ws.read(d / "report.json")
    )
    monkeypatch.setattr(core, "save_experiment", save)
    monkeypatch.setattr(core, "run_experiment", run)

    def action(name, body, code=201):
        result = client.post("/api/evidence-studies/actions/" + name, json=body)
        assert result.status_code == code, result.get_json()
        return result.get_json()

    analysis = action("analyze", {"source": "source-case"})
    review = action("generate", {"source": analysis["id"], "counts": {"tool": 1}})
    action("save", {"source": review["id"], "enabled": ["lora_suggestion-001"], "name": "Review"}, 400)
    exp = action("save", {"source": review["id"], "enabled": ["tool-001"], "name": "Review"})
    assert exp["kind"] == "save" and exp["status"] == "complete"
    assert ws.describe(analysis["id"])["detail"]["candidates"] == []
    completed = action("run", {"source": exp["id"]})
    rows = action("compare", {"ids": ["source-case", completed["id"]]}, 200)["rows"]
    assert [r["flags_in_answer"] for r in rows] == [None, 2]
    assert [r["valid_submissions"] for r in rows] == [1, 0]
    assert [r["flags_recovered"] for r in rows] == [1, 1]


def test_interrupted_process_releases_lease(registry, monkeypatch):
    ident = "a" * 32
    entry = ws.item_dir(ident)
    entry.mkdir(parents=True)
    ws.write(entry / "item.json", {"id": ident, "status": "running", "kind": "run", "profile": "case"})
    assert ws.registered(ident)["status"] == "interrupted"

    def worker(argv, **kwargs):
        f = ws.item_dir(argv[-1]) / "item.json"
        ws.write(f, dict(ws.read(f), status="complete"))

    monkeypatch.setattr(ws.subprocess, "Popen", worker)
    assert ws.resume(ident)["status"] == "complete"
    with pytest.raises(ValueError, match="Only a failed"):
        ws.resume(ident)
