import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config
import main


class DashboardMultiSolverTests(unittest.TestCase):
    def test_run_modal_options_update_runtime_configuration(self):
        old_turns = config.MAX_TURNS
        old_threshold = config.PASS_THRESHOLD
        old_output = config.OUTPUT_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                prefix = main.apply_dashboard_run_options({
                    "max_turns": 7,
                    "pass_threshold": 65,
                    "base_dir": temp_dir,
                    "challenge_name": "regression run",
                })
                self.assertEqual(prefix, "regression run")
                self.assertEqual(config.MAX_TURNS, 7)
                self.assertEqual(config.PASS_THRESHOLD, 65)
                self.assertEqual(config.OUTPUT_DIR, temp_dir)
            finally:
                config.MAX_TURNS = old_turns
                config.PASS_THRESHOLD = old_threshold
                config.OUTPUT_DIR = old_output

    def test_first_solver_generates_and_all_solvers_evaluate(self):
        first = {"id": "first", "provider": "ollama", "label": "Solver 1"}
        second = {"id": "second", "provider": "ollama", "label": "Solver 2"}
        result = {
            "pct": 100,
            "matched": [],
            "nodes_visited": [],
            "attack_steps": [],
            "chain_labels": [],
            "error": "",
            "flags_found": [],
            "turns": 1,
            "elapsed_s": 0.1,
            "missed": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(config, "OUTPUT_DIR", temp_dir), \
             patch.object(main, "load_attack_graph", return_value={}), \
             patch.object(main, "parse_reference_graph", return_value=([], [], None)), \
             patch.object(main, "score_challenge_from_graph", return_value=([], 1.0)), \
             patch.object(main, "hypothesize_why_obvious", return_value=""), \
             patch.object(main, "build_claude_nodes", return_value=[]), \
             patch.object(main, "make_dashboard_data", return_value={}), \
             patch.object(main, "update_dashboard_js"), \
             patch.object(main, "solve_challenge_with_model", return_value=result) as solve_mock:

            def generate(_iteration, _difficulty, override_name, gen_model_cfg):
                self.assertIs(gen_model_cfg, first)
                with open(os.path.join(temp_dir, f"{override_name}.xml"), "w") as handle:
                    handle.write("<scenario />")
                with open(os.path.join(temp_dir, f"{override_name}_meta.json"), "w") as handle:
                    json.dump({"params": {}}, handle)
                with open(os.path.join(temp_dir, f"{override_name}_solution.json"), "w") as handle:
                    json.dump({}, handle)
                return True

            with patch.object(main, "generate_one_challenge", side_effect=generate):
                main.run_generate_and_solve("easy", [first, second])

        self.assertEqual([call.args[2] for call in solve_mock.call_args_list], [first, second])


if __name__ == "__main__":
    unittest.main()
