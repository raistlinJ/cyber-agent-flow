"""ScenarioForge Attack Graph v2 loading and compatibility helpers."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


SCHEMA_VERSION = 2
_PROJECT_DIR = Path(__file__).resolve().parent
_DEFAULT_SCHEMA_PATH = (
    _PROJECT_DIR.parent.parent
    / "scenarioforge"
    / "schemas"
    / "attack_graph"
    / "attack_graph_v2.schema.json"
)


def schema_path() -> Path:
    """Return the v2 contract path, allowing non-sibling checkouts to override it."""
    configured = os.environ.get("SCENARIOFORGE_ATTACK_GRAPH_SCHEMA", "").strip()
    return Path(configured).expanduser() if configured else _DEFAULT_SCHEMA_PATH


def _format_error(error: Any) -> str:
    location = ".".join(str(item) for item in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def validate_attack_graph(graph: Any) -> dict[str, Any]:
    """Validate a v2 export and the path invariants the schema cannot express."""
    path = schema_path()
    if not path.is_file():
        raise ValueError(
            "ScenarioForge Attack Graph v2 schema was not found at "
            f"{path}. Set SCENARIOFORGE_ATTACK_GRAPH_SCHEMA to the schema file."
        )

    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load Attack Graph schema at {path}: {exc}") from exc

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(graph), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(_format_error(error) for error in errors[:5])
        if len(errors) > 5:
            details += f"; … {len(errors) - 5} more"
        raise ValueError(f"Invalid ScenarioForge Attack Graph v2: {details}")

    assert isinstance(graph, dict)  # established by the JSON Schema above
    node_ids = [str(node["id"]) for node in graph["nodes"]]
    chain_order = list(graph["chain_order"])
    if node_ids != chain_order:
        raise ValueError(
            "Invalid ScenarioForge Attack Graph v2: nodes must be in the exact "
            "chain_order order."
        )

    expected_edges = list(zip(chain_order, chain_order[1:]))
    actual_edges = [(edge["source"], edge["target"]) for edge in graph["edges"]]
    if actual_edges != expected_edges:
        raise ValueError(
            "Invalid ScenarioForge Attack Graph v2: edges must be consecutive "
            "chain_order pairs."
        )

    return graph


def load_attack_graph(graph_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read and validate an Attack Graph v2 export from disk."""
    try:
        with open(graph_path, encoding="utf-8") as handle:
            graph = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read attack graph {graph_path}: {exc}") from exc
    return validate_attack_graph(graph)


