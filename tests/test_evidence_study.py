"""Exercise the standalone study with real artifact validation and an offline worker double."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evidence_study as study
from evidence_artifacts import load_candidate


MODEL = {"provider": "openai", "url": "https://example.invalid/v1", "name": "participant"}
FLAGS = ("FLAG{" + "1" * 24 + "}", "FLAG{" + "2" * 24 + "}")


def instance(path):
    public = path / "participant"
    suite = path / "host" / "suite"
    public.mkdir(parents=True)
    tasks = [{"id": study.TASK, "family": "case-file-handoff", "prompt": "Review this ticket and its sealed notes."}]
    verifier = {study.TASK: {"type": "flags_found", "expected": dict(zip(("ticket", "notes"), FLAGS))}}
    study.write(public / "tasks.json", tasks)
    (public / "handoff-ticket.txt").write_text("Example ticket\n")
    (public / "case-notes.sealed").write_bytes(b"offline worker fixture")
    study.write(suite / "participant/tasks.json", tasks)
    study.write(suite / "evaluator/verifiers.json", verifier)
    manifest = {"id": study.TASK, "format": "scenarioforge-evaluation",
                "files": {f: study.sha256((suite/f).read_bytes()).hexdigest()
                          for f in ["participant/tasks.json", "evaluator/verifiers.json"]}}
    manifest["package_hash"] = study.digest(manifest)
    study.write(suite / "manifest.json", manifest)
    study.write(path / "host/build-receipt.json", {
        "evaluation_package_hash": manifest["package_hash"],
        "participant_sha256": {p.name: study.sha256(p.read_bytes()).hexdigest() for p in public.iterdir()}
    })
    return path


class StudyTests(unittest.TestCase):
    def execute(self, args):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(study, "sources", return_value={"version": "test"}):
            self.assertEqual(study.main([str(a) for a in args]), 0)

    def test_proposal_wall_budget_is_independent_of_the_participant(self):
        from evidence_review import trial_settings_digest

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "config.json"
            cfg = {"model": MODEL, "candidates": {}, "limits": {"wall_seconds": 37}}
            study.write(path, cfg)
            baseline = study.settings(path)
            study.write(path, dict(cfg, generation_wall_seconds=240))
            longer = study.settings(path)
            self.assertEqual(trial_settings_digest(baseline), trial_settings_digest(longer))
            self.assertEqual(longer["limits"]["wall_seconds"], 37)
            for config, expected in ((baseline, 37), (longer, 240)):
                with patch.object(study, "propose_candidate", side_effect=TimeoutError("fixture")) as call:
                    study.generate_candidate(root / str(expected) / "tool-001", "tool", "example",
                                             config, set(), 1, [])
                self.assertEqual(call.call_args.args[4]["wall_seconds"], expected)
            for invalid in (0, -1, True, 12.5, None):
                study.write(path, dict(cfg, generation_wall_seconds=invalid))
                with self.assertRaises(ValueError):
                    study.settings(path)

    def test_ranked_run_validates_all_types_and_confirms_selected_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            src, output, cfgfile = instance(base/"instance"), base/"study", base/"config.json"
            config = {"model": MODEL, "analysis_model": {**MODEL, "name": "analyst"},
                      "generator_model": {**MODEL, "name": "author"},
                      "candidates": {"tool": 3, "playbook": 2, "skill": 1, "lora_suggestion": 1},
                      "selection": "ranked", "keep_top": 4, "repetitions": 2}
            study.write(cfgfile, config)
            args = [src, "--config", cfgfile, "--output", output]
            participants, authors, analysts = [], [], []

            def participant(kit, directory, model, *, guidance, tools, limits):
                self.assertEqual(set(p.name for p in kit.iterdir()), set(study.PUBLIC))
                self.assertEqual(model["name"], "participant")
                stage = directory.relative_to(output).parts[1]
                found = FLAGS[:1] if stage.startswith("baseline-") else FLAGS
                if stage.startswith("confirmation-"):
                    self.assertTrue((output/"selection.json").exists())
                    self.assertIn("playbook procedure", guidance)
                    self.assertIn("skill procedure", guidance)
                    self.assertNotIn("advisory", guidance)
                    self.assertEqual({t["operation"] for t in tools}, {"matching_lines", "unique_flags"})
                participants.append(stage)
                result = {"status": "completed", "final_answer": json.dumps({"flags": found})}
                study.write(directory / "result.json", result)
                return result

            def analyze(worker_directory, analyst, model, limits):
                self.assertTrue((worker_directory/"result.json").is_file())
                self.assertEqual(model["name"], "analyst")
                analysts.append(worker_directory)
                return {"analysis": "Routine offline evidence handling observation."}

            def propose(kind, analysis, directory, model, limits, *, index, previous, backend):
                self.assertEqual(model["name"], "author")
                self.assertEqual(backend, "model")
                self.assertIn("offline", analysis)
                self.assertFalse((output/"selection.json").exists())
                authors.append((kind, index))
                proposal = {"name": "review", "description": "Review text previously read from the case."}
                if kind == "tool":
                    if index == 3:
                        return {**proposal, "operation": "unsupported"}
                    if index == 2:
                        self.assertEqual(previous, ("review",))
                        return {**proposal, "operation": "matching_lines", "keyword": "ticket"}
                    return {**proposal, "operation": "unique_flags"}
                if kind == "lora_suggestion":
                    return {**proposal, "markdown": "An advisory training objective for evaluating future offline case reviews."}
                return {**proposal, "markdown": "# Local review\n\nFollow the " + kind + " procedure in this case."}

            with patch.object(study, "run_trial", side_effect=participant), patch.object(study, "analyze_trial", side_effect=analyze), patch.object(study, "propose_candidate", side_effect=propose):
                self.execute(args)
            report = study.read(output/"report.json")
            self.assertEqual(len(participants), 12)
            self.assertEqual(len(authors), 7)
            self.assertEqual(len(analysts), 2)
            self.assertEqual(report["baseline"]["flags_recovered"], 2)
            self.assertEqual(report["confirmation"]["flags_recovered"], 4)
            self.assertEqual(report["additional_flags"], 2)
            self.assertEqual(set(report["retained"]), {"tool-001","tool-002","skill-001","playbook-001"})
            self.assertEqual(report["candidates"]["tool-003"]["status"], "rejected")
            self.assertEqual(report["candidates"]["playbook-002"]["duplicate_of"], "playbook-001")
            self.assertEqual(report["candidates"]["lora_suggestion-001"]["status"], "advisory")
            artifact = output / report["candidates"]["tool-001"]["artifact"]
            self.assertEqual(load_candidate(artifact)["operation"], "unique_flags")
            with patch.object(study, "run_trial", side_effect=AssertionError("unexpected inference")), patch.object(study, "analyze_trial", side_effect=AssertionError("unexpected analysis")), patch.object(study, "propose_candidate", side_effect=AssertionError("unexpected generation")):
                self.execute(args + ["--resume"])
                self.assertEqual(study.read(output/"report.json"), report)
                study.write(cfgfile, {**config, "seed": 24})
                with self.assertRaisesRegex(ValueError, "configuration"):
                    self.execute(args + ["--resume"])
                study.write(cfgfile, config)
                (artifact/"tool.json").write_text("changed")
                with self.assertRaisesRegex(ValueError, "Checkpoint"):
                    self.execute(args + ["--resume"])

    def test_selection_modes_and_zero_budget(self):
        baseline = {"flags_recovered": 1, "incorrect_submissions": 0}
        scores = {"a": baseline, "b": dict(baseline, flags_recovered=2, incorrect_submissions=1),
                  "c": dict(baseline, flags_recovered=2)}
        def selected(mode, top, results=scores):
            return study.rank(results, baseline, {"selection": mode, "keep_top": top})["selected"]
        self.assertEqual(selected("improve", 3), ["c","b"])
        self.assertEqual(selected("ranked", 1), ["c"])
        self.assertEqual(selected("improve", 3, {"a":baseline}), [])
        self.assertEqual(selected("ranked", 0), [])

    def test_no_candidates_runs_fresh_baseline_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            src, cfgfile, output = instance(base/"instance"), base/"config.json", base/"run"
            study.write(cfgfile, {"model": MODEL, "candidates": {}})
            calls = []
            def participant(kit, directory, model, *, guidance, tools, limits):
                calls.append(directory)
                self.assertEqual((guidance, tools), ("", []))
                return {"status": "timeout", "final_answer": json.dumps({"flags": FLAGS})}
            with patch.object(study,"run_trial",side_effect=participant), patch.object(study,"propose_candidate",side_effect=AssertionError), patch.object(study,"analyze_trial",side_effect=AssertionError):
                self.execute([src, "--config", cfgfile, "--output", output])
            self.assertEqual(len(set(calls)), 2)
            report = study.read(output/"report.json")
            self.assertEqual(report["retained"], [])
            self.assertEqual(report["confirmation"]["flags_recovered"], 0)

    def test_native_flag_scoring_and_budget(self):
        answers = [(json.dumps({"flags":[FLAGS[1], FLAGS[1], "wrong"]}),1,1),
                   ("\n".join(FLAGS),0,0), (json.dumps({"flags": [FLAGS[0], 7]}),0,0),
                   (json.dumps({"flags": list(FLAGS), "extra":"wrong shape"}),0,0)]
        for answer, n, wrong in answers:
            row = study.score({"status":"completed", "final_answer":answer}, set(FLAGS))
            self.assertEqual((row["flags_recovered"],row["incorrect_submissions"]), (n,wrong))
        for status, exhausted in (("timeout",False),("budget_exceeded",False),("completed",True)):
            row = study.score({"status":status, "turn_budget_exhausted":exhausted,
                               "final_answer":json.dumps({"flags":FLAGS})}, set(FLAGS))
            self.assertEqual(row["flags_recovered"], 0)
            self.assertFalse(row["valid_format"])

    def test_invalid_configuration_values(self):
        bad_model = ({"url":42},{"url":"https://name:password@example.invalid/v1"},
                     {"url":"file:///tmp/model"},{"api_key_env":17},{"api_key_env":"bad-name"})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"config.json"
            base = {"model":MODEL,"candidates":{}}
            for patch_values in ([{"model":{**MODEL,**x}} for x in bad_model] +
                                 [{"candidates":{"tool":True}},{"candidates":{"unsafe":1}},
                                  {"repetitions":False},{"keep_top":-1},{"selection":"other"},{"limits":{"wall_seconds":0}}]):
                study.write(path,{**base,**patch_values})
                with self.subTest(patch_values=patch_values), self.assertRaises(ValueError):
                    study.settings(path)


if __name__ == "__main__":
    unittest.main()
