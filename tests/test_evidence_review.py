"""Human review and selection use CAF's frozen sealed case and its real artifact checks."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import evidence_review as review
import evidence_study as study
from test_evidence_study import FLAGS, MODEL, instance


class ReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.instance = instance(self.root / "instance")
        self.config = self.root / "config.json"
        study.write(self.config, {"model": MODEL, "candidates": {}, "repetitions": 2})
        self.source = self.root / "baseline"
        self.review = self.root / "review"
        self.experiment = self.root / "saved"
        self.output = self.root / "rerun"

        def trial(kit, directory, model, *, guidance, tools, limits):
            response = list(FLAGS) if not guidance else {"flags": list(FLAGS)}
            data = {
                "status": "completed",
                "final_answer": json.dumps(response),
                "model_calls": 2,
                "tool_calls": 1,
                "tool_calls_by_name": {"read_ticket": 1},
            }
            study.write(directory / "result.json", data)
            return data

        def analyze(worker, analyst, model, limits):
            self.assertTrue((worker / "result.json").is_file())
            return {"analysis": "Check JSON submissions. " + FLAGS[0]}

        def propose(kind, analysis, directory, model, limits, *, index, **kwargs):
            self.assertNotIn(FLAGS[0], analysis)
            proposal = {
                "kind": kind,
                "name": f"{kind.replace('_', '-')}-{index}",
                "description": "Use supplied text.",
            }
            if kind == "tool":
                proposal["operation"] = "unique_flags"
            else:
                proposal["markdown"] = f"{kind} procedure"
            return proposal

        for name, impl in (("run_trial", trial), ("analyze_trial", analyze), ("propose_candidate", propose)):
            patcher = patch.object(study, name, side_effect=impl)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(study, "sources", return_value={"version": "test"})
        patcher.start()
        self.addCleanup(patcher.stop)
        review.run_baseline(self.instance, self.config, self.source)

    def test_stage_flow_provenance_moves_skips_and_explicit_paired_execution(self):
        source = review.inspect_study(self.source)
        self.assertFalse(source["analysis_complete"])
        self.assertIsNone(source["confirmation"])
        self.assertEqual(source["baseline"]["flags_recovered"], 0)
        self.assertEqual([r["flags_in_answer"] for r in source["baseline_rows"]], [2, 2])
        self.assertEqual(self.run_trial.call_count, 2)
        self.assertEqual(self.analyze_trial.call_count, 0)
        pre = review.analyze_study(self.source, self.instance, self.config, self.review)
        self.assertTrue(pre["analysis_complete"])
        self.assertNotIn(FLAGS[0], str(pre))
        self.assertEqual(self.analyze_trial.call_count, 2)
        target = self.root / "review-copy"
        shutil.copytree(self.review, target)
        counts = {"playbook": 1, "tool": 2, "lora_suggestion": 1, "skill": 1}
        shown = review.generate_review(self.source, self.instance, self.config, target, counts)
        self.assertEqual(shown, review.inspect_review(target))
        self.assertEqual(
            shown, review.generate_review(self.source, self.instance, self.config, target, counts)
        )
        self.assertEqual(self.analyze_trial.call_count, 2)
        self.assertEqual(self.propose_candidate.call_count, 5)
        by_key = {r["id"]: r for r in shown["candidates"]}
        self.assertEqual(by_key["tool-002"]["status"], "duplicate")
        self.assertFalse(by_key["lora_suggestion-001"]["eligible"])
        for ids in [["tool-002"], ["lora_suggestion-001"], ["tool-001", "tool-001"], ["../trial"]]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                review.save_experiment(target, ids, self.experiment, "Test")
        selected = ["skill-001", "tool-001"]
        created = review.save_experiment(target, selected, self.experiment, "Case review")
        self.assertEqual(created["status"], "runnable")
        self.assertEqual(created, review.save_experiment(target, selected, self.experiment, "Case review"))
        self.assertEqual((self.run_trial.call_count, self.propose_candidate.call_count), (2, 5))
        portable = self.root / "moved-experiment"
        self.experiment.rename(portable)
        result = review.run_experiment(portable, self.instance, self.config, self.output)
        self.assertEqual(result["retained"], selected)
        self.assertEqual(result["additional_flags"], 4)
        self.assertEqual(result["baseline"]["flags_available"], 4)
        self.assertEqual(self.run_trial.call_count, 6)
        self.assertEqual(result, review.run_experiment(portable, self.instance, self.config, self.output))
        self.assertEqual(self.run_trial.call_count, 6)
        derived = review.inspect_study(self.output)
        self.assertEqual({r["id"] for r in derived["candidates"]}, set(selected))
        self.assertEqual(derived["confirmation"], result["confirmation"])
        manifest, items = review.load_experiment(portable)
        self.assertEqual((manifest["repetitions"], manifest["wall_seconds"]), (2, 120))
        guidance, tools = review.condition_artifacts(items)
        self.assertIn("skill procedure", guidance)
        self.assertEqual([t["name"] for t in tools], ["tool-1"])

    def test_tampering_links_conflicts_and_foreign_case(self):
        args = self.source, self.instance, self.config, self.review
        review.generate_review(*args, {"tool": 1})
        with self.assertRaisesRegex(ValueError, "counts changed"):
            review.generate_review(*args, {"tool": 2})
        with self.assertRaises(ValueError):
            review.analyze_study(self.source, self.instance, self.config, self.source / "nested")
        review.save_experiment(self.review, ["tool-001"], self.experiment, "Trial")
        with self.assertRaises(ValueError):
            review.save_experiment(self.review, [], self.experiment, "Trial")
        cfg = study.read(self.config)
        study.write(self.config, {**cfg, "repetitions": 1})
        with self.assertRaisesRegex(ValueError, "registered case"):
            review.run_experiment(self.experiment, self.instance, self.config, self.output)
        study.write(self.config, cfg)
        p = self.experiment / "artifacts/tool-001/tool.json"
        p.write_text("changed")
        with self.assertRaises(ValueError):
            review.run_experiment(self.experiment, self.instance, self.config, self.output)
        result = self.source / "trials/baseline-001/attempt-0001/worker/result.json"
        result.unlink()
        result.symlink_to(self.config)
        with self.assertRaisesRegex(ValueError, "link"):
            review.inspect_study(self.source)

    def test_copy_previous_candidates_and_additional_counts(self):
        src, config, original = self.instance, self.config, self.root / "original"
        cfg = study.read(config)
        study.write(config, {**cfg, "candidates": {"tool": 1}})
        study.main([str(src), "--config", str(config), "--output", str(original)])
        view = review.generate_review(original, src, config, self.review, {"tool": 1})
        self.assertEqual([r["id"] for r in view["candidates"]], ["tool-001", "tool-002"])
        self.assertEqual([r["eligible"] for r in view["candidates"]], [True, False])

    def test_import_existing_host_history_without_replay_or_answers(self):
        cfg = study.read(self.config)
        study.write(self.config, {**cfg, "repetitions": 5})
        source_id = study.read(self.source / "manifest.json")["package_hash"]
        submitted = json.dumps({"flags": [FLAGS[0]]})
        official = {
            "score": 0.5,
            "passed": False,
            "valid_format": True,
            "unknown_flags_count": 0,
            "checks": [{"name": "ticket", "passed": True}, {"name": "notes", "passed": False}],
        }
        worker = {
            "status": "completed",
            "final_answer": submitted,
            "model_calls": 2,
            "tool_calls": 1,
            "tool_calls_by_name": {"read_ticket": 1},
            "elapsed_seconds": 1.5,
            "extra_private_trace": "omit this",
        }
        row = {"condition": "baseline", "repetition": 1, "worker": worker, "score": official}
        obj = {"rows": [row], "package_hash": source_id, "provenance": {"private": "omit this"}}
        infile = self.root / "host-history.json"
        output = self.root / "imported"
        study.write(infile, obj)
        review.import_scored(self.instance, self.config, infile, output)
        seen = review.inspect_study(output)
        self.assertEqual(seen["baseline"]["flags_recovered"], 1)
        self.assertEqual(seen["baseline_rows"][0]["flags_in_answer"], 1)
        self.assertIsNone(seen["confirmation"])
        self.assertEqual(self.analyze_trial.call_count, 0)
        self.assertEqual(self.run_trial.call_count, 2)
        saved = (output / "trials/baseline-001/attempt-0001/worker/result.json").read_text()
        self.assertNotIn(FLAGS[0], saved)
        self.assertNotIn("omit this", saved)
        self.assertIn("assessment_summary", saved)
        self.assertEqual(review.import_scored(self.instance, self.config, infile, output), seen)
        from evidence_worker import verified_tool_projection

        event = {"seq": 1, "tool": "read_ticket", "timestamp": "2026-11-21T07:06:12.140+00:00",
                 "exit_code": 0, "duration_ms": 94, "flag_like_count": 1}
        traced = {**worker, "tool_events": [event]}
        study.write(infile, {**obj, "rows": [{**row, "worker": traced}]})
        trace_output = self.root / "traced"
        review.import_scored(self.instance, self.config, infile, trace_output)
        restored = study.read(trace_output / "trials/baseline-001/attempt-0001/worker/result.json")
        projected = verified_tool_projection(restored["tool_events"], restored["tool_calls_by_name"])
        self.assertEqual(projected[0]["duration_ms"], 94)
        self.assertIn("1 distinct flag-like values", projected[0]["result_preview"])
        self.assertNotIn(FLAGS[0], json.dumps(restored))
        for changes in [
            {"worker": {**worker, "tool_events": [{**event, "args": {"key": FLAGS[0]}}]}},
            {"worker": {**worker, "tool_events": [{**event, "seq": 2}]}},
            {"worker": {**worker, "tool_events": []}},
            {"score": {**official, "score": 1.0}},
            {
                "score": {
                    **official,
                    "checks": [{"name": "ticket", "passed": False}, {"name": "notes", "passed": True}],
                }
            },
            {"worker": {**worker, "tool_calls_by_name": {"shell": 1}}},
            {"repetition": 2},
        ]:
            with self.subTest(changed=list(changes)), self.assertRaises(ValueError):
                study.write(infile, {**obj, "rows": [{**row, **changes}]})
                review.import_scored(self.instance, self.config, infile, self.root / "invalid")
        study.write(infile, {**obj, "rows": [row, row]})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            review.import_scored(self.instance, self.config, infile, self.root / "invalid")
        self.assertFalse((self.root / "invalid").exists())
