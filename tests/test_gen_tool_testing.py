import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import gen_tool_tests
from gen_tool_test_env.suite import validate_suite


@pytest.fixture
def plugin(tmp_path):
    root = tmp_path / "plugins"
    target = root / "mcp_tools" / "http_probe"
    shutil.copytree(Path(__file__).parent / "fixtures/gen_tool_testing/http_probe", target)
    return root, target


def test_report_lock_and_outdated_detection(plugin):
    root, target = plugin
    run = gen_tool_tests.TestRun(root, "http_probe")
    assert gen_tool_tests.latest_report(root, "http_probe")["status"] == "running"
    with pytest.raises(gen_tool_tests.TestBusyError):
        gen_tool_tests.TestRun(root, "http_probe")
    run.finish("passed", cases=[{"name": "sample", "status": "passed"}])
    assert not gen_tool_tests.latest_report(root, "http_probe")["outdated"]
    (target / "probe.py").write_text("changed")
    assert gen_tool_tests.latest_report(root, "http_probe")["outdated"]


def test_interrupted_worker_is_not_shown_running_forever(plugin):
    root, _ = plugin
    run = gen_tool_tests.TestRun(root, "http_probe")
    run.lock.close()
    assert gen_tool_tests.latest_report(root, "http_probe")["status"] == "error"


def test_missing_docker_reports_blocked(plugin, monkeypatch):
    root, _ = plugin
    monkeypatch.setattr(gen_tool_tests.shutil, "which", lambda _: None)
    report = gen_tool_tests.TestRun(root, "http_probe").execute()
    assert report["status"] == "blocked"
    assert "Docker" in report["message"]


def test_legacy_tool_without_suite_is_not_a_pass(plugin):
    root, target = plugin
    (target / "tests/suite.json").unlink()
    assert gen_tool_tests.TestRun(root, "http_probe").execute()["status"] == "not_tested"


def test_rejects_symlinked_artifacts(plugin, tmp_path):
    root, target = plugin
    (target / "external").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlinks"):
        gen_tool_tests.TestRun(root, "http_probe")


@pytest.mark.parametrize("change", [
    {"template": "arbitrary-dockerfile"},
    {"cases": []},
    {"cases": [{"name": "empty", "args": [], "exit_code": 0}]},
    {"cases": [{"name": "hang", "args": [], "exit_code": 0, "stdout_contains": ["ok"], "timeout_seconds": 999}]},
])
def test_rejects_invalid_test_contract(change):
    plan = {"version": 1, "template": "python-files", "cases": [{"name": "check", "args": [], "exit_code": 0, "stdout_contains": ["ok"]}]}
    with pytest.raises(ValueError):
        validate_suite({**plan, **change})


def test_container_deadline_cleans_up_and_retains_report(plugin, monkeypatch):
    root, _ = plugin
    calls = []
    monkeypatch.setattr(gen_tool_tests.shutil, "which", lambda _: "/bin/docker")

    def command(args, **kwargs):
        calls.append(args)
        if args[1] == "image":
            return subprocess.CompletedProcess(args, 0, "sha256:fixture\n", "")
        if args[1] == "run":
            assert "--network=none" in args
            assert "--read-only" in args
            assert "--cap-drop=ALL" in args
            raise subprocess.TimeoutExpired(args, 270)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(gen_tool_tests.subprocess, "run", command)
    report = gen_tool_tests.TestRun(root, "http_probe").execute()
    assert report["status"] == "error"
    assert calls[-1][1:3] == ["rm", "-f"]
    assert gen_tool_tests.latest_report(root, "http_probe")["status"] == "error"


def test_api_start_and_read_results(plugin, monkeypatch):
    import app
    root, _ = plugin
    monkeypatch.setattr(app, "PLUGINS_DIR", str(root))
    monkeypatch.setattr(gen_tool_tests.shutil, "which", lambda _: None)

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            self.target()

    monkeypatch.setattr(app.threading, "Thread", ImmediateThread)
    client = app.app.test_client()
    response = client.post("/api/plugins/mcp-tools/http_probe/tests")
    assert response.status_code == 202
    assert response.get_json()["trigger"] == "webui"
    assert client.get("/api/plugins/mcp-tools/http_probe/tests").get_json()["status"] == "blocked"
    assert client.post("/api/plugins/mcp-tools/../tests").status_code == 400
    plugins = client.get("/api/plugins").get_json()
    assert plugins["mcp_tools"][0]["test_report"]["status"] == "blocked"


