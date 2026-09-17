"""Scoped Docker resource cleanup and a cross-process guard for test activity."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = "cyber-agent-flow-tool-tests:1"
MANAGED_LABEL = "io.cyber-agent-flow.managed"
SCOPE_LABEL = "io.cyber-agent-flow.scope"
IMAGE_LABEL = "io.cyber-agent-flow.image-ref"
MANAGED_VALUE = "tool-tests"


class RuntimeBusyError(RuntimeError):
    pass


def resource_scope():
    identity = f"{socket.gethostname()}:{os.getuid()}:{ROOT}"
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def docker_labels():
    return ["--label", f"{MANAGED_LABEL}={MANAGED_VALUE}", "--label", f"{SCOPE_LABEL}={resource_scope()}"]


@contextmanager
def runtime_guard(*, cleanup=False):
    directory = Path(os.environ.get("CYBER_AGENT_FLOW_TEST_RUNTIME_DIR", Path.home() / ".cache/cyber-agent-flow/tool-tests"))
    directory.mkdir(parents=True, exist_ok=True)
    # Checkouts share the default image tag, so activity also shares a guard.
    with open(directory / "runtime.lock", "a") as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if cleanup else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeBusyError("Test activity or cleanup is in progress. Wait for it to finish and retry.") from exc
        yield


def _docker(binary, *args, allow_missing=False):
    try:
        result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Docker cleanup command timed out. Check the daemon and retry.") from exc
    if result.returncode:
        if allow_missing and any(text in result.stderr.lower() for text in ("no such", "not found")):
            return ""
        raise ValueError((result.stderr or result.stdout or "Docker command failed.").strip()[-2000:])
    return result.stdout


def _inspect(binary, kind, identifier):
    output = _docker(binary, kind, "inspect", identifier, allow_missing=True)
    return json.loads(output)[0] if output else None


def _owned(labels):
    return labels.get(MANAGED_LABEL) == MANAGED_VALUE and labels.get(SCOPE_LABEL) == resource_scope()


def cleanup_resources(*, remove_containers=True, remove_images=False, dry_run=False, image=DEFAULT_IMAGE):
    """Clean this checkout's test resources; never use global Docker prune."""
    if any(not isinstance(value, bool) for value in (remove_containers, remove_images, dry_run)) or not (remove_containers or remove_images):
        raise ValueError("Select containers, images, or both using boolean options.")
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Docker is unavailable. Install/start Docker before cleaning test resources.")
    with runtime_guard(cleanup=True):
        report = {"dry_run": dry_run, "containers": [], "images": [], "skipped": [], "errors": []}
        # Verify daemon access before interpreting a missing legacy image as harmless.
        ids = _docker(docker, "container", "ls", "--all", "--no-trunc", "--filter", "name=caf-test-", "--format", "{{.ID}}").split()
        legacy_image = _inspect(docker, "image", DEFAULT_IMAGE)
        legacy_config = (legacy_image or {}).get("Config") or {}
        legacy_ok = (legacy_config.get("Entrypoint") == ["python3", "/runner/runner.py"]
                     and not (legacy_config.get("Labels") or {}).get(SCOPE_LABEL))
        selected_containers = set()
        if remove_containers:
            for identifier in ids:
                info = _inspect(docker, "container", identifier)
                if not info:
                    continue
                name = info.get("Name", "").lstrip("/")
                if not re.fullmatch(r"caf-test-[0-9a-f]{32}", name):
                    continue
                labels = (info.get("Config") or {}).get("Labels") or {}
                owned = _owned(labels)
                legacy = not labels.get(SCOPE_LABEL) and legacy_ok and info.get("Image") == legacy_image["Id"]
                if not (owned or legacy):
                    continue
                state = (info.get("State") or {}).get("Status", "unknown")
                if not owned and state not in {"exited", "dead"}:
                    report["skipped"].append({"resource": name, "reason": "Legacy container may still be active; only stopped legacy containers are removed."})
                    continue
                entry = {"id": identifier, "name": name, "state": state}
                try:
                    if not dry_run:
                        # Current runs hold the shared guard, so a labeled running
                        # container under this exclusive guard is an orphan.
                        _docker(docker, "container", "rm", *(["--force"] if owned else []), identifier, allow_missing=True)
                    report["containers"].append(entry)
                    selected_containers.add(identifier)
                except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                    report["errors"].append({"resource": name, "error": str(exc)})

        if remove_images:
            image_ids = set(_docker(docker, "image", "ls", "--all", "--no-trunc", "--filter", f"label={MANAGED_LABEL}={MANAGED_VALUE}",
                                   "--filter", f"label={SCOPE_LABEL}={resource_scope()}", "--format", "{{.ID}}").split())
            if legacy_ok:
                image_ids.add(legacy_image["Id"])
            for identifier in sorted(image_ids):
                info = _inspect(docker, "image", identifier)
                if not info:
                    continue
                labels = (info.get("Config") or {}).get("Labels") or {}
                legacy = legacy_ok and identifier == legacy_image["Id"]
                if not (_owned(labels) or legacy):
                    continue
                tags = info.get("RepoTags") or []
                allowed_tags = {DEFAULT_IMAGE, image, labels.get(IMAGE_LABEL)}
                if len(tags) > 1 or any(tag not in allowed_tags for tag in tags):
                    report["skipped"].append({"resource": identifier, "reason": "Image has other tags; kept to preserve shared images."})
                    continue
                users = set(_docker(docker, "container", "ls", "--all", "--no-trunc", "--filter", f"ancestor={identifier}", "--format", "{{.ID}}").split())
                if dry_run:
                    users -= selected_containers
                if users:
                    report["skipped"].append({"resource": identifier, "reason": "Image is referenced by a retained container."})
                    continue
                entry = {"id": identifier, "tags": tags}
                try:
                    if not dry_run:
                        # No --force: Docker also checks references that appeared
                        # outside this app between inspection and removal.
                        _docker(docker, "image", "rm", tags[0] if tags else identifier, allow_missing=True)
                    report["images"].append(entry)
                except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                    report["errors"].append({"resource": identifier, "error": str(exc)})
        report["status"] = "partial" if report["errors"] else "success"
        return report


def build_test_image(image):
    with runtime_guard():
        return subprocess.run(["docker", "build", *docker_labels(), "--label", f"{IMAGE_LABEL}={image}",
                               "-t", image, str(ROOT / "gen_tool_test_env")]).returncode
