# Testing generated tools

This runner tests generated MCP tools under `plugins/mcp_tools/`. It does not test
built-in tools. Other generated artifacts use format validation instead.

New MCP tools include `tests/suite.json` and any needed files under `tests/fixtures/`.
Claude Code creates the files in staging, then CyberAgentFlow runs container tests.
Failed assertions are returned to Claude Code for up to two implementation repairs;
the first valid test plan and fixtures remain frozen. Each attempt's report is saved
when the artifact is published. Generation success means validated files were produced;
the separate test status can still be failed or unavailable. Playbooks do not execute
these tests. See [Claude Code generation](claude-generation.md) for inference setup.

## Setup and CLI

Docker must be running on the same machine as the app, with permission to bind-mount
its temporary directories. Build the reusable image once (and rebuild after changes
to `gen_tool_test_env/`):

```sh
python gen-tool_tests.py build
python gen-tool_tests.py run <tool_folder>
python gen-tool_tests.py show <tool_folder>
```

`<tool_folder>` is the directory name under `plugins/mcp_tools/`. Use the project's
virtual environment if needed. The commands print JSON. Exit codes are 0 for a current
pass, 1 for failed assertions, and 2 for unavailable, missing, outdated, or errored tests.
`--plugins-dir /path/to/plugins` can be supplied before `run` or `show`.

The app does not silently install Docker or pull/build an image during generation.
If Docker or the image is unavailable, the result is **Unavailable**, with instructions
to set it up and rerun. Existing tools without a suite remain **Not tested**.

## WebUI

Open **Configuration → Artifacts → MCP Tools**. Each tool has a test status,
**Run Tests**, and **View Results**. Running tests updates automatically without
changing the enabled-tool selection. Results show the environment, image ID, individual
checks, output, failures, and timestamps. **Outdated** means the artifact or its test
files have changed since the report was produced.

