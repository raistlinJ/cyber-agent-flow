# Sealed case-file artifact study

Use the standalone CAF study to measure whether a playbook, text-processing tool or instruction-only skill improves flag recovery on a ScenarioForge Alderbank case-file handoff. CAF reads the ticket, supplies its first flag to open the sealed notes, and submits a JSON object containing a `flags` array. The host awards one point for each distinct correct flag in a valid final submission, up to two points per session. Incorrect submissions are counted separately.

## Run the study

Use the complete generated instance, which contains the participant files and the host evaluation suite. Set the model and endpoint in a study configuration. For an authenticated endpoint, place the credential in the environment variable named by `model.api_key_env`. The commands below run from the CAF checkout using the [example configuration](../configs/evidence-study.json).

```sh
instance=../scenarioforge/outputs/scenarios-alderbank-case-handoff
config=configs/evidence-study.json
venv/bin/python evidence_study.py "$instance" --config "$config" --plan
venv/bin/python evidence_study.py "$instance" --config "$config" --output runs/alderbank-artifacts
```

A new run needs a new output directory. To continue a matching run, add `--resume` to the second command. From the orchestrator checkout, the following command runs the same CAF implementation.

```sh
.venv/bin/python -m cyber_agent_flow_orchestrator case-artifact-study \
  ../scenarioforge/outputs/scenarios-alderbank-case-handoff \
  --config ../cyber-agent-flow/configs/evidence-study.json --output runs/alderbank-artifacts
```

## Configure the experiment

| Configuration | Effect |
|---|---|
| `candidates.playbook`, `candidates.skill` | Number of Markdown playbooks or agent skills to propose from the baseline evidence. Accepted documents supply guidance in fresh sessions. |
| `candidates.tool` | Number of tools to propose. A tool extracts distinct flag strings or matches input lines against a literal keyword. CAF runs functional fixtures before exposing it to the participant. |
| `candidates.lora_suggestion` | Number of written suggestions for training data, objectives and held-out evaluation. These are advisory documents. Model training is a separate step. |
| `model`, `analysis_model`, `generator_model`, `generation_backend` | Set the participant model and optionally separate analysis and authoring models. Select `model` for model-based authoring or `claude_cli` for [CAF’s Claude CLI generation backend](claude-generation.md). |
| `repetitions`, `seed`, `limits` | Set sessions per condition, the randomized candidate evaluation order, and the turn, time, context and tool budgets. |
| `generation_wall_seconds` | Optional positive integer time budget per artifact proposal. Defaults to the trial wall time. Participant and analyst budgets are configured under `limits`. |
| `keep_top`, `selection` | Set the maximum number of candidates to enable together in the confirmation sessions and the eligibility rule described below. |

Each configured count is a generation opportunity. CAF individually evaluates distinct, accepted playbooks, skills and tools. Two candidates of one type with the same instruction body or tool operation and parameters occupy one evaluation slot. One proposal of each supported type allows at most five participant sessions per repetition, covering baseline, three individual candidates and combined confirmation.

## Interpret the results

CAF ranks individually tested candidates by total flags recovered, then fewer incorrect submissions and candidate ID. Under `improve`, a candidate qualifies only if it recovers more flags than baseline. Under `ranked`, the highest-ranked candidates can qualify even on a tie. CAF freezes up to `keep_top` qualifying artifacts together and starts fresh confirmation sessions. An empty selection repeats baseline.

Use `selection.json` to see which artifacts qualified. `report.json` contains baseline, individual and confirmation counts, trial rows, and the difference in recovered flags between confirmation and baseline. Each stage uses the same frozen case. A claim about transfer to other scenarios requires a separately designed held-out evaluation.

## Review a completed run in CAF

Open **Evidence studies** in the CAF WebUI. Choose **Analyze baseline** on a completed run to read the analyst’s output. Set a proposal count for each artifact type and choose **Generate candidates**. Preview the candidates, enable the ones to evaluate, name the experiment and add it to **Runnable experiments**. Running it produces a fresh baseline and a selected-artifact condition. Existing validated candidates remain available when you request zero new proposals. LoRA suggestions are available to read. Select two or more completed runs and choose **Compare selected runs** to see official flags credited, flag values in the final answer, submission-format validity and incorrect submissions. Older runs can have unavailable metrics.

**Run baseline** starts a new case from a registered profile. **Automatically rank candidates** offers the original individually tested top-N workflow, including a plan preview. Both workflows use the same CAF study functions through the browser, the local CLI and the SSH server.

All users of a CAF instance share its evidence workspace. Register the cases, model configurations and optional completed source runs that should be visible to those users in `eval-inputs/evidence-profiles.json` under the CAF checkout. Relative paths resolve beside that JSON file. For example:

```json
{
  "alderbank": {
    "instance": "../../scenarioforge/outputs/scenarios-alderbank-case-handoff",
    "config": "../configs/evidence-study.json",
    "source": "../../cyber-agent-flow-orchestrator/runs/alderbank-sealed-ripple-artifacts"
  }
}
```

Use the same participant model and trial settings as the source run for a paired comparison. Set `CAF_EVIDENCE_PROFILES` to choose another registry and `CAF_EVIDENCE_WORKSPACE` to override the default private `eval-runs/evidence-workspace` directory. Configure model credentials in the host process environment using the variable names in the registered model config. Registered read-only cases, source runs and saved experiment IDs are the inputs exposed through the interfaces.

```sh
venv/bin/python cli.py artifacts list
venv/bin/python cli.py artifacts analyze source-alderbank
venv/bin/python cli.py artifacts show ANALYSIS_ID
venv/bin/python cli.py artifacts generate ANALYSIS_ID --playbook 1 --tool 2 --skill 1 --lora-suggestion 1
venv/bin/python cli.py artifacts save REVIEW_ID --name "Ticket review" --enable playbook-001
venv/bin/python cli.py artifacts run EXPERIMENT_ID
venv/bin/python cli.py artifacts compare source-alderbank RUN_ID
```

Analysis and generation run in the background. Check the returned ID with `artifacts show` or `artifacts list`. Run `artifacts --help` for the baseline and ranked-study commands. In interactive CLI or SSH chat, enter `/artifacts` to list commands. SSH exec accepts the same `artifacts ...` commands.

The Flask server exposes `GET /api/evidence-studies`, `GET /api/evidence-studies/items/<id>` and `POST /api/evidence-studies/actions/<action>`. Send JSON. Actions are `baseline` (profile), `plan` and `study` (profile, counts, keep_top, selection, repetitions), `analyze` (source run ID), `generate` (analysis ID as source, counts), `save` (review ID as source, enabled IDs, name), `run` (experiment ID as source), and `compare` (ids). Launch actions return a persistent workspace item to poll. Use the Resume button, the `resume` command, or the `resume` action (id) to continue a failed or interrupted job from persisted checkpoints.

For a macOS-hosted CAF process, an operator can bind an existing Keychain generic password to an exact HTTPS model endpoint in the private local file `eval-inputs/evidence-keychain.json`. Each endpoint maps to an object with `variable` (the configured `api_key_env`) and `service` (the Keychain service name). The Keychain account must match the endpoint host and port. The worker uses this binding only when the environment variable is empty and TLS verification is enabled.
