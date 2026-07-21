# CTF Trial Run (Modular Version)

This is a modularized version of the CTF Trial Run — Progressive Disclosure Solver. It simulates a CTF (Capture The Flag) challenge execution and uses Large Language Models to solve them against ScenarioForge attack graphs.

## Installation & Setup

This project uses [`uv`](https://github.com/astral-sh/uv) to manage its dependencies (`pyproject.toml`).

To install dependencies and build the virtual environment:
```bash
uv sync
```

You can start the evaluation dashboard simply by running:
```bash
uv run main.py
```
This automatically defaults to UI Server mode (`--serve`), hosting the dashboard at `http://localhost:8765/` (by default).

## Modes of Operation

### 1. UI Control Center (Default)
Run the background server and control everything from the web browser:
```bash
uv run main.py [--host 0.0.0.0] [--port 8080]
```
- **Shared Environment File**: By default, the app reads and writes `<project-root>/.scenarioforge/.scenarioforge.env`, independent of the directory it is launched from. Override it with `--scenarioforge-env /path/to/.scenarioforge.env` when needed.
- **Live Configuration**: Set and validate CORE's gRPC endpoint plus SSH/remote-venv settings directly from the Web UI. They are saved as ScenarioForge's `CORE_HOST`, `CORE_PORT`, `CORE_SSH_*`, and optional `CORE_VENV_BIN` settings in the selected environment file.
- **Dynamic AI Solvers**: Add one or more solver tabs, then fetch and validate native Anthropic models or OpenAI-compatible/Ollama models independently. The complete solver list is saved in `scenarioforge.solvers.yaml` beside the selected environment file (with owner-only permissions). At least one validated solver is required before a run can start.
- **Side-by-side UI runs**: The first validated solver assists scenario generation; every validated solver then evaluates the same generated scenario.
- **Run controls**: The Run Eval modal configures generation difficulty and loops, simulator turn limit, pass threshold, output directory, artifact-name prefix, and generate/single-replay/directory-replay mode.

### 2. Generate and Solve (CLI-driven)
Generate a new scenario through the ScenarioForge CLI and immediately solve it:
```bash
uv run main.py --generate medium --loop 2 --solver-provider anthropic --solver-model claude-sonnet-4-6
```

For a local Ollama server, no API key or URL is required (it defaults to
`http://localhost:11434/v1`):

```bash
uv run main.py --generate medium --solver-provider ollama --solver-model llama3
```

For vLLM, llama.cpp's OpenAI-compatible server, or another compatible gateway,
provide its `/v1` endpoint and, when required, its key:

```bash
uv run main.py --generate medium \
    --solver-provider openai-compatible --solver-model your-model-id \
    --solver-url http://localhost:8000/v1 --solver-api-key "$PROVIDER_API_KEY"
```

Use `--solver-no-verify-ssl` only for endpoints with a development or
self-signed certificate.

### Comparing Solver Models (Replay Modes)

`--solver-provider2`/`--solver-model2` and the optional third pair add models
to the same evaluation. Each configured solver independently receives the same
scenario and its results are recorded side by side, which is useful for model
comparisons. These extra solver slots apply to `--xml` + `--graph` and
`--solve-dir`; `--generate` uses the primary solver only.

Each additional solver has matching `--solver-api-key2`/`3`,
`--solver-url2`/`3`, and `--solver-no-verify-ssl2`/`3` flags. For example,
compare a hosted Claude model with a local Ollama model:

```bash
uv run main.py --solve-dir /path/to/challenges \
    --solver-provider anthropic --solver-model claude-sonnet-4-6 \
    --solver-provider2 ollama --solver-model2 llama3
```

### 3. Single Solve (Replay Mode)
Run a single, pre-existing challenge against one or more models:
```bash
uv run main.py --xml path/to/scenario.xml --graph path/to/attack_graph.json
```

### 4. Replay Batch
Discover all challenges in a directory and evaluate multiple models:
```bash
uv run main.py \
    --solve-dir /path/to/challenges/directory \
    --solver-provider anthropic --solver-model claude-sonnet-4-6 \
    --solver-provider2 openai --solver-model2 gpt-4o
```

## Architecture

- `main.py`: CLI parser and execution orchestration (the entry point).
- `config.py`: Global constants, default values, and environment/API keys.
- `llm.py`: Interaction with Language Models (Anthropic, OpenAI, HuggingFace, vLLM, Ollama, Custom OpenAI-compatible).
- `simulator.py`: In-memory simulated network node execution and state tracking.
- `generator.py`: Runs ScenarioForge's seeded `new → preview-plan → flag-sequencing → execute --post-execution-validation` pipeline and preserves phase artifacts.
- `simulator.py`: Consumes Attack Graph v2 plus saved Flow/PlanPreview metadata for a model-facing simulation; ScenarioForge execute validation remains the runtime authority.
- `dashboard.py`: HTTP server and API backend for live visualization and configuration.
- `network.py`: Helper proxies for tunneling.
- `utils.py`: Simple data and filesystem helpers.

For integration boundaries, completed glue, and remaining limitations, see [ScenarioForge compatibility findings](SCENARIOFORGE_COMPATIBILITY_FINDINGS.md).