If checks fail, choose **Continue with Claude** on the tool or in **View Results**.
The dialog resumes from the original generation prompt, current source, and latest
test results. Send instructions, then click **Test** after the prompt finishes.
You can repeat this cycle; edits preserve the test plan and fixtures. See
[interactive follow-up](claude-generation.md#interactive-follow-up-after-tests-fail)
for context persistence and inference settings.

Reports persist at `plugins/test_results/<tool_folder>/<test_id>.json`, separate from
the generated artifact so regeneration does not erase history. CLI and WebUI use the
same runner, reports, and process lock. A second run for the same tool is rejected while
one is active. An interrupted app/CLI run is shown as a test error when next inspected.

API: `POST /api/plugins/mcp-tools/<tool_folder>/tests` starts a background run;
`GET` on that URL returns the latest report. `GET /api/plugins` includes test summaries.

## Environments and test plans

Both initial templates use Python 3.12 slim with the Python standard library:

- `python-files`: run the tool against bundled fixture files.
- `python-http`: start a local GET-only HTTP fixture server inside the runner container.
  Unknown routes return 404. No host port is exposed.

A plan describes arguments and expected results; it cannot choose a Docker image,
mounts, installation commands, or container privileges. Tests invoke the tool using its
manifest command, `base_args`, and `allow_args`, including the MCP runner's placeholder
semantics. Bundled script paths resolve under `/artifact`; each test gets a writable,
empty temporary working directory. Use `{artifact}` for fixture paths and `{target_url}`
for the HTTP fixture server address.

```json
{
  "version": 1,
  "template": "python-http",
  "http_routes": {
    "/health": {"status": 200, "body": "healthy"}
  },
  "cases": [
    {"name": "launch", "args": ["--help"], "exit_code": 0,
     "stdout_contains": ["usage:"]},
    {"name": "known response", "args": ["{target_url}/health"], "exit_code": 0,
     "stdout_json": {"status": 200, "body": "healthy"}},
    {"name": "missing input", "args": [], "exit_code": 2,
     "stderr_contains": ["required"], "timeout_seconds": 5}
  ]
}
```

Use `stdout_contains`/`stderr_contains` for required substrings, or `stdout_json` for
exact JSON equality. Every case must specify `exit_code` and at least one output
assertion. Plans support 1–12 cases with 1–20 seconds per case (default 10).
Generated tools are asked to include launch, functional, and invalid-input checks.
A complete reference tool and plan are in `tests/fixtures/gen_tool_testing/http_probe/`.

## Execution boundaries and limits

The runner uses an artifact snapshot mounted read-only, no external network, a non-root
user, no Linux capabilities, no new privileges, a read-only root filesystem, and a
64 MiB temporary filesystem. CPU, memory, process count, and execution time are limited.
It does not mount application credentials, the repository, or the Docker socket.
These controls use the standard [Docker run options](https://docs.docker.com/reference/cli/docker/container/run/).
Containers are removed after completion or the outer timeout. Killing the host process
forcibly or stopping Docker can interrupt cleanup; leftover containers have names
starting with `caf-test-`. Inspect those specific containers before removing them.

## Cleaning leftover Docker resources

Open **Configuration → Artifacts → Generated tool test cleanup**. Choose leftover
containers, containers and reusable images, or images only. **Preview cleanup** lists
the proposed removals; **Clean up** applies the selected cleanup. Results show removed,
skipped, and failed resources. Removing the reusable image requires rebuilding it
before another test: `python gen-tool_tests.py build`.

The same cleanup is available from the script:

```sh
python gen-tool_tests.py cleanup                       # Leftover test containers
python gen-tool_tests.py cleanup --images              # Containers and unused test images
python gen-tool_tests.py cleanup --images-only         # Unused images only
python gen-tool_tests.py cleanup --images --dry-run     # Preview without deleting
```

Cleanup prints JSON and exits 0 on success, 1 for partial removal failures, or 2 when
cleanup cannot start (including active tests, another cleanup, or unavailable Docker).
Repeated cleanup is safe. Saved artifacts, test reports, and generated documents are
retained.

New containers and images built with `gen-tool_tests.py build` carry ownership labels for
this user, host, and checkout. Cleanup removes matching stopped, partial, or orphaned
containers, including running orphans left by a crashed worker. Builds and tests hold
a shared activity lock; cleanup requires exclusive access, so active runs cannot be
removed. The guard covers WebUI, CLI, and tests run during generation. Its directory
defaults to `~/.cache/cyber-agent-flow/tool-tests`; if overriding
`CYBER_AGENT_FLOW_TEST_RUNTIME_DIR`, use the same stable value for every app/CLI process.

For older installations, cleanup also recognizes stopped `caf-test-<32 hex digits>`
containers using the legacy default test image. Unlabeled containers that may still be
active are reported as skipped. Images referenced by retained containers, images with
additional/shared tags, and resources belonging to other checkouts are kept. Custom
images are eligible when built through this app's labeled build command. The legacy
default image is recognized by its exact tag and runner entrypoint.

Image cleanup includes labeled unused and dangling test images. It does not run a
global Docker prune or remove shared base images, volumes, or BuildKit caches. A failed
build's unscoped cache is outside this cleanup's scope.

API: `POST /api/plugins/test-runtime/cleanup` accepts boolean `remove_containers`
(default true), `remove_images` (default false), and `dry_run` (default false).
Active test/build/cleanup activity returns HTTP 409; Docker availability errors return
503. Partial removal failures are returned in the result's `errors` list.

Reports record the artifact SHA-256 and the actual image ID. Output is limited to
16,000 characters per stream per case. Artifacts, including fixtures, are limited to
20 MiB and cannot contain symlinks.

A pass proves only the supplied cases in the recorded environment. Generated tests can
share incorrect assumptions with generated code; review their expected results.
Tools requiring additional binaries, Python packages, privileged operations, or full
network labs need a separately maintained environment. Dependencies are not installed
by the generated plan. `CYBER_AGENT_FLOW_TEST_IMAGE` can select an administrator-built
image implementing the same `/runner/runner.py` harness contract. The default templates
are deliberately small; they are not replicas of a complete Kali deployment.

## Developer verification

```sh
python gen-tool_tests.py build
CAF_TEST_DOCKER=1 python -m pytest tests/test_gen_tool_testing.py -q
```

The opt-in Docker tests cover both templates, HTTP responses, wrong expectations,
timeouts, the CLI, read-only artifacts, and blocked external networking. Without
`CAF_TEST_DOCKER=1`, the remaining contract, API, and job-state tests run normally.