def extract_attack_graph_from_xml(xml_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Extract and validate the Attack Graph v2 payload embedded inside the ScenarioForge XML."""
    try:
        xml_root = ET.parse(xml_path).getroot()
        flow_el = xml_root.find(".//Scenario/ScenarioEditor/FlagSequencing/FlowState")
        if flow_el is None or not flow_el.text:
            raise ValueError(f"No <FlowState> block found in {xml_path}")
        
        flow_state = json.loads(flow_el.text)
        
        # The FlowState can contain the export directly, nest it under
        # `attack_graph`, or persist only the current chain and assignments.
        graph = flow_state.get("attack_graph") if isinstance(flow_state.get("attack_graph"), dict) else None
        if graph is None:
            return attack_graph_from_flow_state(flow_state, str(flow_state.get("scenario") or ""))
    except Exception as exc:
        raise ValueError(f"Could not extract attack graph from {xml_path}: {exc}") from exc
        
    return validate_attack_graph(graph)


def ordered_chain_ids(graph: dict[str, Any]) -> list[str]:
    """Return the canonical attack-path order after validating the graph."""
    validated = validate_attack_graph(graph)
    return list(validated["chain_order"])


def generator_for(node: dict[str, Any]) -> dict[str, Any]:
    """Return a safe generator mapping for nodes without an assignment."""
    generator = node.get("generator")
    return generator if isinstance(generator, dict) else {}


def attack_graph_from_flow_state(flow_state: dict[str, Any], scenario: str) -> dict[str, Any]:
    """Build the v2 evaluator export from ScenarioForge's saved FlowState.

    The Flow JSON is the durable runtime source. Some CLI responses include an
    `attack_graph` export directly, while others persist only the chain and
    assignments in XML; this adapter keeps both paths on the same v2 contract.
    """
    chain = flow_state.get("chain") if isinstance(flow_state.get("chain"), list) else []
    assignments = flow_state.get("flag_assignments") if isinstance(flow_state.get("flag_assignments"), list) else []
    assignment_by_node = {
        str(item.get("node_id") or "").strip(): item for item in assignments
        if isinstance(item, dict) and str(item.get("node_id") or "").strip()
    }

    nodes = []
    chain_order = []
    for index, raw_node in enumerate(chain, start=1):
        if not isinstance(raw_node, dict):
            continue
        node_id = str(raw_node.get("id") or "").strip()
        if not node_id:
            continue
        assignment = assignment_by_node.get(node_id, {})
        generator = None
        if assignment:
            generator = {
                "id": str(assignment.get("id") or ""),
                "name": str(assignment.get("name") or ""),
                "kind": str(assignment.get("type") or ""),
                "source": str(assignment.get("flag_generator") or ""),
                "catalog": str(assignment.get("generator_catalog") or ""),
                "sequence_index": index,
                "resolved_inputs": assignment.get("resolved_inputs") if isinstance(assignment.get("resolved_inputs"), dict) else {},
                "resolved_outputs": assignment.get("resolved_outputs") if isinstance(assignment.get("resolved_outputs"), dict) else {},
                "flag_value": assignment.get("flag_value"),
            }
        chain_order.append(node_id)
        nodes.append({
            "id": node_id,
            "sequence_index": index,
            "label": str(raw_node.get("name") or node_id),
            "type": str(raw_node.get("type") or ""),
            "is_vuln": bool(raw_node.get("is_vuln")),
            "ipv4": str(raw_node.get("ipv4") or raw_node.get("ip4") or "").strip() or None,
            "generator": generator,
        })

    if not chain_order:
        raise ValueError("ScenarioForge FlowState contains no ordered chain")

    producer_by_fact = {}
    dependencies = []
    for target_index, node_id in enumerate(chain_order):
        assignment = assignment_by_node.get(node_id, {})
        requires = assignment.get("requires") if isinstance(assignment.get("requires"), list) else []
        dependency_facts = {}
        for fact in requires:
            fact = str(fact or "").strip()
            source = producer_by_fact.get(fact)
            if source:
                dependency_facts.setdefault(source, []).append(fact)
        for source, facts in dependency_facts.items():
            source_assignment = assignment_by_node.get(source, {})
            resolved = source_assignment.get("resolved_outputs") if isinstance(source_assignment.get("resolved_outputs"), dict) else {}
            dependencies.append({
                "sequence_index": chain_order.index(source) + 1,
                "source": source,
                "target": node_id,
                "facts": facts,
                "artifacts": facts,
                "artifacts_resolved": resolved,
                "artifacts_resolved_kv": [f"{key}={value}" for key, value in resolved.items()],
            })
        produces = assignment.get("produces") if isinstance(assignment.get("produces"), list) else []
        for fact in produces:
            fact = str(fact or "").strip()
            if fact:
                producer_by_fact[fact] = node_id

    dependency_by_pair = {(item["source"], item["target"]): item for item in dependencies}
    edges = []
    for index, (source, target) in enumerate(zip(chain_order, chain_order[1:]), start=1):
        dependency = dependency_by_pair.get((source, target), {})
        edges.append({
            "sequence_index": index,
            "source": source,
            "target": target,
            "relationship": "sequence",
            "facts": list(dependency.get("facts") or []),
            "artifacts": list(dependency.get("artifacts") or []),
            "artifacts_resolved": dict(dependency.get("artifacts_resolved") or {}),
            "artifacts_resolved_kv": list(dependency.get("artifacts_resolved_kv") or []),
        })

    graph = {
        "schema_version": SCHEMA_VERSION,
        "scenario": str(flow_state.get("scenario") or scenario or ""),
        "chain_order": chain_order,
        "assignment_order": [node_id for node_id in chain_order if node_id in assignment_by_node],
        "nodes": nodes,
        "edges": edges,
        "stages": [{"stage": index, "indices": [index]} for index in range(len(nodes))],
        "fact_dependencies": dependencies,
    }
    return validate_attack_graph(graph)
