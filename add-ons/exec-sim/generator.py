import json
import os
import random
import re
import subprocess
import time
import xml.etree.ElementTree as ET

import config
from attack_graph import load_attack_graph, extract_attack_graph_from_xml
from llm import call_model


SCENARIOFORGE_PHASE_TIMEOUT_S = 20 * 60


def _run_scenarioforge_phase(
    name, command, *, cwd, log_path, timeout_s=SCENARIOFORGE_PHASE_TIMEOUT_S, allow_failure=False,
):
    """Run one ScenarioForge phase and preserve its complete diagnostics."""
    env = os.environ.copy()
    env.update({"NO_COLOR": "1", "PYTHONUNBUFFERED": "1"})
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, env=env,
            timeout=timeout_s,
        )
        combined = (result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")
    except subprocess.TimeoutExpired as exc:
        combined = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
        result = None
        combined += f"\n[scenarioforge-da] {name} timed out after {timeout_s}s.\n"

    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write(combined)

    if result is None:
        raise RuntimeError(f"ScenarioForge {name} timed out; see {log_path}")
    if allow_failure:
        return result.returncode, combined
    if result.returncode != 0:
        detail = combined.strip().splitlines()[-1] if combined.strip() else "no diagnostics"
        raise RuntimeError(f"ScenarioForge {name} failed ({detail}); see {log_path}")
    return combined


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _last_marker_json(text, marker):
    """Return the last JSON marker emitted by the ScenarioForge CLI."""
    for line in reversed((text or "").splitlines()):
        if marker not in line:
            continue
        try:
            return json.loads(line.split(marker, 1)[1].strip())
        except json.JSONDecodeError:
            continue
    return None


def _last_marker_value(text, marker):
    for line in reversed((text or "").splitlines()):
        if marker in line:
            value = line.split(marker, 1)[1].strip()
            if value:
                return value.split()[0]
    return ""


def _attack_graph_from_flow_artifacts(xml_path, flow_plan_path):
    """Load the v2 graph emitted by Flow, accepting either documented location."""
    try:
        payload = _read_json(flow_plan_path)
    except (OSError, json.JSONDecodeError):
        payload = {}

    candidates = []
    if isinstance(payload, dict):
        candidates.extend((payload.get("attack_graph"), payload.get("data", {}).get("attack_graph")
                           if isinstance(payload.get("data"), dict) else None))
    for graph in candidates:
        if isinstance(graph, dict):
            # Reuse the normal validator by briefly persisting only the exported
            # graph next to the phase artifact.
            graph_path = os.path.splitext(flow_plan_path)[0] + "_attack_graph.json"
            with open(graph_path, "w", encoding="utf-8") as handle:
                json.dump(graph, handle, indent=2)
            return load_attack_graph(graph_path), graph_path

    graph = extract_attack_graph_from_xml(xml_path)
    graph_path = os.path.splitext(flow_plan_path)[0] + "_attack_graph.json"
    with open(graph_path, "w", encoding="utf-8") as handle:
        json.dump(graph, handle, indent=2)
    return graph, graph_path

def classify_vulns(vuln_names):
    classified = []
    for name in vuln_names:
        pkg = name.split("/")[0].lower()
        cve = name.split("/")[-1]
        cls = config.VULN_CLASSIFICATION.get(pkg, {
            "input_specific": None, "type": "Unknown",
            "trigger": "Unknown", "category": "Unknown", "example": "",
        })
        classified.append({
            "vuln_name": name, "package": pkg, "cve_id": cve,
            "input_specific": cls["input_specific"], "vuln_type": cls["type"],
            "trigger": cls["trigger"], "category": cls["category"],
            "example": cls.get("example", ""),
        })
    return classified


def plan_scenario(difficulty="easy", model_cfg=None):
    print(f"[planner] Designing a {difficulty} scenario …")
    if model_cfg is None:
        raise ValueError("plan_scenario requires model_cfg (the generator model config)")

    difficulty_guide = {
        "easy":   "chain_length=2-3, simple routing (RIP/RIPNG), 1-2 services",
        "medium": "chain_length=4-5, moderate routing (OSPFv2), mixed services",
        "hard":   "chain_length=6-8, complex routing (BGP/OSPFv3), all services",
    }.get(difficulty, "chain_length=3-4, OSPFv2")

    prompt = f"""You are designing a CTF (Capture The Flag) network scenario for the CORE TopoGen tool.
Difficulty: {difficulty}
Guide: {difficulty_guide}

IMPORTANT — how docker nodes work:
- Each step in the attack chain uses exactly ONE docker node
- docker_count must equal chain_length (each node appears once, no duplicates)
- Difficulty comes from: longer chains, harder routing, more diverse services
- There are NO decoy nodes — every docker node is part of the chain

Available options:
- Routing protocols: RIP (easy) < RIPNG < OSPFv2 < OSPFv3 < BGP (hard)
- Services (ONLY these three): SSH, HTTP, DHCPClient
- Traffic (ONLY these two): TCP, UDP

Respond ONLY with a JSON object, no markdown:
{{
  "chain_length": <int: 2-3 easy, 4-5 medium, 6-8 hard>,
  "pc_count": <int, 1-2>,
  "server_count": <int, 0-1>,
  "routing_protocol": <one of: RIP, RIPNG, OSPFv2, OSPFv3, BGP>,
  "services": <list from: SSH, HTTP, DHCPClient>,
  "traffic": <list from: TCP, UDP>,
  "vuln_count": <int, 1 to chain_length>,
  "flag_node_generator_count": <int, 1-2>,
  "reasoning": "<one sentence describing what makes this challenge unique>"
}}"""

    raw = call_model(prompt, model_cfg).strip()

    if not raw:
        raise RuntimeError(
            f"[planner] Generator model returned empty response "
            f"(provider={model_cfg['provider']}, model={model_cfg['id']}). "
            "Check that the model is loaded and the host is reachable."
        )

    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()

    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"[planner] Could not parse JSON from generator response: {e}\n"
            f"Raw response was:\n{raw[:500]}"
        ) from e

    params["chain_length"]     = max(2, int(params.get("chain_length", 2)))
    params["docker_count"]     = params["chain_length"]
    params["pc_count"]         = max(1, min(2, int(params.get("pc_count", 1))))
    params["server_count"]     = max(0, min(1, int(params.get("server_count", 0))))
    params["routing_protocol"] = params.get("routing_protocol", "RIP")

    valid_routing = {"RIP", "RIPNG", "BGP", "OSPFv2", "OSPFv3"}
    if params["routing_protocol"] not in valid_routing:
        params["routing_protocol"] = "RIP"

    valid_services = {"SSH", "HTTP", "DHCPClient"}
    raw_svcs = params.get("services", ["SSH"])
    params["services"] = [
        s for s in (
            "SSH"       if s.lower() in ("ssh",) else
            "HTTP"      if s.lower() in ("http","https") else
            "DHCPClient" if s.lower() in ("dhcp","dhcpclient") else
            s.upper() if s.upper() in valid_services else None
            for s in raw_svcs
        ) if s and s in valid_services
    ] or ["SSH"]

    valid_traffic = {"TCP", "UDP"}
    params["traffic"] = [
        t.upper() for t in params.get("traffic", ["TCP"])
        if t.upper() in valid_traffic
    ] or ["TCP"]

    params["vuln_count"] = max(1, min(
        params["docker_count"],
        int(params.get("vuln_count", params["docker_count"]))
    ))
    params["difficulty"] = difficulty

    print(f"[planner] → {params}")
    return params


