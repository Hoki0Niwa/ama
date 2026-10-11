"""Initial-mainline benchmark; prototype colors, not Steam performance.

Examples (outputs must not exist):
  python tools/bench_fever_first40.py build --output bin/research_first40/build
  python tools/bench_fever_first40.py run --native bin/research_first40/build/fever_battle.exe --build-manifest bin/research_first40/build/build.json --seeds 31004 31010 --output bin/research_first40/smoke
  python tools/bench_fever_first40.py replay --experiment data/fever/baselines/2026-10-11-chain15-research/current-mode.json --output bin/research_first40/replay

--candidate LABEL=PATH uses the same native solo protocol and Observation
adapter. A new search implementation is deliberately not supplied here.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import (SCHEMA, HORIZON, LegacyBackend,
    NativeEnvironment, normalize_step, paired_comparison, run_trial, summarize,
    terminal, trial_result)
from fever_battle.first40_provenance import fingerprints, host_info, sha, snapshot


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def contract():
    return dict(schema=SCHEMA, goal=15, first_main_threshold=10, horizon=40,
        secondary_horizons=[30, 35], visible=3, initial_field="empty", initial_dropset_index=0,
        colors="native queue / prototype splitmix4; Steam distribution unverified",
        environment="normal only; no opponent, nuisance, Fever entry, second mainline or game input",
        denominator="all started trials, including engine failures",
        death_policy="failure even with an actual >=15 fire on the same transition",
        time_budget="no total per-move cutoff; existing native IPC timeout 10 seconds per request",
        native_threads=6, trial_parallelism=1, cpu_sampling="driver + backend native + environment native",
        nodes="null unless backend exposes search_nodes; never inferred from beam width")


def fresh_directory(path):
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def build(args):
    out = fresh_directory(args.output)
    info = snapshot(out, [])
    sources = fingerprints()
    compiler = Path(args.compiler).resolve()
    version = subprocess.check_output([str(compiler), "--version"], text=True).splitlines()[0]
    # build.ps1 joins Output to the repository root; only in-workspace outputs.
    relative = (out / "fever_battle.exe").relative_to(ROOT)
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(ROOT / "build.ps1"), "-Target", "fever_battle", "-Compiler", str(compiler),
        "-Output", str(relative)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (out / "build.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    info.update(command=command, compiler=str(compiler), compiler_sha256=sha(compiler),
        compiler_version=version, returncode=completed.returncode, build_log_sha256=sha(out / "build.log"),
        source_unchanged=sources == fingerprints())
    if completed.returncode == 0:
        info["binaries"] = {str(out / name): sha(out / name) for name in ("fever_battle.exe", "operations.dll")}
    write_json(out / "build.json", info)
    if completed.returncode or not info["source_unchanged"]:
        raise RuntimeError(f"build failed or source changed: {out / 'build.log'}")
    print(json.dumps(dict(build_manifest=str(out / "build.json"), binaries=info["binaries"])))


def checkpoint(out, manifest, runs, complete=False):
    report = dict(contract=contract(), manifest_sha256=sha(out / "manifest.json"),
        complete=complete, runs=runs, summary=summarize(runs),
        paired=paired_comparison(runs) if complete else {})
    write_json(out / "results.json", report)
    write_json(out / "summary.json", dict(complete=complete, summary=report["summary"], paired=report["paired"]))


def run(args):
    seeds = args.seeds if args.seeds is not None else list(range(args.seed_start, args.seed_start + args.count))
    if not seeds or len(seeds) != len(set(seeds)) or min(seeds) < 0:
        raise ValueError("seeds must be nonempty, distinct, nonnegative")
    if len(args.characters) != len(set(args.characters)):
        raise ValueError("duplicate character")
    backends = [("legacy", args.native.resolve())]
    for text in args.candidate:
        label, value = text.split("=", 1)
        if not label or label in {name for name, _ in backends}:
            raise ValueError("candidate labels must be nonempty and unique")
        backends.append((label, Path(value).resolve()))
    if args.width <= 0 or args.depth < 3 or args.depth > 64:
        raise ValueError("positive width and depth 3..64 required")
    # These native builds read dropsets from cwd, not a private data copy.
    binaries = [path for _, path in backends]
    binaries += [path.parent / "operations.dll" for path in binaries if (path.parent / "operations.dll").exists()]
    out = fresh_directory(args.output)
    manifest = snapshot(out, binaries, args.build_manifest)
    manifest.update(contract=contract(), seed_role=args.seed_role,
        settings=dict(seeds=seeds, characters=args.characters, width=args.width, depth=args.depth,
            config=str(args.config.resolve()), backends={label: str(path) for label, path in backends},
            environment_native=str(args.native.resolve())),
        config_sha256=sha(args.config), expected_trials=len(seeds) * len(args.characters) * len(backends))
    if args.config.resolve() != (ROOT / "config.json").resolve():
        (out / "custom-config.json").write_bytes(args.config.read_bytes())
    write_json(out / "manifest.json", manifest)
    runs = []
    with (out / "steps.jsonl").open("x", encoding="utf-8") as trace:
        def emit(record):
            trace.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            trace.flush()
        # Interleave candidates per seed; all use the reference environment.
        for character in args.characters:
            for seed in seeds:
                for label, native in backends:
                    row = run_trial(character, seed, label,
                        lambda native=native: LegacyBackend(native, args.config, args.width, args.depth),
                        lambda c, s: NativeEnvironment(args.native.resolve(), c, s), emit)
                    logical = manifest["host"]["logical_cpus"]
                    row["host_equivalent_cpu_percent"] = (100 * row["cpu_core_equivalents"] / logical
                        if row["cpu_core_equivalents"] is not None and logical else None)
                    runs.append(row)
                    checkpoint(out, manifest, runs)
                    print(json.dumps({key: row[key] for key in ("backend", "character", "seed", "outcome",
                        "placed_moves", "first_main_chain", "success_move")}), flush=True)
    manifest["source_unchanged"] = manifest["source_sha256"] == fingerprints()
    manifest["binaries_unchanged"] = all(sha(path) == value for path, value in manifest["binaries"].items())
    manifest["config_unchanged"] = sha(args.config) == manifest["config_sha256"]
    write_json(out / "manifest.json", manifest)
    complete = len(runs) == manifest["expected_trials"] and all(manifest[key] for key in (
        "source_unchanged", "binaries_unchanged", "config_unchanged"))
    checkpoint(out, manifest, runs, complete)
    if not complete:
        raise RuntimeError("invalid or incomplete experiment; retain outputs for diagnosis")
    print(json.dumps(summarize(runs), ensure_ascii=False), flush=True)


def replay(args):
    experiment = json.loads(args.experiment.read_text(encoding="utf-8-sig"))
    if experiment.get("settings", {}).get("variant") == "oracle8":
        raise ValueError("oracle8 is privileged; cannot use as a visible-three baseline")
    trace_path = args.trace or args.experiment.with_suffix(".jsonl")
    rows = defaultdict(list)
    with trace_path.open(encoding="utf-8-sig") as trace:
        for line in trace:
            row = json.loads(line)
            key = (row["character"], row["seed"])
            prefix = rows[key]
            if row["move"] <= HORIZON and (not prefix or terminal(prefix[-1]) is None):
                prefix.append(normalize_step(row, historical=True))
    keys = [(row["character"], row["seed"]) for row in experiment["runs"]]
    if len(keys) != len(set(keys)) or set(rows) != set(keys):
        raise ValueError("saved trials and trace keys differ or are duplicated")
    runs = []
    for old in experiment["runs"]:
        key = (old["character"], old["seed"])
        result = trial_result(*key, "legacy_saved", rows[key],
            outcome=({"nomove": "nomove", "dead": "dead"}.get(old.get("end"), "engine_error")
                     if old.get("failure") else None),
            failure=old.get("failure"), cost_source="historical wall only; CPU/nodes/memory unavailable")
        if result["outcome"] == "incomplete":
            raise ValueError(f"insufficient saved prefix: {key}")
        # Independent experiment fire history must agree with prefix outcome.
        first = next((r for r in old["fires"] if r["chain"] >= 10 and r["move"] <= 40), None)
        if (result["first_main_move"], result["first_main_chain"]) != (
                first["move"] if first else None, first["chain"] if first else None):
            raise ValueError(f"saved first-main history mismatch: {key}")
        runs.append(result)
    out = fresh_directory(args.output)
    manifest = dict(contract=contract(), mode="historical_replay_no_engine_calls",
        inputs={str(path.resolve()): sha(path) for path in (args.experiment, trace_path)},
        historical_head=experiment.get("head"), historical_source_sha256=experiment.get("source_sha256"),
        historical_native_sha256=experiment.get("native_sha256"),
        historical_settings=experiment.get("settings"), historical_notes=experiment.get("notes"),
        historical_provenance=str(args.experiment.parent / "provenance.json"),
        historical_provenance_sha256=sha(args.experiment.parent / "provenance.json")
            if (args.experiment.parent / "provenance.json").exists() else None,
        evaluator_sha256={str(ROOT / name): sha(ROOT / name) for name in (
            "tools/bench_fever_first40.py", "fever_battle/first40_benchmark.py")},
        evaluator_host=host_info(), cost_scope="old wall time only; CPU/memory/nodes unmeasured",
        historical_inputs_unchanged=True)
    write_json(out / "manifest.json", manifest)
    with (out / "steps.jsonl").open("x", encoding="utf-8") as trace:
        for key in keys:
            for row in rows[key]:
                row["backend"] = "legacy_saved"
                trace.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    checkpoint(out, manifest, runs, True)
    print(json.dumps(summarize(runs), ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build", help="dedicated native build with source/compiler/binary manifest")
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--compiler", default=r"C:\msys64\mingw64\bin\g++.exe")
    b.set_defaults(action=build)
    r = commands.add_parser("run", help="all-started first40 trials; never overwrite existing output")
    r.add_argument("--output", type=Path, required=True)
    r.add_argument("--native", type=Path, required=True)
    r.add_argument("--candidate", action="append", default=[], metavar="LABEL=PATH")
    r.add_argument("--build-manifest", type=Path)
    r.add_argument("--config", type=Path, default=ROOT / "config.json")
    r.add_argument("--characters", nargs="+", default=["raffina", "rafisol"])
    r.add_argument("--seeds", nargs="+", type=int)
    r.add_argument("--seed-start", type=int, default=31001)
    r.add_argument("--count", type=int, default=24)
    r.add_argument("--seed-role", choices=["development", "holdout"], default="development")
    r.add_argument("--width", type=int, default=250)
    r.add_argument("--depth", type=int, default=8)
    r.set_defaults(action=run)
    p = commands.add_parser("replay", help="reclassify saved Oct11 experiment, without engine execution")
    p.add_argument("--experiment", type=Path, required=True)
    p.add_argument("--trace", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(action=replay)
    args = parser.parse_args()
    try:
        args.action(args)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
