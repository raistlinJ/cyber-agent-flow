from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from attack_graph import attack_graph_from_flow_state, extract_attack_graph_from_xml, load_attack_graph, validate_attack_graph
from simulator import SolverSession, build_simulator


def _graph() -> dict:
    return {
        "schema_version": 2,
        "scenario": "DA compatibility",
        "chain_order": ["entry", "target"],
        "assignment_order": ["target"],
        "nodes": [
            {
                "id": "entry",
                "sequence_index": 1,
                "label": "Entry",
                "type": "Docker",
                "is_vuln": False,
                "ipv4": "10.44.0.10",
                "generator": None,
            },
            {
                "id": "target",
                "sequence_index": 2,
                "label": "Target",
                "type": "docker",
                "is_vuln": True,
                "ipv4": "10.44.0.20",
                "generator": {
                    "id": "target-generator",
                    "name": "Target Generator",
                    "kind": "flag-generator",
                    "source": "",
                    "catalog": "",
                    "sequence_index": 2,
                    "resolved_inputs": {},
                    "resolved_outputs": {"Flag(flag_id)": "FLAG{target}"},
                    "flag_value": "FLAG{target}",
                },
            },
        ],
        "edges": [
            {
                "sequence_index": 1,
                "source": "entry",
                "target": "target",
                "relationship": "sequence",
                "facts": [],
                "artifacts": [],
                "artifacts_resolved": {},
                "artifacts_resolved_kv": [],
            },
        ],
        "stages": [{"stage": 0, "indices": [0]}, {"stage": 1, "indices": [1]}],
        "fact_dependencies": [],
    }


class AttackGraphCompatibilityTests(unittest.TestCase):
    def test_current_v2_graph_validates_and_simulator_uses_exported_path_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            graph_path = Path(temp_dir) / "attack_graph.json"
            xml_path = Path(temp_dir) / "scenario.xml"
            graph_path.write_text(json.dumps(_graph()), encoding="utf-8")
            xml_path.write_text(
                "<Scenarios><Scenario name='Demo'><ScenarioEditor>"
                "<section name='Services'><item selected='SSH'/></section>"
                "</ScenarioEditor></Scenario></Scenarios>",
                encoding="utf-8",
            )

            graph = load_attack_graph(graph_path)
            simulator = build_simulator(str(graph_path), str(xml_path))

        self.assertEqual(graph["schema_version"], 2)
        self.assertEqual(simulator["root_id"], "entry")
        self.assertEqual(simulator["chain_order"], ["entry", "target"])
        self.assertEqual(simulator["ip_map"], {"entry": "10.44.0.10", "target": "10.44.0.20"})
        self.assertEqual(simulator["node_state"]["entry"]["gen_id"], "")

    def test_rejects_nonconsecutive_edges(self):
        graph = _graph()
        graph["edges"] = []

        with self.assertRaisesRegex(ValueError, "consecutive chain_order"):
            validate_attack_graph(graph)

    def test_generic_flow_artifacts_and_fact_dependencies_drive_simulation(self):
        graph = _graph()
        graph["nodes"][0]["generator"] = {
            "id": "ssh_password_helpdesk_home",
            "name": "SSH Password Helpdesk Home",
            "kind": "flag-node-generator",
            "source": "SSH",
            "catalog": "flag_node_generators",
            "sequence_index": 1,
            "resolved_inputs": {},
            "resolved_outputs": {
                "Credential(user, password)": "helpdesk:secret",
                "File(path)": "/home/helpdesk/support/ticket.txt",
            },
            "flag_value": None,
        }
        graph["nodes"][1]["generator"]["resolved_inputs"] = {
            "Credential(user, password)": "helpdesk:secret"
        }
        graph["fact_dependencies"] = [{
            "sequence_index": 1,
            "source": "entry",
            "target": "target",
            "facts": ["Credential(user, password)"],
            "artifacts": ["Credential(user, password)"],
            "artifacts_resolved": {"Credential(user, password)": "helpdesk:secret"},
            "artifacts_resolved_kv": ["Credential(user, password)=helpdesk:secret"],
        }]

        with tempfile.TemporaryDirectory() as temp_dir:
            graph_path = Path(temp_dir) / "attack_graph.json"
            xml_path = Path(temp_dir) / "scenario.xml"
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            xml_path.write_text(
                "<Scenarios><Scenario name='Demo'><ScenarioEditor>"
                "<PlanPreview>{\"full_preview\":{\"services_preview\":{\"entry\":[\"SSH\"]}}}</PlanPreview>"
                "<FlagSequencing><FlowState>{\"flag_assignments\":[]}</FlowState></FlagSequencing>"
                "</ScenarioEditor></Scenario></Scenarios>",
                encoding="utf-8",
            )
            session = SolverSession(build_simulator(str(graph_path), str(xml_path)))

        ok, _ = session.pivot_to("Target")
        self.assertFalse(ok)
        discovery = session.run_command("find /home -type f")
        self.assertIn("ticket.txt", discovery)
        ok, _ = session.pivot_to("Target")
        self.assertTrue(ok)

    def test_flow_state_without_embedded_export_is_adapted_to_v2(self):
        graph = attack_graph_from_flow_state({
            "scenario": "Flow adapter",
            "chain": [
                {"id": "one", "name": "One", "type": "docker", "ipv4": "10.0.0.1"},
                {"id": "two", "name": "Two", "type": "docker", "ipv4": "10.0.0.2", "is_vuln": True},
            ],
            "flag_assignments": [
                {"node_id": "one", "id": "one-gen", "type": "flag-generator", "produces": ["Token(one)"]},
                {"node_id": "two", "id": "two-gen", "type": "flag-generator", "requires": ["Token(one)"]},
            ],
        }, "ignored")

        self.assertEqual(graph["chain_order"], ["one", "two"])
        self.assertEqual(graph["fact_dependencies"][0]["facts"], ["Token(one)"])

    def test_extract_graph_from_current_flow_state_location(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "scenario.xml"
            xml_path.write_text(
                "<Scenarios><Scenario name='Demo'><ScenarioEditor><FlagSequencing>"
                '<FlowState>{"scenario":"Demo","chain":[{"id":"one","name":"One","type":"docker"}],"flag_assignments":[]}</FlowState>'
                "</FlagSequencing></ScenarioEditor></Scenario></Scenarios>",
                encoding="utf-8",
            )
            graph = extract_attack_graph_from_xml(xml_path)
        self.assertEqual(graph["chain_order"], ["one"])


if __name__ == "__main__":
    unittest.main()
