import io
import json
from pathlib import Path
import zipfile

import pytest

import claude_generation as generation
from artifact_catalog import DOCUMENT_KINDS, infer_kind, validate_document_files
from artifact_store import document_path, read_document, document_fingerprint, validate_document, validation_report
from generated_artifacts import publish_artifact


def sample_files(kind, name="security-review"):
    return {
        "playbook": {"playbook.md": "# Review\n\n1. Inspect the captured logs.\n"},
        "markdown": {"document.md": "# Analysis notes\n\nThe captured logs lack timestamps.\n"},
        "skill": {"SKILL.md": f"---\nname: {name}\ndescription: Review captured logs when investigating missing timestamps.\n---\n# Review\n\nInspect the logs and record unknowns.\n"},
        "rag_document": {"document.md": "# Log review\n\nThe captured logs lack timestamps.\n\n## Recommendation\nPreserve records with unknown timestamps.\n",
                         "metadata.json": json.dumps({"title": "Log review", "summary": "Timestamp handling from analysis", "tags": ["logs"]})},
        "template": {"TEMPLATE.md": "# Review {{target_name}}\n\nFindings: {{findings}}\n", "README.md": "Fill target_name with the test target and findings with evidence."},
        "structured_data": {"data.json": '{"findings":[{"issue":"missing timestamps","confidence":"observed"}]}', "README.md": "findings contains observed issues from analysis."},
    }[kind]


@pytest.mark.parametrize("kind", sorted(DOCUMENT_KINDS))
def test_generate_documents_without_container_execution(tmp_path, monkeypatch, kind):
    name = "security-review"
    target = document_path(tmp_path, kind, name, must_exist=False)
    monkeypatch.setattr(generation, "claude_executable", lambda: "claude")
    def cli(workspace, prompt, *args, **kwargs):
        assert name in prompt
        for filename, content in sample_files(kind).items():
            (workspace / filename).write_text(content)
        return {"response": "Created document"}
    monkeypatch.setattr(generation, "run_claude", cli)
    monkeypatch.setattr(generation.TestRun, "execute", lambda *a, **kw: pytest.fail("Documents must not execute"))
    result = generation.generate_artifact(kind, target, [{"content": "Use the analysis"}], "http://localhost:8080", None, "own-model")
    assert not result["test_reports"]
    assert validate_document(tmp_path, kind, name)["status"] == "passed"
    assert not validation_report(tmp_path, kind, name)["outdated"]
    assert set(read_document(target, kind)) >= set(sample_files(kind))


@pytest.mark.parametrize("kind", sorted(DOCUMENT_KINDS))
def test_followup_edits_and_validation_for_each_document_type(tmp_path, monkeypatch, kind):
    name = "security-review"
    target = document_path(tmp_path, kind, name, must_exist=False)
    original = validate_document_files(kind, sample_files(kind), name)
    publish_artifact(str(target), original, single_file=kind == "playbook")
    validate_document(tmp_path, kind, name)
    def cli(workspace, prompt, *args, **kwargs):
        assert not kwargs["lock_tests"]
        files = sample_files(kind)
        markdown = next(filename for filename in files if filename.endswith(".md"))
        files[markdown] += "\nAdditional evidence was not available.\n"
        for filename, content in files.items():
            (workspace / filename).write_text(content)
        return {"response": "Added the evidence limitation."}
    monkeypatch.setattr(generation, "run_claude", cli)
    generation.refine_artifact(target, [{"role": "user", "content": "Document the unknowns"}], {}, document_fingerprint(target, kind),
                               "http://localhost:8080", None, "own-model", kind=kind)
    assert validation_report(tmp_path, kind, name)["outdated"]
    assert validate_document(tmp_path, kind, name)["status"] == "passed"


def test_rag_chunks_are_derived_from_source_and_stale_chunks_fail(tmp_path):
    files = sample_files("rag_document")
    files["document.md"] += "\n" + ("This is recorded evidence. " * 300)
    files["chunks.jsonl"] = '{"text":"invented by the model"}'
    generated = validate_document_files("rag_document", files, "security-review")
    chunks = [json.loads(line) for line in generated["chunks.jsonl"].splitlines()]
    assert len(chunks) > 1
    assert len({chunk["id"] for chunk in chunks}) == len(chunks)
    assert all(chunk["text"] in files["document.md"] and len(chunk["text"]) <= 1800 for chunk in chunks)
    assert generated["chunks.jsonl"] == validate_document_files("rag_document", generated, "security-review")["chunks.jsonl"]
    path = document_path(tmp_path, "rag_document", "security-review", must_exist=False)
    publish_artifact(str(path), generated)
    (path / "document.md").write_text("Changed source")
    assert validate_document(tmp_path, "rag_document", "security-review")["status"] == "failed"


