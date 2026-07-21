# ScenarioForge Compatibility Findings

## Purpose and scope

This note records the gap assessment for `scenarioforge-da` (SF-DA) as a
consumer of ScenarioForge-generated challenge data. It is intentionally focused
on limitations that existed in SF-DA, rather than requesting changes to
ScenarioForge.

The integration boundary is a saved Scenario XML plus an Attack Graph JSON
export. The current ScenarioForge contract is Attack Graph v2. Its ordered path
is `chain_order`/`edges`; generator provenance is in each node's `generator`
object; and non-adjacent fact prerequisites are in `fact_dependencies`.

## Connection glue now in place

SF-DA can now reliably consume the current export contract:

| Capability | Current behavior |
|---|---|
| Contract validation | Loads `attack_graph_v2.schema.json` from the sibling ScenarioForge checkout, or from `SCENARIOFORGE_ATTACK_GRAPH_SCHEMA`. Invalid or stale graphs fail before solving. |
| Ordered attack path | Uses `chain_order` as the canonical root and sequence instead of deriving a root from an unordered set of graph nodes. |
| Resolved addressing | Uses each graph node's exported `ipv4`; only absent addresses use the old deterministic simulation fallback. |
| Optional assignments | Handles `generator: null` without crashing. |
| Runtime pipeline | Runs the documented seeded `new → preview-plan → flag-sequencing → execute --post-execution-validation` pipeline and preserves each phase's JSON and log artifacts. |
| Runtime acceptance | Requires `CORE_SESSION_ID` and a successful `VALIDATION_SUMMARY_JSON` before treating generation as successful. |
| Core target | Saves and validates the same CORE gRPC (`CORE_HOST`/`CORE_PORT`) plus SSH (`CORE_SSH_*`) and optional remote venv (`CORE_VENV_BIN`) connection contract used by ScenarioForge CLI/Web UI execution. |
| Solver settings | Stores dashboard solver provider, model, endpoint, TLS, label, and key values in a dedicated `scenarioforge.solvers.yaml` file beside the selected environment file. |

These changes make SF-DA a safer client of the latest ScenarioForge output and
make ScenarioForge execute validation the runtime authority. The simulator is
still a model-facing abstraction, not a replacement for the running CORE
scenario.

## What SF-DA could not do before this work

### 1. Verify that an input graph was compatible

SF-DA previously accepted any JSON document containing `nodes` and `edges`.
It had no schema-version check and no validation that the graph path matched
the intended ordered chain. As a result, a stale export, an incomplete graph,
or a graph with a different interpretation of edges could be silently treated
as a solvable challenge.

The previous root selection also used a Python set. When more than one root was
possible, the selected starting node was nondeterministic.

### 2. Preserve ScenarioForge-resolved network addressing

The simulator previously ignored exported IPv4 addresses and manufactured
addresses from labels and broad node-type buckets. That could differ from the
saved preview's address plan and caused the simulator, dashboard, and model
prompt to describe a network that was not the exported scenario.

### 3. Safely consume optional generator assignments

ScenarioForge correctly represents an unassigned node as `generator: null`.
SF-DA assumed a mapping and called generator methods directly, which could
raise an exception while building the simulator or dashboard.

## Remaining SF-DA limitations

These are SF-DA product limitations, not ScenarioForge contract defects.

| Priority | Limitation | Evidence in SF-DA | Impact |
|---|---|---|---|
| Medium | The simulator is not a real interactive CORE client. | `simulator.py` exposes generic resolved Flow artifacts and facts through shell-like responses. | Generator-specific binaries, web applications, authentication, and exploits are represented as safe abstractions; the real execute validation is the authoritative runtime check. |
| Medium | Segmentation is preserved but not enforced as firewall policy. | `PlanPreview` switch peers and segmentation metadata are loaded, while command routing does not evaluate each generated firewall/NAT rule. | A solver may see a topology peer that a live segmentation rule would deny; use ScenarioForge execute output for policy-sensitive evaluation. |
| Low | Generator-specific UI hints and access instructions are not rendered verbatim. | The simulator consumes resolved paths, facts, outputs, kind, source, catalog, and Flow assignments, but not every display-only hint template. | This avoids coupling the solver protocol to presentation text while retaining the execution-relevant values. |

## Interpretation of flag-generator support

SF-DA accepts both `flag-generator` and `flag-node-generator` nodes. It uses
their identifier, kind, source, catalog, resolved inputs/outputs, Flow artifact
paths, and fact dependencies to create generic discoverable artifacts and gate
pivots on acquired facts. The actual generator runtime remains ScenarioForge
execute rather than a reimplementation inside SF-DA.

## Recommended follow-on work in SF-DA

1. Add optional generator adapters for high-value catalogs when their exact
   interactive behavior matters to a solver benchmark.
2. Evaluate saved segmentation rules during simulated routing when the
   benchmark requires live-policy parity.
3. Export a redacted, structured execute report for downstream dashboards and
   batch analytics.

## Acceptance criteria for the connection layer

The connection layer should be considered complete when SF-DA can: validate an
Attack Graph v2 export; follow its exact ordered path; retain exported node
addresses; tolerate unassigned nodes; and report an actionable error when a
graph is not compatible. Those criteria are now covered by
`test_attack_graph.py`.
