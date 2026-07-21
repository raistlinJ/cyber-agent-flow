import glob
import json
import os
import re

from attack_graph import load_attack_graph

def discover_challenges(source_dir: str) -> list:
    """Scan source_dir for *_solution.json files. Returns sorted list of challenge dicts."""
    challenges = []
    for sol_path in sorted(glob.glob(os.path.join(source_dir, "*_solution.json"))):
        name = os.path.basename(sol_path).replace("_solution.json", "")
        try:
            load_attack_graph(sol_path)
        except Exception as e:
            print(f"  [warn] Skipping {name} — {e}")
            continue

        xml_path  = os.path.join(source_dir, f"{name}.xml")
        meta_path = os.path.join(source_dir, f"{name}_meta.json")
        difficulty = "unknown"
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    difficulty = json.load(f).get("difficulty", "unknown")
            except Exception:
                pass

        challenges.append({
            "name":          name,
            "difficulty":    difficulty,
            "solution_path": sol_path,
            "xml_path":      xml_path if os.path.exists(xml_path) else None,
        })
    return challenges


def short_label(model_id: str) -> str:
    name = model_id.split("/")[-1].lower()
    name = re.sub(r"-\d+-\d+$", "", name)
    name = re.sub(r"-\d+b$", "", name)
    name = re.sub(r"-(preview|latest|turbo)$", "", name)
    name = re.sub(r"^claude-", "", name)
    name = name.replace("-", "")
    return name or "model"


def next_run_dir(base_dir: str, label: str) -> str:
    pattern = re.compile(rf"^trial_run(\d+)_{re.escape(label)}$")
    max_n = 0
    if os.path.isdir(base_dir):
        for entry in os.listdir(base_dir):
            m = pattern.match(entry)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return os.path.join(base_dir, f"trial_run{max_n + 1}_{label}")
