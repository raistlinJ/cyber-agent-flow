# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "anthropic",
#     "jsonschema>=4.21.1",
#     "openai",
#     "PyYAML>=6.0",
# ]
# ///

import argparse
import asyncio
import json
import os
import re
import sys
import time

from attack_graph import load_attack_graph
import config


SUPPORTED_SOLVER_PROVIDERS = (
    "anthropic",
    "openai",
    "openrouter",
    "vllm",
    "huggingface",
    "ollama",
    "openai-compatible",
)
OLLAMA_OPENAI_BASE_URL = "http://localhost:11434/v1"


def solver_config(provider, model_id, api_key, label, url="", enforce_ssl=True):
    """Build the common model configuration used by CLI and dashboard runs."""
    if provider == "ollama":
        # Ollama exposes an OpenAI-compatible API locally and does not use a key.
        url = url or OLLAMA_OPENAI_BASE_URL
        api_key = ""
    elif provider == "openai-compatible" and not url:
        raise ValueError("--solver-url is required when --solver-provider is openai-compatible")

    return {
        "id": model_id,
        "provider": provider,
        "api_key": api_key,
        "label": label,
        "url": url,
        "enforce_ssl": enforce_ssl,
    }
from dashboard import (
    start_dashboard_server, parse_reference_graph, score_challenge_from_graph,
    hypothesize_why_obvious, build_claude_nodes, make_dashboard_data, update_dashboard_js,
    _load_solver_settings, _solver_settings_path,
)
from generator import generate_one_challenge
from llm import call_model
from simulator import solve_challenge_with_model
from utils import discover_challenges, short_label, next_run_dir

_iteration_counter = 0

def load_scenarioforge_env(env_path=None):
    env_path = os.path.abspath(env_path or config.SCENARIOFORGE_ENV_PATH)
    if not os.path.exists(env_path):
        return
    print(f"[config] Loading env file from {env_path}")
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

def run_generate_and_solve(difficulty: str, model_cfgs, loop: int = 1,
                           challenge_prefix: str = "Generated"):
    """Generate one challenge, then solve it with each configured solver.

    The first solver supplies generation-time LLM assistance. Every solver is
    evaluated against the resulting identical scenario.
    progressive-disclosure loop, and push both the difficulty panel and the
    live terminal to the dashboard. Repeats `loop` times back to back."""
    global _iteration_counter

    if not isinstance(model_cfgs, list):
        model_cfgs = [model_cfgs]
    if not model_cfgs:
        raise ValueError("At least one solver configuration is required")

    generator_model_cfg = model_cfgs[0]
    challenge_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", challenge_prefix).strip("._") or "Generated"

    for i in range(loop):
        challenge_name = f"{challenge_prefix}_{int(time.time())}_{i+1}"

        gen_ok = generate_one_challenge(
            i + 1, difficulty,
            override_name=challenge_name, gen_model_cfg=generator_model_cfg)
        if not gen_ok:
            print(f"  ✗ Generation failed for {challenge_name} — skipping")
            continue

        xml_path      = os.path.join(config.OUTPUT_DIR, f"{challenge_name}.xml")
        solution_path = os.path.join(config.OUTPUT_DIR, f"{challenge_name}_solution.json")

        if os.path.exists(xml_path):
            meta_path     = os.path.join(config.OUTPUT_DIR, f"{challenge_name}_meta.json")
            with open(meta_path) as f:
                params = json.load(f)["params"]

            raw = load_attack_graph(solution_path)
            ref_nodes, ref_edges, _root = parse_reference_graph(raw)
            for model_cfg in model_cfgs:
                print(f"\n  [{model_cfg['label']}] solving {challenge_name} …")
                result = solve_challenge_with_model(xml_path, solution_path, model_cfg)
                step_scores, challenge_score = score_challenge_from_graph(
                    raw, ref_nodes, ref_edges, result["pct"])
                hypothesis = hypothesize_why_obvious(
                    raw, params, result["pct"], model_cfg=model_cfg, call_model_fn=call_model)
                claude_nodes = build_claude_nodes(
                    result["nodes_visited"], result["attack_steps"], result["chain_labels"])

                _iteration_counter += 1
                data = make_dashboard_data(
                    iteration=_iteration_counter, params=params,
                    ref_nodes=ref_nodes, ref_edges=ref_edges,
                    step_scores=step_scores, challenge_score=challenge_score,
                    coverage=result["pct"], matched=result["matched"],
                    hypothesis=hypothesis, claude_nodes=claude_nodes,
                    mismatches={}, missed=result["missed"],
                )
                update_dashboard_js(data, config.DASHBOARD_DIR)

                icon = "✓ PASS" if result["pct"] >= config.PASS_THRESHOLD else "✗ FAIL"
                if result["error"]:
                    print(f"    ERROR: {result['error']}")
                else:
                    print(f"    {icon}  coverage={result['pct']}%  score={challenge_score}  "
                          f"flags={len(result['flags_found'])}  turns={result['turns']}  "
                          f"({result['elapsed_s']}s)")


