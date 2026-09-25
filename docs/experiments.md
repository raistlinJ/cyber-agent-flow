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
