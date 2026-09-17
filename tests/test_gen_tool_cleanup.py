import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

import gen_tool_test_runtime as runtime
import gen_tool_tests


@pytest.fixture
def docker_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("CYBER_AGENT_FLOW_TEST_RUNTIME_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(runtime, "resource_scope", lambda: "cleanup-test-scope")
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "/fake/docker")
    labels = {runtime.MANAGED_LABEL: runtime.MANAGED_VALUE, runtime.SCOPE_LABEL: runtime.resource_scope()}
    images = {
        "sha256:legacy": {"Id": "sha256:legacy", "RepoTags": [runtime.DEFAULT_IMAGE], "Config": {"Entrypoint": ["python3", "/runner/runner.py"], "Labels": {}}},
        "sha256:owned": {"Id": "sha256:owned", "RepoTags": ["caf-owned:1"], "Config": {"Labels": {**labels, runtime.IMAGE_LABEL: "caf-owned:1"}}},
        "sha256:dangling": {"Id": "sha256:dangling", "RepoTags": [], "Config": {"Labels": labels}},
    }
    containers = {}
    calls = []
    failures = set()
    def add(name_char, *, state="exited", owned=True, image="sha256:owned", other_scope=False):
        identifier = name_char * 64
        container_labels = dict(labels) if owned else {}
        if other_scope:
            container_labels[runtime.SCOPE_LABEL] = "other-checkout"
        containers[identifier] = {"Id": identifier, "Name": "/caf-test-" + name_char * 32,
                                 "Image": image, "Config": {"Labels": container_labels}, "State": {"Status": state}}
        return identifier
    def command(binary, *args, allow_missing=False):
        calls.append(args)
        assert "prune" not in args
        kind, action, *rest = args
        if action == "ls" and kind == "container":
            ancestor = next((arg.removeprefix("ancestor=") for arg in rest if arg.startswith("ancestor=")), None)
            return "\n".join(identifier for identifier, info in containers.items() if not ancestor or info["Image"] == ancestor)
        if action == "ls" and kind == "image":
            return "\n".join(identifier for identifier, info in images.items() if runtime._owned(info["Config"].get("Labels", {})))
        records = containers if kind == "container" else images
        identifier = rest[-1]
        if kind == "image" and identifier not in images:
            identifier = next((key for key, info in images.items() if identifier in info.get("RepoTags", [])), identifier)
        if action == "inspect":
            return json.dumps([records[identifier]]) if identifier in records else ""
        if action == "rm":
            if identifier in failures:
                raise ValueError("resource busy")
            records.pop(identifier, None)
            return identifier
        raise AssertionError(args)
    monkeypatch.setattr(runtime, "_docker", command)
    return add, containers, images, calls, failures


def test_cleanup_removes_owned_orphans_and_stopped_legacy_only(docker_mock):
    add, containers, _, calls, _ = docker_mock
    stopped = add("a")
    orphan = add("b", state="running")
    partial = add("c", state="created")
    legacy = add("d", owned=False, image="sha256:legacy")
    active_legacy = add("e", owned=False, image="sha256:legacy", state="running")
    unrelated = add("f", owned=False, image="sha256:unrelated")
    other = add("0", other_scope=True)
    report = runtime.cleanup_resources()
    assert {item["id"] for item in report["containers"]} == {stopped, orphan, partial, legacy}
    assert set(containers) == {active_legacy, unrelated, other}
    assert report["skipped"][0]["resource"] == "caf-test-" + "e" * 32
    assert not report["images"]
    assert ("container", "rm", legacy) in calls  # Never force an unlabeled legacy container.
    assert ("container", "rm", "--force", orphan) in calls


def test_dry_run_and_repeated_cleanup(docker_mock):
    add, containers, images, calls, _ = docker_mock
    identifier = add("a", state="running")
    preview = runtime.cleanup_resources(remove_images=True, dry_run=True)
    assert identifier in containers and len(images) == 3
    assert len(preview["containers"]) == 1 and len(preview["images"]) == 3
    assert not any(command[1] == "rm" for command in calls)
    done = runtime.cleanup_resources(remove_images=True)
    assert done["status"] == "success" and not containers and not images
    assert not any("--force" in command for command in calls if command[0] == "image")
    again = runtime.cleanup_resources(remove_images=True)
    assert again["containers"] == [] and again["images"] == []


def test_image_only_preserves_containers_and_shared_images(docker_mock):
    add, containers, images, _, _ = docker_mock
    identifier = add("a")
    images["sha256:dangling"]["RepoTags"] = ["caf-other:1", "shared:1"]
    report = runtime.cleanup_resources(remove_containers=False, remove_images=True)
    assert identifier in containers
    assert set(images) == {"sha256:owned", "sha256:dangling"}
    assert len(report["skipped"]) == 2
    assert len(report["images"]) == 1


def test_failed_removal_keeps_image_and_reports_partial(docker_mock):
    add, containers, images, _, failures = docker_mock
    identifier = add("a")
    failures.add(identifier)
    report = runtime.cleanup_resources(remove_images=True)
    assert report["status"] == "partial"
    assert identifier in containers and "sha256:owned" in images
    assert report["errors"][0]["error"] == "resource busy"