def run_trial(xml_path: str, solution_path: str,
              solver_models: list, out_dir: str = None,
              challenge_name: str = "challenge") -> list:
    """Run a single challenge against all solver_models. Saves results to out_dir."""
    if out_dir is None:
        labels = "_".join(m["label"].replace(" ", "") for m in solver_models)
        out_dir = next_run_dir(config.OUTPUT_DIR, short_label(labels))
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n{'='*65}")
    print(f"  CTF Trial Run — {challenge_name}")
    print(f"  Models    : {[m['label'] for m in solver_models]}")
    print(f"  Output    : {out_dir}")
    print(f"{'='*65}\n")

    all_results = []
    for model_cfg in solver_models:
        print(f"\n  [{model_cfg['label']}] solving …")
        res = solve_challenge_with_model(xml_path, solution_path, model_cfg)
        all_results.append(res)

        resp_path = os.path.join(out_dir, f"{challenge_name}_{model_cfg['label']}_response.json")
        with open(resp_path, "w") as f:
            json.dump({
                "challenge":     challenge_name,
                "model":         res["model"],
                "label":         res["label"],
                "provider":      res["provider"],
                "elapsed_s":     res["elapsed_s"],
                "turns":         res["turns"],
                "coverage_pct":  res["pct"],
                "flags_found":   res["flags_found"],
                "nodes_visited": res["nodes_visited"],
                "chain_labels":  res["chain_labels"],
                "matched":       res["matched"],
                "missed":        res["missed"],
                "attack_steps":  res["attack_steps"],
                "solver_turns":  res["solver_turns"],
                "error":         res["error"],
            }, f, indent=2)

        icon = "✓ PASS" if res["pct"] >= config.PASS_THRESHOLD else "✗ FAIL"
        if res["error"]:
            print(f"    ERROR: {res['error']}")
        else:
            print(f"    {icon}  coverage={res['pct']}%  "
                  f"flags={len(res['flags_found'])}  turns={res['turns']}  ({res['elapsed_s']}s)")

    return all_results


