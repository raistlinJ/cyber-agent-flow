"""Container tests for generated MCP tools under plugins/mcp_tools, excluding built-in tools."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from gen_tool_test_env.suite import load_suite
from gen_tool_test_runtime import DEFAULT_IMAGE, RuntimeBusyError, runtime_guard, docker_labels, cleanup_resources, build_test_image

ROOT = Path(__file__).resolve().parent
DEFAULT_PLUGINS = ROOT / "plugins"
IMAGE = os.environ.get("CYBER_AGENT_FLOW_TEST_IMAGE", DEFAULT_IMAGE)
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


class TestBusyError(RuntimeError):
    pass


def run_container(command, cancel_check):
    if cancel_check is None:
        return subprocess.run(command, capture_output=True, text=True, timeout=270)
    import time
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        while True:
            if cancel_check():
                raise InterruptedError("Test run canceled.")
            if time.monotonic() - started > 270:
                raise subprocess.TimeoutExpired(command, 270)
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def tool_path(plugins_dir, name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Invalid tool folder name.")
    path = Path(plugins_dir) / "mcp_tools" / name
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Generated tool not found.")
    return path


def artifact_files(path):
    total = 0
    for directory, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {"__pycache__", ".git"})
        for name in dirs + sorted(names):
            item = Path(directory) / name
            if item.is_symlink():
                raise ValueError("Test artifacts cannot contain symlinks.")
        for name in sorted(names):
            item = Path(directory) / name
            if name == "PROVENANCE.md" or name.endswith(".pyc"):
                continue
            if not item.is_file():
                raise ValueError("Test artifacts must contain regular files.")
            total += item.stat().st_size
            if total > MAX_ARTIFACT_BYTES:
                raise ValueError("Test artifact exceeds the 20 MiB fixture limit.")
            yield item


def fingerprint(path):
    digest = hashlib.sha256()
    for item in artifact_files(path):
        digest.update(item.relative_to(path).as_posix().encode() + b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".report-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def latest_report(plugins_dir, name):
    artifact = tool_path(plugins_dir, name)
    folder = Path(plugins_dir) / "test_results" / name
    paths = sorted(folder.glob("*.json"), reverse=True)
    if not paths:
        return {"status": "not_tested", "tool": name}
    report = json.loads(paths[0].read_text())
    try:
        report["outdated"] = report.get("artifact_sha256") != fingerprint(artifact)
    except (ValueError, OSError):
        report["outdated"] = True
    if report.get("status") == "running":
        with open(folder / ".lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                report.update(status="error", message="Test worker stopped before finishing. Run tests again.")
            except BlockingIOError:
                pass
    return report


class TestRun:
    def __init__(self, plugins_dir, name, trigger="manual"):
        self.artifact = tool_path(plugins_dir, name)
        folder = Path(plugins_dir) / "test_results" / name
        folder.mkdir(parents=True, exist_ok=True)
        self.lock = open(folder / ".lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise TestBusyError("Tests are already running for this tool.") from exc
        try:
            self.report = {"test_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "_" + uuid.uuid4().hex[:8],
                           "tool": name, "status": "running", "trigger": trigger, "started_at": timestamp(),
                           "artifact_sha256": fingerprint(self.artifact), "image": IMAGE, "cases": []}
            self.path = folder / (self.report["test_id"] + ".json")
            write_report(self.path, self.report)
        except Exception:
            self.lock.close()
            raise

    def finish(self, status, message=None, **fields):
        self.report.update(status=status, finished_at=timestamp(), **fields)
        if message:
            self.report["message"] = message
        try:
            write_report(self.path, self.report)
        finally:
            self.lock.close()
        return self.report

    def execute(self, cancel_check=None):
        try:
            with runtime_guard():
                return self._execute(cancel_check)
        except RuntimeBusyError as exc:
            return self.finish("blocked", str(exc))
        except OSError as exc:
            return self.finish("error", str(exc))

    def _execute(self, cancel_check=None):
        container = "caf-test-" + uuid.uuid4().hex
        docker = shutil.which("docker")
        launched = False
        try:
            if not (self.artifact / "tests/suite.json").is_file():
                return self.finish("not_tested", "No tests/suite.json. Regenerate with tests or add a test plan.")
            suite = load_suite(self.artifact / "tests/suite.json")
            self.report["template"] = suite["template"]
            if not docker:
                return self.finish("blocked", "Docker is unavailable. Install/start Docker and rerun tests.")
            inspect = subprocess.run([docker, "image", "inspect", IMAGE, "--format", "{{.Id}}"], capture_output=True, text=True, timeout=15)
            if inspect.returncode:
                return self.finish("blocked", "Test image or Docker daemon unavailable. Start Docker and run: python gen-tool_tests.py build")
            self.report["image_id"] = inspect.stdout.strip()
            with tempfile.TemporaryDirectory(prefix="caf-tool-test-") as temporary:
                snapshot = Path(temporary) / "artifact"
                snapshot.mkdir(mode=0o755)
                for item in artifact_files(self.artifact):
                    target = snapshot / item.relative_to(self.artifact)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item, target)
                    target.chmod(0o644)
                # The report describes exactly the snapshot executed, even during regeneration.
                self.report["artifact_sha256"] = fingerprint(snapshot)
                load_suite(snapshot / "tests/suite.json")
                command = [docker, "run", "--rm", "--pull=never", "--name", container,
                           *docker_labels(),
                           "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                           "--user", "65534:65534", "--pids-limit", "64", "--memory", "256m", "--memory-swap", "256m", "--cpus", "1",
                           "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777", "--log-driver=none",
                           "--mount", f"type=bind,src={snapshot},dst=/artifact,readonly", self.report["image_id"]]
                launched = True
                result = run_container(command, cancel_check)
                if result.returncode:
                    return self.finish("error", (result.stderr or result.stdout or "Container failed.")[-16000:])
                output = json.loads(result.stdout)
                if output.get("status") not in {"passed", "failed"} or not isinstance(output.get("cases"), list) or len(output["cases"]) != len(suite["cases"]):
                    raise ValueError("Container returned an invalid test report.")
                return self.finish(output["status"], cases=output["cases"])
        except InterruptedError:
            return self.finish("canceled", "Test run canceled.")
        except subprocess.TimeoutExpired:
            return self.finish("error", "Container exceeded its execution deadline.")
        except Exception as exc:
            return self.finish("error", str(exc)[:16000])
        finally:
            if launched:
                try:
                    subprocess.run([docker, "rm", "-f", container], capture_output=True, timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if not self.lock.closed:
                self.lock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins-dir", type=Path, default=DEFAULT_PLUGINS)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("build", help="Build the trusted reusable test image")
    cleanup = commands.add_parser("cleanup", help="Remove leftover test containers and optionally reusable test images")
    image_flags = cleanup.add_mutually_exclusive_group()
    image_flags.add_argument("--images", action="store_true", help="Also remove unused app-owned test images")
    image_flags.add_argument("--images-only", action="store_true", help="Remove unused app-owned test images without removing containers")
    cleanup.add_argument("--dry-run", action="store_true", help="List what would be removed without changing Docker resources")
    for action in ("run", "show"):
        command = commands.add_parser(action)
        command.add_argument("tool", help="Folder name under plugins/mcp_tools")
    args = parser.parse_args(argv)
    try:
        if args.action == "build":
            return build_test_image(IMAGE)
        if args.action == "cleanup":
            report = cleanup_resources(remove_containers=not args.images_only, remove_images=args.images or args.images_only,
                                       dry_run=args.dry_run, image=IMAGE)
            print(json.dumps(report, indent=2))
            return 0 if report["status"] == "success" else 1
        report = TestRun(args.plugins_dir, args.tool, "cli").execute() if args.action == "run" else latest_report(args.plugins_dir, args.tool)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "passed" and not report.get("outdated") else (1 if report["status"] == "failed" else 2)
    except (OSError, ValueError, TestBusyError, RuntimeBusyError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
