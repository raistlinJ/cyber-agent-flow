# Artifact generation with Claude Code

The Generate action uses the native `claude` CLI to create tools and playbooks from
analysis scaffolding and analyst notes. It sends inference requests to the endpoint
and model selected in the generation dialog. Session analysis still uses the app's
existing inference clients.

The type picker also supports Markdown documents, skills, RAG documents, templates,
and structured JSON. See [generated artifact formats](generated-artifacts.md) for their
contracts, validation, library controls, and storage locations.

## Installation

`install_prerequisites.sh` installs/verifies Claude Code. On Linux, when invoked with
sudo, it installs the CLI for `SUDO_USER`. On macOS, run without sudo.
`start_ws.sh --build` and first-time startup also install/verify it.

For an existing app installation:

```sh
./install_claude.sh
./install_claude.sh --check
```

The helper uses Anthropic's [native installer](https://code.claude.com/docs/en/setup)
and checks the required CLI flags. It reuses a compatible installation; npm and Node
are not required. Run `./install_claude.sh --update` to explicitly update. Set
`CYBER_AGENT_FLOW_CLAUDE_VERSION` to a specific release to pin a new installation;
the default channel is `stable`. The adapter was exercised with Claude Code 2.1.140.
`CYBER_AGENT_FLOW_CLAUDE_BIN` can specify an absolute executable path for both the app
and installer. Otherwise the app searches PATH and `~/.local/bin/claude`.

## Your models through llama.cpp

Use a llama-server build that supports `/v1/messages`, streaming, and tool calls.
Current upstream exposes an [Anthropic Messages API](https://github.com/ggml-org/llama.cpp/tree/master/tools/server#post-v1messages).
Older builds with only OpenAI chat completions need an upgrade or a compatible gateway.
Your model and its chat template must support tool use; see llama.cpp's
[function-calling guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md).

For example, with your own compatible GGUF:

```sh
llama-server -m /path/to/your-model.gguf --alias artifact-model --jinja \
  --host 127.0.0.1 --port 8080
```

In **Recommendations → Generate**, choose **llama.cpp / Anthropic-compatible gateway**,
enter `http://localhost:8080`, click **Fetch Models**, and select `artifact-model`.
Use the hostname reachable from the Flask server if inference runs elsewhere.
Leave the API key blank for an unauthenticated local server, or supply its configured
key. The adapter accepts a trailing `/v1` and removes it for Claude Code.

Model discovery uses `/v1/models` for this selection. Generation always uses the
Anthropic Messages protocol, even though the API's legacy provider value is `openai`.
Ollama must likewise expose a compatible Messages API. A gateway that only implements
`/v1/chat/completions` is insufficient. Model names are passed explicitly to the CLI,
including its default model aliases; the app does not configure a cloud fallback.
No Claude cloud login is needed to use your local endpoint. The CLI's gateway
configuration follows the [Claude Code gateway documentation](https://code.claude.com/docs/en/llm-gateway).

## Generation and tests

1. Claude Code creates files in a temporary workspace using its Edit tool. The process
   runs in bare mode with a temporary configuration, no inherited API credentials,
   no user/project settings, no MCP servers, and no shell or network tools.
2. The controller validates file paths, manifest, Python syntax, and test plan.
3. MCP tools run in the trusted test container. On failed assertions, the controller
   supplies results and previous source to another CLI attempt. Implementation files
   are recreated; the first valid test plan and fixtures stay frozen. There are at
   most three generation attempts, each limited to 20 CLI turns and 10 minutes.
4. Validated files are published to `plugins/mcp_tools/<name>/` or
   `plugins/playbooks/<name>.md`. Playbooks receive file validation only.

Prepare the container once with `venv/bin/python gen-tool_tests.py build` while Docker is
running. Missing Docker/image produces an unavailable test result, without repeated
repair attempts. Exhausted failing tests remain marked failed; successful file
generation does not imply passing tests. Tools are enabled separately in Configuration.
See [tool testing](generated-tool-testing.md) for CLI reruns, UI controls, and environment limits.

Generation records at `runs/<run_id>/plugin_jobs/<job_id>.json` include the backend,
model, per-attempt metadata, and final test ID. Test reports for completed generation
attempts live at `plugins/test_results/<name>/<test_id>.json`. API keys are passed in
the child process environment, not command arguments or job records. Cancellation
stops the active CLI process or container test; unpublished staging files are discarded.

## Interactive follow-up after tests fail

In **Configuration → Artifacts → MCP Tools**, click **Continue with Claude**
on the tool, or open **View Results** and choose **Continue with Claude** there.
The dialog shows the original generation prompt, latest test report, and saved
conversation. Enter instructions or ask a question, then choose **Send prompt**.
The inference URL and model start with the generation job's settings; enter the API
key again if your server requires one. Keys are not saved in conversation records.

Each turn includes the original requirements, prior user/assistant messages, current
source, and latest test results. The app reconstructs this context for a fresh CLI
process; it does not depend on Claude's local session history. Older generated tools
use their saved `CLAUDE_PROMPT.md` if the generation job predates prompt recording.

An edit is validated in staging and then published. Test plans and fixtures remain
frozen. Failed or canceled edits preserve the existing tool. Answers without edits
are retained in the conversation and clearly marked as changing no files.

**Test** is disabled while a prompt is running and becomes available after a successful
turn. Click it to run the shared container tests; follow-up prompts do not start tests
automatically. The dialog refreshes test results as they finish. Repeat **Send prompt →
Test** as needed. Closing and reopening the dialog restores the history and active
job. An interrupted app process is shown as a failed prompt that can be retried.

Conversation turns are stored alongside generation jobs in
`runs/<run_id>/plugin_jobs/`, linked by `root_job_id`. API clients can use
`GET /api/plugins/mcp-tools/<name>/conversation` to fetch context and
`POST` there with `prompt`, `revision`, `artifact_sha256`, and optional inference
settings to start a turn. `revision` and `artifact_sha256` come from the GET response
and prevent submitting stale context. Tests retain the existing `/tests` endpoint.

## Developer verification

```sh
./install_claude.sh --check
CAF_TEST_CLAUDE=1 CAF_TEST_DOCKER=1 venv/bin/python -m pytest tests -q
node --test tests/js/plugin-repair.test.cjs
```

The optional native tests run the installed CLI against a local scripted Messages
endpoint. They check model routing, file permissions, frozen tests, and a failed Docker
test followed by repair and publication. They do not measure a real model's ability to
generate useful code. Without these flags, the external-runtime tests are skipped.
