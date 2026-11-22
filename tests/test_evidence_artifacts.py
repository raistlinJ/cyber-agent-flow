import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evidence_artifacts import (KINDS, load_candidate, proposal_instructions, save_candidate,
                                use_tool, validate_candidate)


def proposal(kind):
    base = {"name": "review-evidence", "description": "Review evidence already read from the case."}
    if kind == "tool":
        return dict(base, operation="unique_flags")
    return dict(base, markdown="# Case review\n\nCheck the evidence in order and verify the report.")


class EvidenceArtifactsTest(unittest.TestCase):
    def test_materialize_round_trip_all_types(self):
        names = {"playbook": "playbook.md", "skill": "SKILL.md", "tool": "tool.json",
                 "lora_suggestion": "suggestion.md"}
        with tempfile.TemporaryDirectory() as tmp:
            for kind in KINDS:
                with self.subTest(kind=kind):
                    self.assertIn("JSON object", proposal_instructions(kind))
                    canonical = validate_candidate(kind, proposal(kind))
                    folder = Path(tmp) / kind
                    report = save_candidate(folder, canonical)
                    self.assertEqual(report["status"], "passed")
                    self.assertEqual(set(report["file_sha256"]), {names[kind], "candidate.json"})
                    self.assertEqual(load_candidate(folder), canonical)
                    self.assertEqual(json.loads((folder / "validation.json").read_text()), report)
                    if kind == "skill":
                        self.assertTrue((folder / "SKILL.md").read_text().startswith("---\nname: review-evidence\n"))
                    if kind == "tool":
                        self.assertEqual(len(report["cases"]), 4)
                    with self.assertRaises(FileExistsError):
                        save_candidate(folder, canonical)

    def test_only_closed_tool_operations_and_schema(self):
        bad = [{"operation":"shell"}, {"command":"cat"}, {"keyword":"base"}, {"name":"../outside"},
               {"operation":"matching_lines", "keyword":".*"}, {"operation":"matching_lines", "keyword":"https://a"},
               {"operation":"matching_lines", "keyword":"/etc/passwd"}, {"description":"From FLAG{abc123} here"}]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_candidate("tool", dict(proposal("tool"), **change))

    def test_operations_rely_only_on_supplied_text(self):
        vectors = [
            ({"operation":"unique_flags"}, "FLAG{ff} flag{xx} xFLAG{ff} FLAG{cc} FLAG{ff}", "FLAG{ff}\nFLAG{cc}"),
            ({"operation":"matching_lines","keyword":"case entry"}, "Case Entry 1\nitem\nCASE ENTRY 2", "Case Entry 1\nCASE ENTRY 2")]
        for operation, source, expected in vectors:
            artifact = validate_candidate("tool", dict(proposal("tool"), **operation))
            self.assertEqual(use_tool(artifact, source), expected)
            self.assertEqual(use_tool(artifact, "/etc/passwd"), "")
            self.assertEqual(use_tool(artifact, ""), "")
            with self.assertRaises(ValueError):
                use_tool(artifact, "x" * (128 * 1024 + 1))

    def test_failed_functional_check_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "candidate"
            with patch("evidence_artifacts.use_tool", return_value=""), self.assertRaises(ValueError):
                save_candidate(dest, validate_candidate("tool", proposal("tool")))
            self.assertFalse(dest.exists())

    def test_tampering_rejected_even_if_report_still_passes(self):
        original = validate_candidate("tool", proposal("tool"))
        with tempfile.TemporaryDirectory() as tmp:
            for index, changes in enumerate(("tool", "flag", "report", "unlisted", "symlink")):
                dest = Path(tmp)/str(index)
                save_candidate(dest, original)
                if changes == "tool":
                    (dest / "tool.json").write_text("modified")
                elif changes == "flag":
                    (dest / "candidate.json").write_text(json.dumps(dict(original, description="FLAG{abc}")))
                elif changes == "report":
                    (dest / "validation.json").write_text('{"status":"passed"}')
                elif changes == "unlisted":
                    (dest / "PROVENANCE.md").write_text("unexpected document")
                else:
                    os.symlink("tool.json", dest / "extra")
                with self.assertRaises(ValueError):
                    load_candidate(dest)

if __name__ == "__main__":
    unittest.main()
