"""Claude Code artifact generation against a configured Anthropic-compatible server."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from generated_artifacts import validate_tool_files, publish_artifact
from gen_tool_tests import TestRun, artifact_files, fingerprint
from gen_tool_test_env.suite import validate_suite
from artifact_catalog import DOCUMENT_KINDS, document_instructions, validate_document_files
from artifact_store import read_document, document_fingerprint

MAX_ATTEMPTS = 3
CLI_TIMEOUT_SECONDS = 600


class GenerationCancelled(Exception):
    pass


def claude_executable():
    override = os.environ.get("CYBER_AGENT_FLOW_CLAUDE_BIN")
    candidates = [override] if override else [shutil.which("claude"), str(Path.home() / ".local/bin/claude")]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.abspath(candidate)
    raise ValueError("Claude Code is not installed. Run ./install_claude.sh or set CYBER_AGENT_FLOW_CLAUDE_BIN.")


def normalize_endpoint(host):
    host = str(host or "").strip().rstrip("/")
    if host.endswith("/v1"):
        host = host[:-3]
    parsed = urlsplit(host)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("A valid Anthropic-compatible server URL is required (for llama.cpp, e.g. http://localhost:8080).")
    return host


def check_cancelled(cancel_check):
    if cancel_check and cancel_check():
        raise GenerationCancelled()


def run_claude(workspace, prompt, host, api_key, model, ssl_verify=True, cancel_check=None, lock_tests=False):
    executable = claude_executable()
    host = normalize_endpoint(host)
    workspace = Path(workspace).resolve()
    check_cancelled(cancel_check)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="caf-claude-config-") as config, tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        # Keep credentials out of arguments, persisted user settings, and generated files.
        inherited = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
        env = {key: os.environ[key] for key in inherited if key in os.environ}
        env.update({"CLAUDE_CONFIG_DIR": config, "ANTHROPIC_BASE_URL": host,
                    "ANTHROPIC_API_KEY": api_key or "local-inference", "ANTHROPIC_AUTH_TOKEN": "",
                    "ANTHROPIC_MODEL": model, "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": model, "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
                    "ANTHROPIC_CUSTOM_MODEL_OPTION": model,
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1"})
        if not ssl_verify:
            env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"
        # Only file edits are exposed. The controller supplies file contents for repairs;
        # generated code, shell commands, network tools, and MCP servers cannot run here.
        settings = {"permissions": {"allow": [f"Edit(/{workspace}/**)"], "deny": []}}
        if lock_tests:
            settings["permissions"]["deny"].append(f"Edit(/{workspace}/tests/**)")
        command = [executable, "--bare", "--print", "--output-format", "json", "--model", model,
                   "--max-turns", "20", "--no-session-persistence", "--setting-sources", "",
                   "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
                   "--tools", "Edit", "--permission-mode", "dontAsk", "--settings", json.dumps(settings)]
        stdin.write(prompt.encode("utf-8"))
        stdin.seek(0)
        process = subprocess.Popen(command, cwd=workspace, env=env, stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            while process.poll() is None:
                check_cancelled(cancel_check)
                if time.monotonic() - started > CLI_TIMEOUT_SECONDS:
                    raise TimeoutError("Claude Code generation exceeded its 10-minute attempt limit.")
                if stdout.tell() + stderr.tell() > 8 * 1024 * 1024:
                    raise ValueError("Claude Code exceeded the generation log limit.")
                time.sleep(0.2)
            check_cancelled(cancel_check)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        stdout.seek(0)
        stderr.seek(0)
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(output)
        except ValueError as exc:
            detail = (error or output)[-1500:]
            if api_key:
                detail = detail.replace(api_key, "[redacted]")
            raise ValueError(f"Claude Code returned invalid output: {detail}") from exc
        if not isinstance(result, dict):
            raise ValueError("Claude Code returned an invalid result record.")
        if process.returncode or result.get("is_error"):
            detail = str(result.get("result") or result.get("errors") or error or result.get("subtype"))[-1500:]
            if api_key:
                detail = detail.replace(api_key, "[redacted]")
            raise ValueError(f"Claude Code generation failed: {detail}")
        response = str(result.get("result") or "Files updated.")[:16000]
        if api_key:
            response = response.replace(api_key, "[redacted]")
        return {"duration_seconds": round(time.monotonic() - started, 2), "num_turns": result.get("num_turns"),
                "session_id": result.get("session_id"), "subtype": result.get("subtype"), "response": response}


def refine_artifact(target_path, messages, report, expected_sha256, host, api_key, model,
                    ssl_verify=True, cancel_check=None, kind="mcp_tool"):
    """Apply one user-directed turn; leave execution to the user's Test action."""
    target = Path(target_path)

    def before_publish():
        check_cancelled(cancel_check)
        current_sha = document_fingerprint(target, kind) if kind in DOCUMENT_KINDS else fingerprint(target)
        if current_sha != expected_sha256:
            raise ValueError("Artifact changed during this prompt. Reopen the conversation and try again.")

    before_publish()
    original = read_document(target, kind) if kind in DOCUMENT_KINDS else read_generated_files(target)
    if kind == "mcp_tool":
        if "tests/suite.json" not in original:
            raise ValueError("Interactive repair requires an existing tests/suite.json.")
        validate_suite(json.loads(original["tests/suite.json"]))
    frozen = {name: content for name, content in original.items() if kind == "mcp_tool" and name.startswith("tests/")}
    prompt = json.dumps({"conversation": messages, "latest_test_report": report, "previous_files": original}, indent=2)
    if len(prompt) > 400000:
        raise ValueError("Artifact and conversation are too large for an interactive repair.")
    prompt += (
        "\nContinue this artifact's generation using the user's latest instructions. "
        "When making changes, recreate ALL implementation files, including manifest.json, in the current workspace using Edit, "
        "with old_string empty and new_string containing the full file. The previous implementation is provided above. "
        "The original tests and fixtures are already present and frozen: do not alter, remove, or bypass them. "
        "Do not create configuration files, CLAUDE.md, or provenance files. Do not run code or commands. "
        "The user will run tests separately. If answering a question without making changes, leave the implementation "
        "files absent and just answer. Finish with a short explanation of your changes or your answer."
    )
    if kind in DOCUMENT_KINDS:
        prompt = json.dumps({"conversation": messages, "latest_validation": report, "previous_files": original}, indent=2) + (
            "\nContinue using the user's instructions. If changing the artifact, recreate ALL its files using Edit "
            "with old_string empty and new_string containing full text. If only answering a question, create no files. "
            "Do not run code or create configuration/provenance files. Finish with a short explanation.\n"
        ) + document_instructions(kind, target.stem if kind == "playbook" else target.name)
    with tempfile.TemporaryDirectory(prefix="caf-refine-") as temporary:
        workspace = Path(temporary).resolve()
        for name, content in frozen.items():
            path = workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        result = run_claude(workspace, prompt, host, api_key, model, ssl_verify, cancel_check, lock_tests=kind == "mcp_tool")
        files = read_generated_files(workspace)
        if {name: content for name, content in files.items() if name.startswith("tests/")} != frozen:
            raise ValueError("Repair attempted to modify the frozen test plan or fixtures.")
        if set(files) == set(frozen):
            before_publish()
            result["response"] = (result.get("response") or "Prompt completed.") + "\n\nNo files were changed."
            return {"backend": "claude_cli", **result}
        files = (validate_document_files(kind, files, target.stem if kind == "playbook" else target.name)
                 if kind in DOCUMENT_KINDS else validate_tool_files(files, require_tests=True))
        provenance = target / "PROVENANCE.md"
        if kind != "playbook" and provenance.is_file():
            files["PROVENANCE.md"] = provenance.read_text(encoding="utf-8")
        publish_artifact(str(target), files, single_file=kind == "playbook", before_publish=before_publish)
        return {"backend": "claude_cli", **result}