def solve_only(source_dir: str, solver_models: list, solver_label: str):
    """Replay all challenges in source_dir with the given models. No generation, no browser."""
    challenges = discover_challenges(source_dir)
    if not challenges:
        print(f"\n  No valid challenges found in {source_dir}")
        return

    source_dirname = os.path.basename(source_dir.rstrip("/\\"))
    out_dir = os.path.join(config.OUTPUT_DIR,
                           f"trial_{solver_label}_on_{source_dirname}")
    n = 1
    while os.path.exists(out_dir):
        out_dir = os.path.join(config.OUTPUT_DIR,
                               f"trial{n}_{solver_label}_on_{source_dirname}")
        n += 1
    os.makedirs(out_dir, exist_ok=True)

    summary_path = os.path.join(out_dir, "trial_summary.json")

    print(f"\n{'='*65}")
    print(f"  TRIAL RUN REPLAY MODE")
    print(f"  Source     : {source_dir}")
    print(f"  Challenges : {len(challenges)}")
    print(f"  Solvers    : {[m['label'] for m in solver_models]}")
    print(f"  Output     : {out_dir}")
    print(f"  Threshold  : {config.PASS_THRESHOLD}%")
    print(f"{'='*65}\n")

    all_rounds   = []
    total_passed = 0
    total_failed = 0

    for i, ch in enumerate(challenges, 1):
        print(f"\n{'─'*65}")
        print(f"  [{i}/{len(challenges)}]  {ch['name']}  (difficulty: {ch['difficulty']})")
        print(f"{'─'*65}")

        if not ch["xml_path"]:
            print(f"  [skip] No XML found for {ch['name']}")
            continue

        ch_results    = []
        ch_all_passed = True

        for model_cfg in solver_models:
            print(f"\n  [{model_cfg['label']}] solving …")
            res = solve_challenge_with_model(
                ch["xml_path"], ch["solution_path"], model_cfg)
            ch_results.append(res)

            resp_path = os.path.join(out_dir,
                                     f"{ch['name']}_{model_cfg['label']}_response.json")
            with open(resp_path, "w") as f:
                json.dump({
                    "challenge":     ch["name"],
                    "difficulty":    ch["difficulty"],
                    "source_dir":    source_dir,
                    "model":         res["model"],
                    "label":         res["label"],
                    "provider":      res["provider"],
                    "elapsed_s":     res["elapsed_s"],
                    "turns":         res["turns"],
                    "coverage_pct":  res["pct"],
                    "flags_found":   res["flags_found"],
                    "nodes_visited": res["nodes_visited"],
                    "chain_labels":  res["chain_labels"],
                    "matched":       res["matched"],
                    "missed":        res["missed"],
                    "attack_steps":  res["attack_steps"],
                    "solver_turns":  res["solver_turns"],
                    "error":         res["error"],
                }, f, indent=2)

            if res["error"]:
                print(f"    ERROR: {res['error']}")
                ch_all_passed = False
            else:
                icon = "✓" if res["pct"] >= config.PASS_THRESHOLD else "✗"
                print(f"    {icon}  coverage={res['pct']}%  "
                      f"flags={len(res['flags_found'])}  turns={res['turns']}  "
                      f"({res.get('elapsed_s','?')}s)")
                if res["pct"] < config.PASS_THRESHOLD:
                    ch_all_passed = False

        if ch_all_passed:
            total_passed += 1
        else:
            total_failed += 1

        results_path = os.path.join(out_dir, f"{ch['name']}_results.json")
        with open(results_path, "w") as f:
            json.dump({
                "challenge":      ch["name"],
                "difficulty":     ch["difficulty"],
                "all_passed":     ch_all_passed,
                "pass_threshold": config.PASS_THRESHOLD,
                "model_results":  [
                    {k: v for k, v in r.items()
                     if k not in ("solver_turns", "attack_steps")}
                    for r in ch_results
                ],
            }, f, indent=2)

        all_rounds.append({
            "challenge":  ch["name"],
            "difficulty": ch["difficulty"],
            "all_passed": ch_all_passed,
            "model_results": [
                {"model": r["model"], "label": r["label"],
                 "pct": r["pct"], "flags": r["flags_found"],
                 "turns": r["turns"], "error": r["error"]}
                for r in ch_results
            ],
        })

        with open(summary_path, "w") as f:
            json.dump({
                "mode":             "trial_solve_only",
                "source_dir":       source_dir,
                "solver_models":    [m["label"] for m in solver_models],
                "pass_threshold":   config.PASS_THRESHOLD,
                "max_turns":        config.MAX_TURNS,
                "total_challenges": len(challenges),
                "completed":        len(all_rounds),
                "passed":           total_passed,
                "failed":           total_failed,
                "challenges":       all_rounds,
            }, f, indent=2)

    print(f"\n{'='*65}")
    print(f"  TRIAL COMPLETE — {len(challenges)} challenges")
    print(f"  Passed: {total_passed}  |  Failed: {total_failed}")
    print(f"{'='*65}")

    for r in all_rounds:
        scores = "  ".join(
            f"{m['label']}: {m['pct']}% ({m['turns']}T)"
            for m in r.get("model_results", [])
        )
        icon = "✓" if r.get("all_passed") else "✗"
        print(f"  {r['challenge']:35s}  {r['difficulty']:8s}  {icon}  {scores}")

    by_diff: dict = {}
    for r in all_rounds:
        d = r["difficulty"]
        if d not in by_diff:
            by_diff[d] = {"total": 0, "passed": 0}
        by_diff[d]["total"] += 1
        if r["all_passed"]:
            by_diff[d]["passed"] += 1

    print("\n  By difficulty:")
    for d, stats in sorted(by_diff.items()):
        print(f"    {d:8s}: {stats['passed']}/{stats['total']} passed")

    count = total = 0
    for r in all_rounds:
        for m in r.get("model_results", []):
            if m.get("pct") is not None:
                total += m["pct"]
                count += 1
    if count:
        print(f"\n  Average coverage: {round(total/count, 1)}%")
    print(f"  Full log: {summary_path}")
    print(f"  Output  : {out_dir}")