def test_generation_starts_tests_without_changing_generation_success(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(app, "_plugin_jobs", {})
    monkeypatch.setattr(app, "_perform_plugin_generation", lambda *a, **k: None)
    monkeypatch.setattr(app, "_write_plugin_provenance", lambda *a, **k: None)
    started = []
    def start(name, trigger):
        started.append((name, trigger))
        return {"test_id": "test123"}
    monkeypatch.setattr(app, "_start_plugin_tests", start)
    app._plugin_job_wrapper("job1", "run1", "mcp_tool", "probe", str(tmp_path / "probe"), "Probe", [{"content": "prompt"}], "openai", "http://test", None, "test", True)
    assert started == [("probe", "generation")]
    assert app._plugin_jobs["job1"]["status"] == "success"
    assert app._plugin_jobs["job1"]["test_id"] == "test123"


@pytest.mark.skipif(os.environ.get("CAF_TEST_DOCKER") != "1", reason="Set CAF_TEST_DOCKER=1 after building the test image")
def test_real_container_http_fixture_and_failure_paths(plugin):
    root, target = plugin
    report = gen_tool_tests.TestRun(root, "http_probe").execute()
    assert report["status"] == "passed", report
    assert len(report["cases"]) == 4
    assert report["image_id"].startswith("sha256:")
    suite = json.loads((target / "tests/suite.json").read_text())
    suite["cases"][1]["stdout_json"]["body"] = "wrong expectation"
    (target / "tests/suite.json").write_text(json.dumps(suite))
    assert gen_tool_tests.latest_report(root, "http_probe")["outdated"]
    failed = gen_tool_tests.TestRun(root, "http_probe").execute()
    assert failed["status"] == "failed"
    assert failed["cases"][1]["failures"] == ["stdout JSON did not match"]
    (target / "probe.py").write_text("import time; time.sleep(60)")
    suite["cases"] = [{"name": "deadline", "args": [], "exit_code": 0, "stdout_contains": ["ok"], "timeout_seconds": 1}]
    (target / "tests/suite.json").write_text(json.dumps(suite))
    timed_out = gen_tool_tests.TestRun(root, "http_probe").execute()
    assert timed_out["status"] == "failed"
    assert timed_out["cases"][0]["timed_out"] is True


@pytest.mark.skipif(os.environ.get("CAF_TEST_DOCKER") != "1", reason="Set CAF_TEST_DOCKER=1 after building the test image")
def test_real_cli_file_fixtures_and_isolation(plugin):
    import sys
    root, target = plugin
    fixture = target / "tests/fixtures/input.txt"
    fixture.parent.mkdir()
    fixture.write_text("sample")
    (target / "probe.py").write_text('''import json, socket, sys
from pathlib import Path
read_only = False
try:
    Path("/artifact/should-not-exist").write_text("changed")
except OSError:
    read_only = True
blocked = False
try:
    with socket.create_connection(("198.51.100.1", 80), timeout=0.2):
        pass
except OSError:
    blocked = True
Path("scratch.txt").write_text("temporary")
print(json.dumps({"fixture": Path(sys.argv[1]).read_text(), "read_only": read_only, "external_network_blocked": blocked}))
''')
    suite = {"version": 1, "template": "python-files", "cases": [
        {"name": "file fixture and isolation", "args": ["{artifact}/tests/fixtures/input.txt"], "exit_code": 0,
         "stdout_json": {"fixture": "sample", "read_only": True, "external_network_blocked": True}}
    ]}
    (target / "tests/suite.json").write_text(json.dumps(suite))
    command = [sys.executable, str(gen_tool_tests.ROOT / "gen-tool_tests.py"), "--plugins-dir", str(root)]
    result = subprocess.run([*command, "run", "http_probe"], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["trigger"] == "cli"
    assert report["status"] == "passed"
    shown = subprocess.run([*command, "show", "http_probe"], capture_output=True, text=True, timeout=10)
    assert shown.returncode == 0
    assert json.loads(shown.stdout)["test_id"] == report["test_id"]
    assert not (target / "scratch.txt").exists()
    assert not (target / "should-not-exist").exists()
