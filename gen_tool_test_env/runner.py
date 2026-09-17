"""Trusted container harness. Never run this directly against untrusted host tools."""
import http.server
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import threading
import time

from suite import load_suite

ARTIFACT = Path("/artifact")
OUTPUT_LIMIT = 16000


def main():
    suite = load_suite(ARTIFACT / "tests/suite.json")
    manifest = json.loads((ARTIFACT / "manifest.json").read_text())
    server = None
    target_url = ""
    if suite["template"] == "python-http":
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                route = suite["http_routes"].get(self.path, {"status": 404, "body": "not found"})
                body = route.get("body", "").encode()
                self.send_response(route.get("status", 200))
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        target_url = f"http://127.0.0.1:{server.server_port}"

    def expand(value):
        return value.replace("{artifact}", str(ARTIFACT)).replace("{target_url}", target_url)

    def bundled(value):
        path = ARTIFACT / value
        return str(path) if path.is_file() else value

    results = []
    try:
        for case in suite["cases"]:
            started = time.monotonic()
            args = [expand(arg) for arg in case["args"]]
            base_args = manifest.get("base_args", manifest.get("args", []))
            command = [bundled(manifest["command"])]
            # Match the MCP runner's placeholder behavior and allow_args semantics.
            has_args = any("{args}" in arg for arg in base_args)
            command += [bundled(expand(arg.replace("{args}", shlex.join(args)).replace("{timeout}", str(case.get("timeout_seconds", 10))))) for arg in base_args]
            if not has_args and manifest.get("allow_args", False):
                command += args
            failures = []
            timed_out = False
            exit_code = None
            with tempfile.TemporaryDirectory() as work, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                try:
                    process = subprocess.Popen(command, cwd=work, stdout=stdout, stderr=stderr, start_new_session=True,
                                               env={"PATH": os.environ["PATH"], "HOME": work, "TMPDIR": work, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
                    try:
                        exit_code = process.wait(timeout=case.get("timeout_seconds", 10))
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        failures.append("Timed out")
                    finally:
                        # Also remove background descendants after a successful parent exit.
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                except OSError as exc:
                    failures.append(str(exc))
                stdout.seek(0)
                stderr.seek(0)
                out = stdout.read(OUTPUT_LIMIT + 1).decode("utf-8", errors="replace")
                err = stderr.read(OUTPUT_LIMIT + 1).decode("utf-8", errors="replace")
            if exit_code != case["exit_code"]:
                failures.append(f"Expected exit {case['exit_code']}; got {exit_code}")
            for key, value in (("stdout_contains", out), ("stderr_contains", err)):
                for expected in case.get(key, []):
                    if expected not in value:
                        failures.append(f"{key}: missing {expected!r}")
            if "stdout_json" in case:
                try:
                    if json.loads(out) != case["stdout_json"]:
                        failures.append("stdout JSON did not match")
                except ValueError:
                    failures.append("stdout was not valid JSON")
            results.append({"name": case["name"], "status": "failed" if failures else "passed", "exit_code": exit_code,
                            "timed_out": timed_out, "duration_seconds": round(time.monotonic() - started, 3),
                            "stdout": out[:OUTPUT_LIMIT], "stderr": err[:OUTPUT_LIMIT],
                            "output_truncated": len(out) > OUTPUT_LIMIT or len(err) > OUTPUT_LIMIT, "failures": failures})
    finally:
        if server:
            server.shutdown()
            server.server_close()
    print(json.dumps({"status": "passed" if all(case["status"] == "passed" for case in results) else "failed", "cases": results}))


if __name__ == "__main__":
    main()