@pytest.mark.parametrize("kind,change", [
    ("markdown", {"outside.py": "pass"}),
    ("markdown", {"../outside.md": "content"}),
    ("skill", {"SKILL.md": "# Missing metadata"}),
    ("skill", {"SKILL.md": "---\nname: wrong-name\ndescription: Review\n---\nInstructions"}),
    ("skill", {"scripts/run.py": "pass"}),
    ("rag_document", {"metadata.json": '{"title":"Review","summary":"Review","tags":"invalid"}'}),
    ("template", {"README.md": "No variables documented"}),
    ("structured_data", {"data.json": "not JSON"}),
    ("structured_data", {"data.json": "[]"}),
])
def test_invalid_document_contracts_are_rejected(kind, change):
    with pytest.raises(ValueError):
        validate_document_files(kind, {**sample_files(kind), **change}, "security-review")


@pytest.fixture
def document_app(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "PLUGINS_DIR", str(tmp_path / "plugins"))
    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(app, "_plugin_jobs", {})
    monkeypatch.setattr(app, "_plugin_generation_targets", set())
    monkeypatch.setattr(app, "_analysis_jobs", {"analysis_original": {"job_id": "analysis_original", "run_id": "run_test",
        "status": "success", "response": "# Analysis\nThe captured logs lack timestamps."}})
    monkeypatch.setattr(app, "claude_executable", lambda: "claude")
    monkeypatch.setattr(generation, "claude_executable", lambda: "claude")
    queued = []
    class Thread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args
        def start(self):
            queued.append(lambda: self.target(*self.args))
    monkeypatch.setattr(app.threading, "Thread", Thread)
    return app, queued


@pytest.mark.parametrize("kind", sorted(DOCUMENT_KINDS))
def test_create_from_analysis_preview_export_and_conversation(document_app, monkeypatch, kind):
    app, queued = document_app
    client = app.app.test_client()
    def cli(workspace, prompt, *args, **kwargs):
        assert "captured logs lack timestamps" in prompt
        assert "Include actionable guidance" in prompt
        for filename, content in sample_files(kind).items():
            (workspace / filename).write_text(content)
        return {"response": "Document created"}
    monkeypatch.setattr(generation, "run_claude", cli)
    started = client.post("/api/scaffolding/generate", json={"run_id": "run_test", "analysis_job_id": "analysis_original",
        "asset_name": "security-review", "kind": kind, "model": "own-model", "instructions": "Include actionable guidance"})
    assert started.status_code == 200
    queued.pop(0)()
    job = app._plugin_jobs[started.get_json()["job_id"]]
    assert job["status"] == "success", job
    base = f"/api/artifacts/{kind}/security-review"
    detail = client.get(base)
    assert detail.status_code == 200
    assert detail.get_json()["validation"]["status"] == "passed"
    download = client.get(base + "/download")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        assert "security-review/PROVENANCE.md" in archive.namelist()
        for filename in sample_files(kind):
            assert f"security-review/{filename}" in archive.namelist()
    listing = client.get("/api/plugins").get_json()["artifacts"]
    assert any(entry["kind"] == kind and entry["name"] == "security-review" for entry in listing)
    conversation = client.get(base + "/conversation").get_json()
    assert conversation["check_label"] == "Validate"
    followup = client.post(base + "/conversation", json={"prompt": "Keep the same content", "revision": conversation["revision"],
        "artifact_sha256": conversation["artifact_sha256"]})
    assert followup.status_code == 202
    assert client.post(base + "/validate").status_code == 409
    queued.pop(0)()
    assert client.get(base + "/conversation").get_json()["can_test"]
    assert client.post(base + "/validate").get_json()["status"] == "passed"


def test_source_job_and_kind_are_validated(document_app):
    app, queued = document_app
    client = app.app.test_client()
    payload = {"run_id": "run_other", "analysis_job_id": "analysis_original", "asset_name": "doc", "kind": "markdown", "model": "own-model"}
    assert client.post("/api/scaffolding/generate", json=payload).status_code == 400
    payload.update(run_id="run_test", kind="unknown")
    assert client.post("/api/scaffolding/generate", json=payload).status_code == 400
    assert not queued
    assert client.get("/api/artifacts/unknown/security-review/download").status_code == 400


@pytest.mark.parametrize("label,expected", [("markdown playbook", "playbook"), ("Markdown document", "markdown"),
    ("Agent skill", "skill"), ("RAG document", "rag_document"), ("Reusable template", "template"), ("Structured JSON", "structured_data")])
def test_recommendation_type_inference(label, expected):
    assert infer_kind(None, f"**Type**: {label}") == expected


def test_generation_dialog_contains_all_artifact_choices(document_app):
    app, _ = document_app
    response = app.app.test_client().get("/")
    assert response.status_code == 200
    for kind in DOCUMENT_KINDS:
        assert f'value="{kind}"'.encode() in response.data