def read_generated_files(workspace):
    files = {}
    for path in artifact_files(Path(workspace)):
        relative = path.relative_to(workspace).as_posix()
        if relative == "CLAUDE.md" or ".claude" in Path(relative).parts:
            raise ValueError("Generation must not create Claude configuration files.")
        files[relative] = path.read_text(encoding="utf-8")
    return files


def generate_artifact(kind, target_path, messages, host, api_key, model, ssl_verify=True, cancel_check=None, progress_callback=None):
    """Generate, validate, and test in staging; publish only after the worker finishes."""
    host = normalize_endpoint(host)
    claude_executable()
    trace = []
    reports = []
    frozen_tests = None

    def progress(message):
        check_cancelled(cancel_check)
        if progress_callback:
            progress_callback(message)

    with tempfile.TemporaryDirectory(prefix="caf-generation-") as temporary:
        staging = Path(temporary).resolve()
        workspace = staging / "mcp_tools" / "artifact"
        workspace.mkdir(parents=True)
        specification = "\n\n".join(str(message.get("content", "")) for message in messages)
        prompt = specification + (
            "\n\nUse the Edit tool to create actual files in the current workspace. "
            "To create a file, set old_string to an empty string and new_string to the complete contents. "
            "Do not return file blocks in your answer. Do not run code or commands. "
            "Our controller validates files and runs container tests separately. "
            "Do not create configuration files, CLAUDE.md, or provenance files. "
            + (document_instructions(kind, Path(target_path).stem if kind == "playbook" else Path(target_path).name)
               if kind in DOCUMENT_KINDS else "Write manifest.json, implementation files, tests/suite.json, and fixtures.")
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            progress(f"Claude Code is {'generating' if attempt == 1 else 'repairing'} files with {model} (attempt {attempt}/{MAX_ATTEMPTS})")
            details = run_claude(workspace, prompt, host, api_key, model, ssl_verify, cancel_check, lock_tests=frozen_tests is not None)
            trace.append({"attempt": attempt, **details})
            try:
                files = read_generated_files(workspace)
                if frozen_tests is not None and {name: text for name, text in files.items() if name.startswith("tests/")} != frozen_tests:
                    raise ValueError("Repair attempted to modify the frozen test plan or fixtures.")
                if kind in DOCUMENT_KINDS:
                    files = validate_document_files(kind, files, Path(target_path).stem if kind == "playbook" else Path(target_path).name)
                    break
                files = validate_tool_files(files, require_tests=True)
                # Apply normalized manifest fields before testing the exact files to publish.
                (workspace / "manifest.json").write_text(files["manifest.json"], encoding="utf-8")
                frozen_tests = {name: text for name, text in files.items() if name.startswith("tests/")}
                progress(f"Running container tests for attempt {attempt}/{MAX_ATTEMPTS}")
                report = TestRun(staging, "artifact", "generation").execute(cancel_check=cancel_check)
                check_cancelled(cancel_check)
                reports.append(report)
                trace[-1]["test_status"] = report["status"]
                if report["status"] != "failed" or attempt == MAX_ATTEMPTS:
                    break
                feedback = "Container test failures:\n" + json.dumps(report["cases"], indent=2)[:30000]
            except ValueError as exc:
                trace[-1]["validation_error"] = str(exc)
                if frozen_tests is not None and "frozen test" in str(exc):
                    raise
                if attempt == MAX_ATTEMPTS:
                    raise
                feedback = "Validation failed: " + str(exc)
            current_files = read_generated_files(workspace)
            contents = json.dumps(current_files, indent=2)
            if len(contents) > 200000:
                raise ValueError("Generated source is too large for automatic repair.")
            # Bare mode offers Edit, but changing existing files in a fresh CLI
            # session requires Read. Supply prior contents explicitly and recreate
            # implementation files instead of granting unrestricted filesystem reads.
            for name in current_files:
                if frozen_tests is None or not name.startswith("tests/"):
                    (workspace / name).unlink()
            prompt = specification + "\n\n" + feedback + (
                "\n\nRepair and recreate ALL implementation files, including manifest.json, using Edit "
                "with old_string set to an empty string and new_string set to the complete contents. "
                "The controller removed the previous implementation files so you can recreate them. "
            )
            if frozen_tests is not None:
                prompt += "The tests and fixtures are frozen: do not change, remove, or bypass them. "
            prompt += "Do not run code. Previous file contents for reference:\n" + contents
            if kind in DOCUMENT_KINDS:
                prompt += "\nRecreate the document files; no tool manifest or tests are needed.\n" + document_instructions(
                    kind, Path(target_path).stem if kind == "playbook" else Path(target_path).name)
        progress("Publishing validated artifact files")
        publish_artifact(target_path, files, single_file=(kind == "playbook"), before_publish=lambda: check_cancelled(cancel_check))
        return {"backend": "claude_cli", "attempts": trace, "test_reports": reports}