def build_vuln_report(challenge_name, difficulty, params, solution_path=None, xml_path=None):
    report = {
        "challenge": challenge_name, "difficulty": difficulty,
        "chain_length": params.get("chain_length", 0),
        "routing": params.get("routing_protocol", ""),
        "services": params.get("services", []),
        "vulnerabilities": [],
        "summary": {"total": 0, "input_specific": 0, "logic_auth_flaws": 0, "by_category": {}},
    }

    cve_names = []
    if xml_path and os.path.exists(xml_path):
        try:
            xroot = ET.parse(xml_path).getroot()
            cve_names = [
                i.get("v_name") for i in
                xroot.findall(".//section[@name='Vulnerabilities']/item")
                if i.get("v_name")
            ]
        except Exception as e:
            print(f"    [warn] Could not parse XML for vulns: {e}")

    chain_nodes = []
    try:
        if solution_path and os.path.exists(solution_path):
            graph = load_attack_graph(solution_path)
        else:
            graph = extract_attack_graph_from_xml(xml_path)
        chain_nodes = [n for n in graph.get("nodes", []) if n.get("is_vuln", False)]
    except Exception as e:
        print(f"    [warn] Could not parse solution/graph data: {e}")

    if not cve_names:
        print(f"    [warn] No CVE names found for {challenge_name}")
        return report

    classified = classify_vulns(cve_names)
    for i, cls in enumerate(classified):
        if i < len(chain_nodes):
            node = chain_nodes[i]
            cls["node_label"]     = node.get("label", f"docker-{i+1}")
            cls["chain_position"] = i + 1
            gen = node.get("generator") or {}
            cls["generator_id"]   = gen.get("id", "")
            cls["generator_name"] = gen.get("name", "")
            cls["is_vuln"]        = node.get("is_vuln", True)
        else:
            cls["node_label"]     = f"docker-{i+1}"
            cls["chain_position"] = i + 1
            cls["generator_id"]   = ""
            cls["generator_name"] = ""
            cls["is_vuln"]        = False

        report["vulnerabilities"].append(cls)

        report["summary"]["total"] += 1
        if cls.get("input_specific"): report["summary"]["input_specific"] += 1
        else: report["summary"]["logic_auth_flaws"] += 1

        cat = cls.get("category", "Unknown")
        report["summary"]["by_category"][cat] = report["summary"]["by_category"].get(cat, 0) + 1

    return report


