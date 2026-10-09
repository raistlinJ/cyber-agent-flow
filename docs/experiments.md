# Evaluation moved to cyber-agent-flow-eval

The evaluator now lives in the separate sibling project **cyber-agent-flow-eval**.
CAF retains the shared engine/tools and its interactive artifact generation/testing.

- [Evaluator installation and engine configuration](../../cyber-agent-flow-eval/README.md)
- [Evaluation YAML and dataset contract](../../cyber-agent-flow-eval/docs/experiments.md)
- [Generate → test → freeze → evaluate](../../cyber-agent-flow-eval/docs/artifact-evaluation-workflow.md)

Use the installed `cyber-agent-flow-eval` command or `python -m cyber_agent_flow_eval`
from the evaluator environment. The former `python -m experiments` command was removed
from CAF. Add `engine.path` (CAF checkout) and optionally `engine.python` (CAF interpreter)
to migrated YAML files; move/rebase catalog and guidance paths and start a new run output.

## Challenge rubrics and evidence IDs

Evaluator-managed tasks can include a public challenge rubric and evidence-report
scaffold. Exact checks, an independent evidence-reading judge, or both establish
completion. Outcomes distinguish success, partial completion, failure and missing
verification. This is configured in the separate evaluator/orchestrator; CAF's
standalone sessions and tool workflows require neither application.

Native tool-call JSON/events now include a stable `evidence_id` and full-output
SHA-256. Large output points to its saved artifact. Continuing a session preserves
prior evidence IDs/files, and the agent can cite these IDs in its report. IDs and
hashes identify recorded observations; an agent's claim alone is not proof of
completion. See the [rubric and study guide](../../cyber-agent-flow-orchestrator/docs/rubric-experiments.md).