def apply_dashboard_run_options(params: dict) -> str:
    """Apply per-run controls submitted from the dashboard Run Eval modal."""
    try:
        max_turns = int(params.get("max_turns", config.MAX_TURNS))
        pass_threshold = int(params.get("pass_threshold", config.PASS_THRESHOLD))
    except (TypeError, ValueError) as exc:
        raise ValueError("Max turns and pass threshold must be whole numbers") from exc
    if max_turns < 1:
        raise ValueError("Max turns must be at least 1")
    if not 0 <= pass_threshold <= 100:
        raise ValueError("Pass threshold must be between 0 and 100")

    base_dir = str(params.get("base_dir", config.OUTPUT_DIR) or "").strip()
    if not base_dir:
        raise ValueError("Output directory is required")
    challenge_prefix = str(params.get("challenge_name", "Generated") or "Generated")

    config.MAX_TURNS = max_turns
    config.PASS_THRESHOLD = pass_threshold
    config.OUTPUT_DIR = base_dir
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    return challenge_prefix


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CTF Trial Run — Progressive Disclosure Solver (multi-model)")

    parser.add_argument("--xml",   type=str, default=None,
                        help="Path to scenario XML (topology)")
    parser.add_argument(
        "--graph",
        help="Path to attack graph JSON (optional; will extract from XML if omitted)",
        default=None,
    )

    parser.add_argument("--solver-provider", default="ollama",
                        choices=SUPPORTED_SOLVER_PROVIDERS,
                        help="Solver provider (use openai-compatible for any OpenAI-style endpoint)")
    parser.add_argument("--solver-model",    default="llama3",
                        help="Solver model ID")
    parser.add_argument("--solver-api-key",  default="",
                        help="API key for Anthropic, OpenAI, or OpenAI-compatible solver (overrides env var)")
    parser.add_argument("--solver-url", "--solver-base-url", dest="solver_url", default="",
                        help="OpenAI-compatible endpoint URL; required for openai-compatible, defaults to Ollama at http://localhost:11434/v1")
    parser.add_argument("--solver-no-verify-ssl", dest="solver_enforce_ssl", action="store_false",
                        help="Disable TLS certificate verification for an OpenAI-compatible or Ollama endpoint")
    parser.add_argument("--solver-label",    default="",
                        help="Human-readable label (auto-derived if omitted)")

    parser.add_argument("--solver-provider2", default=None,
                        choices=SUPPORTED_SOLVER_PROVIDERS,
                        help="Second solver provider")
    parser.add_argument("--solver-model2",    default=None,
                        help="Second solver model ID")
    parser.add_argument("--solver-api-key2",  default="",
                        help="API key for second solver")
    parser.add_argument("--solver-url2", "--solver-base-url2", dest="solver_url2", default="",
                        help="OpenAI-compatible endpoint URL for the second solver")
    parser.add_argument("--solver-no-verify-ssl2", dest="solver_enforce_ssl2", action="store_false",
                        help="Disable TLS certificate verification for the second solver endpoint")
    parser.add_argument("--solver-label2",    default="",
                        help="Label for second solver")

    parser.add_argument("--solver-provider3", default=None,
                        choices=SUPPORTED_SOLVER_PROVIDERS,
                        help="Third solver provider")
    parser.add_argument("--solver-model3",    default=None,
                        help="Third solver model ID")
    parser.add_argument("--solver-api-key3",  default="",
                        help="API key for third solver")
    parser.add_argument("--solver-url3", "--solver-base-url3", dest="solver_url3", default="",
                        help="OpenAI-compatible endpoint URL for the third solver")
    parser.add_argument("--solver-no-verify-ssl3", dest="solver_enforce_ssl3", action="store_false",
                        help="Disable TLS certificate verification for the third solver endpoint")
    parser.add_argument("--solver-label3",    default="",
                        help="Label for third solver")

    parser.add_argument("--solve-dir", type=str, default=None,
                        help="Directory of pre-generated challenges to replay "
                             "(solve-only mode — no generation, no browser)")

    parser.add_argument("--generate", choices=["easy", "medium", "hard"], default=None,
                        help="Generate one new challenge, save it, "
                        "then solve it with the progressive-disclosure loop while "
                             "streaming both panels to the dashboard (single-model)")
    parser.add_argument("--serve", action="store_true",
                        help="Start the dashboard server and wait indefinitely for UI commands")
    parser.add_argument("--loop", type=int, default=1,
                        help="Number of generate+solve iterations to run back-to-back "
                             "(only used with --generate)")
    parser.add_argument("--host", default=None,
                        help="Host IP to bind the dashboard server to")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to bind the dashboard server to")
    parser.add_argument(
        "--scenarioforge-env",
        default=config.SCENARIOFORGE_ENV_PATH,
        help=("Path to the shared ScenarioForge environment file "
              "(default: <project-root>/.scenarioforge/.scenarioforge.env)"),
    )
    parser.add_argument("--vllm-host", default=config.VLLM_BASE_URL,
                        help="vLLM base URL (used when provider is vllm)")

    parser.add_argument("--max-turns",     type=int, default=config.MAX_TURNS,
                        help="Max simulator turns per challenge")
    parser.add_argument("--pass-threshold", type=int, default=config.PASS_THRESHOLD,
                        help="Chain-coverage %% needed to count as pass")
    parser.add_argument("--base-dir",      default=config.OUTPUT_DIR,
                        help="Base directory for output runs")
    parser.add_argument("--challenge-name", default="challenge",
                        help="Name tag for single-challenge output files")

    args = parser.parse_args()

    config.SCENARIOFORGE_ENV_PATH = os.path.abspath(args.scenarioforge_env)
    load_scenarioforge_env(config.SCENARIOFORGE_ENV_PATH)

    for suffix in ("2", "3"):
        provider = getattr(args, f"solver_provider{suffix}")
        model = getattr(args, f"solver_model{suffix}")
        if bool(provider) != bool(model):
            parser.error(f"--solver-provider{suffix} and --solver-model{suffix} must be used together")

    try:
        primary_solver = solver_config(
            args.solver_provider,
            args.solver_model,
            args.solver_api_key,
            args.solver_label or short_label(args.solver_model),
            args.solver_url,
            args.solver_enforce_ssl,
        )
        secondary_solvers = []
        for suffix in ("2", "3"):
            provider = getattr(args, f"solver_provider{suffix}")
            model = getattr(args, f"solver_model{suffix}")
            if provider:
                secondary_solvers.append(solver_config(
                    provider,
                    model,
                    getattr(args, f"solver_api_key{suffix}"),
                    getattr(args, f"solver_label{suffix}") or short_label(model),
                    getattr(args, f"solver_url{suffix}"),
                    getattr(args, f"solver_enforce_ssl{suffix}"),
                ))
    except ValueError as exc:
        parser.error(str(exc))

    config.MAX_TURNS      = args.max_turns
    config.PASS_THRESHOLD = args.pass_threshold
    config.OUTPUT_DIR     = args.base_dir
    
    if args.host:
        config.DASHBOARD_HOST = args.host
    if args.port:
        config.DASHBOARD_PORT = args.port
        
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    config.DASHBOARD_DIR = config.OUTPUT_DIR

    if args.solver_provider == "vllm" or (args.solver_provider2 == "vllm") or (args.solver_provider3 == "vllm"):
        config.VLLM_BASE_URL = args.vllm_host

    if args.solver_provider == "anthropic" and args.solver_api_key:
        config.ANTHROPIC_API_KEY = args.solver_api_key
    if args.solver_provider == "openai" and args.solver_api_key:
        config.OPENAI_API_KEY = args.solver_api_key
    if args.solver_provider == "openrouter" and args.solver_api_key:
        config.OPENROUTER_API_KEY = args.solver_api_key

    solver_models = [primary_solver, *secondary_solvers]

    def dashboard_generate_callback(params):
        diff = params.get("difficulty", "easy")
        loops = int(params.get("loop", 1))
        mode = params.get("mode", "generate")
        try:
            challenge_prefix = apply_dashboard_run_options(params)
        except ValueError as exc:
            print(f"[ui] Invalid run settings: {exc}")
            return
        dashboard_solvers = params.get("solvers")

        if isinstance(dashboard_solvers, list) and dashboard_solvers:
            cfgs = []
            for index, solver in enumerate(dashboard_solvers, start=1):
                cfgs.append(solver_config(
                    solver.get("provider", ""),
                    solver.get("model_id", ""),
                    solver.get("api_key", ""),
                    solver.get("label") or f"Solver {index}",
                    solver.get("url", ""),
                    solver.get("enforce_ssl", True),
                ))
            if mode == "directory":
                source_dir = str(params.get("solve_dir", "")).strip()
                if not os.path.isdir(source_dir):
                    print(f"[ui] Replay directory not found: {source_dir}")
                    return
                print(f"\n[ui] Replaying {source_dir} with {[cfg['label'] for cfg in cfgs]}")
                solve_only(source_dir, cfgs,
                           solver_label="_".join(cfg["label"].replace(" ", "") for cfg in cfgs))
                return
            if mode == "single":
                xml_path = str(params.get("xml_path", "")).strip()
                graph_path = str(params.get("graph_path", "")).strip()
                if not os.path.exists(xml_path) or not os.path.exists(graph_path):
                    print("[ui] Single replay requires existing XML and attack graph files.")
                    return
                out_dir = next_run_dir(
                    config.OUTPUT_DIR,
                    "_".join(cfg["label"].replace(" ", "") for cfg in cfgs),
                )
                print(f"\n[ui] Replaying {xml_path} with {[cfg['label'] for cfg in cfgs]}")
                run_trial(xml_path, graph_path, cfgs, out_dir=out_dir,
                          challenge_name=challenge_prefix)
                return
            print(f"\n[ui] Triggering generation: difficulty={diff}, loops={loops}, "
                  f"solvers={[cfg['label'] for cfg in cfgs]}")
            run_generate_and_solve(diff, cfgs, loop=loops, challenge_prefix=challenge_prefix)
            return
        print("[ui] No YAML-backed solver configuration was supplied; refusing to run.")

    start_dashboard_server(dashboard_generate_callback)

    modes_selected = sum([bool(args.generate), bool(args.solve_dir), bool(args.xml or args.graph), bool(args.serve)])
    if modes_selected > 1:
        sys.exit("Error: --generate, --solve-dir, --xml/--graph, and --serve are mutually exclusive")

    if modes_selected == 0:
        args.serve = True

    if args.serve:
        try:
            saved_dashboard_solvers = _load_solver_settings()
            dashboard_solver_labels = [
                solver.get("label") or solver.get("model_id") or solver.get("provider")
                for solver in saved_dashboard_solvers
            ]
        except Exception as exc:
            dashboard_solver_labels = [f"unavailable ({exc})"]
        print(f"Mode      : serve UI control panel")
        print(f"Solvers   : {dashboard_solver_labels or ['none saved']} (from {_solver_settings_path()})")
        print(f"Dashboard : http://localhost:{config.DASHBOARD_PORT}/")
        print("Press Ctrl+C to stop serving it and exit.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\nStopped.")

    elif args.generate:
        print(f"Mode      : generate + solve")
        print(f"Difficulty: {args.generate}")
        print(f"Solver    : {solver_models[0]['label']}")
        print(f"Loop      : {args.loop}")
        print(f"Dashboard : http://localhost:{config.DASHBOARD_PORT}/")
        run_generate_and_solve(
            difficulty=args.generate,
            model_cfg=solver_models[0],
            loop=args.loop,
        )

        print(f"\nGeneration + solve complete. Dashboard stays up at "
              f"http://localhost:{config.DASHBOARD_PORT}/")
        print("Press Ctrl+C to stop serving it and exit.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\nStopped.")

    elif args.solve_dir:
        print(f"Mode      : solve-only replay")
        print(f"Source    : {args.solve_dir}")
        print(f"Solvers   : {[m['label'] for m in solver_models]}")
        print(f"vLLM host : {config.VLLM_BASE_URL}")
        solve_only(args.solve_dir, solver_models,
                   solver_label="_".join(m["label"].replace(" ", "") for m in solver_models))

    elif args.xml and args.graph:
        if not os.path.exists(args.xml):
            sys.exit(f"Error: XML not found: {args.xml}")
        if not os.path.exists(args.graph):
            sys.exit(f"Error: graph JSON not found: {args.graph}")

        print(f"Mode      : single challenge")
        print(f"XML       : {args.xml}")
        print(f"Graph     : {args.graph}")
        print(f"Solvers   : {[m['label'] for m in solver_models]}")
        print(f"vLLM host : {config.VLLM_BASE_URL}")

        out_dir = next_run_dir(config.OUTPUT_DIR,
                                "_".join(m["label"].replace(" ","") for m in solver_models))
        run_trial(args.xml, args.graph, solver_models,
                  out_dir=out_dir, challenge_name=args.challenge_name)

    else:
        parser.print_help()
        sys.exit("\nError: provide either (--xml + --graph), --solve-dir, --serve, or --generate")