def test_activity_guard_blocks_cleanup_across_processes(docker_mock):
    _, _, _, calls, _ = docker_mock
    code = '''import gen_tool_test_runtime as runtime
runtime.resource_scope = lambda: "cleanup-test-scope"
with runtime.runtime_guard(cleanup=True):
    print("cleanup acquired")
'''
    with runtime.runtime_guard():
        with pytest.raises(runtime.RuntimeBusyError):
            runtime.cleanup_resources()
        child = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert child.returncode != 0 and "in progress" in child.stderr
    child = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert child.returncode == 0
    assert not calls


def test_cleanup_guard_blocks_test_start(docker_mock, tmp_path):
    root = tmp_path / "plugins"
    artifact = root / "mcp_tools/hello"
    artifact.mkdir(parents=True)
    (artifact / "manifest.json").write_text("{}")
    with runtime.runtime_guard(cleanup=True):
        report = gen_tool_tests.TestRun(root, "hello").execute()
    assert report["status"] == "blocked"
    assert "in progress" in report["message"]


def test_cleanup_api_options_and_busy_status(monkeypatch):
    import app
    calls = []
    def cleanup(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "containers": [], "images": [], "skipped": [], "errors": []}
    monkeypatch.setattr(app, "cleanup_resources", cleanup)
    client = app.app.test_client()
    endpoint = "/api/plugins/test-runtime/cleanup"
    assert client.post(endpoint, json={"remove_images": "false"}).status_code == 400
    assert client.post(endpoint, json={"remove_containers": False, "remove_images": False}).status_code == 400
    assert client.post(endpoint, json=[]).status_code == 400
    assert client.post(endpoint, json={"remove_containers": False, "remove_images": True, "dry_run": True}).status_code == 200
    assert len(calls) == 1 and calls[0]["remove_images"] and not calls[0]["remove_containers"] and calls[0]["dry_run"]
    def busy(**kwargs):
        raise runtime.RuntimeBusyError("Testing in progress")
    monkeypatch.setattr(app, "cleanup_resources", busy)
    assert client.post(endpoint, json={}).status_code == 409


@pytest.mark.parametrize("flags,expected", [([], (True, False, False)), (["--images"], (True, True, False)),
    (["--images-only", "--dry-run"], (False, True, True))])
def test_cleanup_cli_flags(monkeypatch, capsys, flags, expected):
    calls = []
    def cleanup(**kwargs):
        calls.append(kwargs)
        return {"status": "success"}
    monkeypatch.setattr(gen_tool_tests, "cleanup_resources", cleanup)
    assert gen_tool_tests.main(["cleanup", *flags]) == 0
    assert tuple(calls[0][key] for key in ("remove_containers", "remove_images", "dry_run")) == expected
    assert json.loads(capsys.readouterr().out)["status"] == "success"


@pytest.mark.skipif(os.environ.get("CAF_TEST_DOCKER") != "1", reason="Set CAF_TEST_DOCKER=1 for scoped Docker cleanup")
def test_real_docker_cleanup_preserves_active_and_unrelated_resources(tmp_path, monkeypatch):
    scope = "cleanup-integration-" + uuid.uuid4().hex
    monkeypatch.setattr(runtime, "resource_scope", lambda: scope)
    monkeypatch.setenv("CYBER_AGENT_FLOW_TEST_RUNTIME_DIR", str(tmp_path / "locks"))
    image = "caf-cleanup-check:" + uuid.uuid4().hex
    # Only resources created by this test are removed. The normal reusable image remains.
    (tmp_path / "Dockerfile").write_text(f"FROM {runtime.DEFAULT_IMAGE}\n")
    subprocess.run(["docker", "build", "-q", *runtime.docker_labels(), "--label", f"{runtime.IMAGE_LABEL}={image}",
                    "-t", image, str(tmp_path)], check=True, capture_output=True, timeout=60)
    native_inspect = runtime._inspect
    monkeypatch.setattr(runtime, "_inspect", lambda binary, kind, identifier: None if kind == "image" and identifier == runtime.DEFAULT_IMAGE
                        else native_inspect(binary, kind, identifier))
    created = []
    try:
        for own in (True, True, False):
            name = "caf-test-" + uuid.uuid4().hex
            labels = runtime.docker_labels() if own else ["--label", f"{runtime.SCOPE_LABEL}=unrelated-test"]
            subprocess.run(["docker", "create", "--name", name, *labels, "--entrypoint", "python3", image,
                            "-c", "import time; time.sleep(120)"], check=True, capture_output=True, timeout=20)
            created.append(name)
        subprocess.run(["docker", "start", created[0]], check=True, capture_output=True, timeout=20)
        with runtime.runtime_guard():
            with pytest.raises(runtime.RuntimeBusyError):
                runtime.cleanup_resources(image=image)
        report = runtime.cleanup_resources(image=image, dry_run=True)
        assert {item["name"] for item in report["containers"]} == set(created[:2])
        removed = runtime.cleanup_resources(image=image)
        assert {item["name"] for item in removed["containers"]} == set(created[:2])
        kept = runtime.cleanup_resources(image=image, remove_containers=False, remove_images=True, dry_run=True)
        image_id = subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()
        assert any(item["resource"] == image_id for item in kept["skipped"])
        subprocess.run(["docker", "rm", "-f", created[2]], check=True, capture_output=True, timeout=20)
        removed_images = runtime.cleanup_resources(image=image, remove_containers=False, remove_images=True)
        assert image_id in {item["id"] for item in removed_images["images"]}
        assert subprocess.run(["docker", "image", "inspect", runtime.DEFAULT_IMAGE], capture_output=True).returncode == 0
    finally:
        for name in created:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
        subprocess.run(["docker", "image", "rm", image], capture_output=True, timeout=20)