def generate_one_challenge(iteration, difficulty, override_name=None, gen_model_cfg=None):
    try:
        challenge_name = override_name or f"Generated_{int(time.time())}"
        print(f"\n{'='*60}")
        print(f"  [{iteration}] Generating {difficulty.upper()} scenario: {challenge_name}")
        print(f"{'='*60}")

        if gen_model_cfg and gen_model_cfg.get("provider") == "dummy":
            print("[planner] Using dummy static parameters for test...")
            params = {
                "chain_length": 2,
                "docker_count": 2,
                "pc_count": 1,
                "server_count": 0,
                "routing_protocol": "RIP",
                "services": ["SSH", "HTTP"],
                "traffic": ["TCP"],
                "vuln_count": 1,
                "flag_node_generator_count": 1,
                "difficulty": difficulty
            }
        else:
            params = plan_scenario(difficulty, model_cfg=gen_model_cfg)

        xml_path = os.path.join(config.OUTPUT_DIR, f"{challenge_name}.xml")
        cli_cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scenarioforge"))
        seed = random.SystemRandom().randint(1, 2**31 - 1)
        phase_paths = {
            "new": os.path.join(config.OUTPUT_DIR, f"{challenge_name}_new.json"),
            "preview": os.path.join(config.OUTPUT_DIR, f"{challenge_name}_preview-plan.json"),
            "flow": os.path.join(config.OUTPUT_DIR, f"{challenge_name}_flag-sequencing.json"),
            "execute": os.path.join(config.OUTPUT_DIR, f"{challenge_name}_execute.json"),
        }

        def phase_log(phase):
            return os.path.join(config.OUTPUT_DIR, f"{challenge_name}_{phase}.log")
        
        # Use the documented, single-XML pipeline. The seed and phase artifacts
        # make the generated scenario reproducible and diagnostically complete.
        cmd_new = [
            "uv", "run", "python", "-m", "scenarioforge.cli", "new",
            "--xml", xml_path,
            "--scenario", challenge_name,
            "--seed", str(seed),
            "--plan-output", phase_paths["new"],
            "--density-count", str(max(2, params["docker_count"] + params["pc_count"] + params.get("server_count", 0))),
            "--seed-role", f"Workstation={params['pc_count']}",
            "--seed-role", f"Docker={params['docker_count']}",
            "--seed-random-flag-node-generator-count", str(params.get("flag_node_generator_count", 1)),
            "--seed-random-vulnerability-count", str(params.get("vuln_count", 1))
        ]
        
        if params.get("server_count", 0) > 0:
            cmd_new.extend(["--seed-role", f"Server={params['server_count']}"])

        if params.get("routing_protocol"):
            cmd_new.extend(["--seed-routing", f"{params['routing_protocol']}=1"])

        for svc in params.get("services", []):
            cmd_new.extend(["--seed-service", f"{svc}=1"])
            
        for traf in params.get("traffic", []):
            cmd_new.extend(["--seed-traffic", f"{traf}=1"])

            
        print(f"    [cli] running 'new' phase (seed={seed})...")
        _run_scenarioforge_phase("new", cmd_new, cwd=cli_cwd, log_path=phase_log("new"))

        cmd_preview = [
            "uv", "run", "python", "-m", "scenarioforge.cli", "preview-plan",
            "--xml", xml_path,
            "--scenario", challenge_name,
            "--seed", str(seed),
            "--plan-output", phase_paths["preview"],
        ]
        print(f"    [cli] running 'preview-plan' phase...")
        _run_scenarioforge_phase("preview-plan", cmd_preview, cwd=cli_cwd, log_path=phase_log("preview-plan"))

        cmd_seq = [
            "uv", "run", "python", "-m", "scenarioforge.cli", "flag-sequencing",
            "--xml", xml_path,
            "--scenario", challenge_name,
            "--seed", str(seed),
            "--flow-mode", "resolve",
            "--flow-length", str(params["chain_length"]),
            "--flow-best-effort",
            "--plan-output", phase_paths["flow"],
        ]
        print(f"    [cli] running 'flag-sequencing' phase...")
        _run_scenarioforge_phase("flag-sequencing", cmd_seq, cwd=cli_cwd, log_path=phase_log("flag-sequencing"))

        graph, graph_path = _attack_graph_from_flow_artifacts(xml_path, phase_paths["flow"])
        solution_path = os.path.join(config.OUTPUT_DIR, f"{challenge_name}_solution.json")
        with open(solution_path, "w", encoding="utf-8") as handle:
            json.dump(graph, handle, indent=2)
        print(f"    ✓ Saved Attack Graph v2 ({len(graph['nodes'])} nodes) to {solution_path}")

        cmd_execute = [
            "uv", "run", "python", "-m", "scenarioforge.cli", "execute",
            "--xml", xml_path,
            "--scenario", challenge_name,
            "--seed", str(seed),
            "--plan-output", phase_paths["execute"],
            "--post-execution-validation",
        ]
        print("    [cli] running 'execute' phase with post-execution validation...")
        execute_returncode, execute_output = _run_scenarioforge_phase(
            "execute", cmd_execute, cwd=cli_cwd, log_path=phase_log("execute"), allow_failure=True,
        )
        validation_summary = _last_marker_json(execute_output, "VALIDATION_SUMMARY_JSON:")
        session_id = _last_marker_value(execute_output, "CORE_SESSION_ID:")
        if isinstance(validation_summary, dict):
            with open(os.path.join(config.OUTPUT_DIR, f"{challenge_name}_execute-validation.json"), "w", encoding="utf-8") as handle:
                json.dump(validation_summary, handle, indent=2)
        if (execute_returncode != 0 or not session_id or not isinstance(validation_summary, dict)
                or validation_summary.get("ok") is not True):
            raise RuntimeError("ScenarioForge execute did not report a successful post-execution validation")

        meta = {
            "challenge": challenge_name, "difficulty": difficulty,
            "scenario_name": challenge_name, "params": params,
            "xml_file": f"{challenge_name}.xml",
            "seed": seed,
            "attack_graph_file": os.path.basename(solution_path),
            "phase_artifacts": {key: os.path.basename(value) for key, value in phase_paths.items()},
            "validation_file": f"{challenge_name}_execute-validation.json",
            "core_session_id": session_id,
        }
        meta_path = os.path.join(config.OUTPUT_DIR, f"{challenge_name}_meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        vuln_report = build_vuln_report(
            challenge_name, difficulty, params, solution_path=solution_path, xml_path=xml_path,
        )
        vuln_path = os.path.join(config.OUTPUT_DIR, f"{challenge_name}_vulns.json")
        with open(vuln_path, "w") as f:
            json.dump(vuln_report, f, indent=2)
        print(f"    ✓ Saved {challenge_name}_vulns.json")

        print(f"\n  ✓ {challenge_name} complete")
        print(f"    XML      : {xml_path}")
        print(f"    Vulns    : {vuln_path}")
        return True

    except Exception as e:
        print(f"\n  ✗ {challenge_name} FAILED: {e}")
        import traceback; traceback.print_exc()
        return False
