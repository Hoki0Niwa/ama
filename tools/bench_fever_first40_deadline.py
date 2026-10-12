"""B0 versus research deadline cap, using one frozen native and the original judge.

Outputs must be new directories. `trials` plays paired openings; `fixed` measures
the saved 124 late observations without following a counterfactual trajectory.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import (LegacyBackend, NativeEnvironment, Observation,
    paired_comparison, percentile, run_trial, summarize)
from fever_battle.first40_deadline_backend import DeadlineBackend
from fever_battle.first40_provenance import fingerprints, process_sample, sha, snapshot
from tools.bench_fever_first40 import contract, fresh_directory, write_json

DATA = ROOT / "data/fever/baselines/2026-10-12-f40-diagnostics/b0-commit"
NATIVE_SHA = "e0cc8f91d5edb7d851b9f1cd6cfce01de26f09f45178f72b491e0c0200365eda"
FIELDS = ("before", "queue", "x", "r", "after", "links", "chain", "options", "capacity",
          "expected_chain", "fire", "fire_moves", "retained_override", "extension_override", "discarded")


def read_steps(path):
    return [json.loads(line) for line in path.read_text(encoding="utf8").splitlines()]


def comparable(row):
    return {k: row.get(k) for k in FIELDS}


def audit(runs, steps, saved):
    old = {(s["character"], s["seed"], s["move"]): s for s in saved}
    groups = {label: {(s["character"], s["seed"], s["move"]): s for s in steps
               if s.get("backend") == label and "move" in s} for label in ("b0", "b1")}
    matched_b0, matched_early = 0, 0
    differences = []
    for key, row in groups["b0"].items():
        if key in old:
            if comparable(row) != comparable(old[key]):
                raise ValueError(f"B0 failed saved reproducibility: {key}")
            matched_b0 += 1
    for key, row in groups["b1"].items():
        if key[2] <= 33:
            ref = groups["b0"].get(key)
            if ref is None or comparable(row) != comparable(ref):
                raise ValueError(f"B1 changed an early observation: {key}")
            matched_early += 1
    rr = {(r["character"], r["seed"], r["backend"]): r for r in runs}
    for ch, seed in sorted({(r["character"], r["seed"]) for r in runs}):
        a, b = rr[ch, seed, "b0"], rr[ch, seed, "b1"]
        shared = sorted(k for k in groups["b0"] if k[:2] == (ch, seed) and k in groups["b1"])
        changes = [k for k in shared if (groups["b0"][k]["x"], groups["b0"][k]["r"]) !=
                   (groups["b1"][k]["x"], groups["b1"][k]["r"])]
        first = changes[0] if changes else None
        differences.append(dict(character=ch, seed=seed,
            first_placement_changed=first[2] if first else None,
            same_observation_at_first_change=bool(first and all(groups["b0"][first][k] == groups["b1"][first][k]
                for k in ("before", "queue"))),
            reference_at_first_change=comparable(groups["b0"][first]) if first else None,
            capped_at_first_change=comparable(groups["b1"][first]) if first else None,
            b0_end=[a["placed_moves"], a["first_main_chain"], a["outcome"]],
            b1_end=[b["placed_moves"], b["first_main_chain"], b["outcome"]]))
        if a["success"]["30"] != b["success"]["30"]:
            raise ValueError("P30 changed under a late-only intervention")
    return dict(b0_saved_steps_matched=matched_b0, early_steps_matched=matched_early,
        trial_differences=differences)


def gate(runs, complete):
    if not complete:
        return dict(pass_to_additional_development=False, reason="incomplete")
    paired = paired_comparison(sorted(runs, key=lambda r: r["backend"]))
    gains = sum(p["gains"] for p in paired.values())
    losses = sum(p["losses"] for p in paired.values())
    unsafe = {label: sum(r["outcome"] in ("dead", "nomove", "timeout", "engine_error")
        for r in runs if r["backend"] == label) for label in ("b0", "b1")}
    passed = (gains > losses and losses == 0 and
        all(p["gains"] >= p["losses"] for p in paired.values()) and unsafe["b1"] <= unsafe["b0"])
    return dict(pass_to_additional_development=passed, gains=gains, losses=losses,
        failures=unsafe, reason="positive development signal" if passed else "stop: no qualifying P40 gain",
        inference="development screening only; never a final adoption test")


def prepare(args):
    if sha(args.native) != NATIVE_SHA:
        raise ValueError("expected the frozen, observer-free research reference native")
    out = fresh_directory(args.output)
    binaries = [args.native]
    dll = args.native.parent / "operations.dll"
    if dll.exists():
        binaries.append(dll)
    manifest = snapshot(out, binaries)
    # The native was built in a git-archive checkout (LF), whereas this working
    # tree uses CRLF for some files. Validate raw build hashes against its own
    # frozen archive; identify current Python separately rather than claiming
    # that it was part of that native build.
    built = json.loads(args.build_manifest.read_text(encoding="utf8"))
    archive = args.build_manifest.parent / "source-snapshot.zip"
    if sha(archive) != built["source_snapshot_sha256"]:
        raise ValueError("frozen native source archive mismatch")
    for path, digest in built["binaries"].items():
        if sha(path) != digest:
            raise ValueError("frozen native build binary mismatch")
    line_ending_differences = []
    with zipfile.ZipFile(archive) as source:
        for name, digest in built["source_sha256"].items():
            raw = source.read(name)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("frozen native source hash mismatch: " + name)
            current = (ROOT / name).read_bytes()
            if current.replace(b"\r\n", b"\n") != raw.replace(b"\r\n", b"\n"):
                raise ValueError("base source content changed: " + name)
            if current != raw:
                line_ending_differences.append(name)
    (out / "native-build.json").write_bytes(args.build_manifest.read_bytes())
    (out / "native-source-snapshot.zip").write_bytes(archive.read_bytes())
    manifest.update(native_build_manifest=built, native_build_manifest_sha256=sha(args.build_manifest),
        native_source_archive_sha256=sha(archive),
        base_source_content_equal_after_crlf_normalization=True,
        base_source_raw_line_ending_differences=line_ending_differences)
    specification = ROOT / "doc/FEVER_FIRST40_NEXT_STEP_2026-10-12.md"
    (out / "experiment-spec.md").write_bytes(specification.read_bytes())
    manifest["specification_sha256"] = sha(specification)
    manifest.update(contract=contract(), experiment="B1 deadline cap only", mode=args.mode,
        seed_role="development", native_source_commit="9c90eede0f0e05176f4dd86363cf29eb186f3f99",
        policy_source="current Python source hashes/archive, distinct from native build source",
        reference_trace_sha256=sha(args.baseline), config_sha256=sha(args.config),
        settings=dict(width=250, maximum_depth=8, virtual_queues=6, native_threads=6,
            horizon=40, observation_visible=3, margin=1, second=False, quota=0,
            time_budget="no total wall cutoff; measure >250ms separately",
            solver_input="Observation only; no environment seed or hidden future",
            environment_native=str(args.native.resolve()), config=str(args.config.resolve())))
    if args.config.resolve() != (ROOT / "config.json").resolve():
        raise ValueError("this experiment uses the fixed repository config")
    return out, manifest


def cost(values):
    return dict(n=len(values), mean_ms=statistics.mean(values) if values else None,
        p95_ms=percentile(values, .95), max_ms=max(values, default=None),
        over_250ms=sum(t > 250 for t in values))


def trials(args):
    seeds = args.seeds or list(range(31001, 31025))
    if len(set(seeds)) != len(seeds) or any(type(s) is not int or s < 0 for s in seeds):
        raise ValueError("distinct nonnegative seeds required")
    out, manifest = prepare(args)
    manifest.update(seeds=seeds, characters=["raffina", "rafisol"], expected_trials=4 * len(seeds),
        candidate_order="alternate b0,b1 / b1,b0 per seed; paired statistics always reference b0")
    write_json(out / "manifest.json", manifest)
    runs, steps = [], []
    violation_counts = {label: Counter() for label in ("b0", "b1")}
    with (out / "steps.jsonl").open("x", encoding="utf8") as trace, (out / "decisions.jsonl").open("x", encoding="utf8") as diag:
        def checkpoint(complete=False):
            ordered = sorted(runs, key=lambda r: (r["backend"], r["character"], r["seed"]))
            report = dict(contract=contract(), manifest_sha256=sha(out / "manifest.json"),
                complete=complete, runs=ordered, summary=summarize(ordered),
                paired=paired_comparison(ordered) if complete else {}, gate=gate(ordered, complete),
                violations={k: dict(v) for k, v in violation_counts.items()})
            write_json(out / "results.json", report)
        for ch in ("raffina", "rafisol"):
            for i, seed in enumerate(seeds):
                for label in (("b0", "b1") if i % 2 == 0 else ("b1", "b0")):
                    holder = {}
                    def factory():
                        backend = DeadlineBackend(args.native, args.config, enabled=label == "b1")
                        holder["backend"] = backend
                        return backend
                    def emit(row):
                        trace.write(json.dumps(row, ensure_ascii=False) + "\n"); trace.flush()
                        steps.append(row)
                        backend = holder.get("backend")
                        data = backend.last_diagnostics if backend else None
                        diag.write(json.dumps(dict(character=ch, seed=seed, backend=label,
                            move=row.get("move", row.get("attempted_move")), data=data), ensure_ascii=False) + "\n")
                        diag.flush()
                        if data:
                            violation_counts[label].update(data["violations"])
                    row = run_trial(ch, seed, label, factory,
                        lambda c, s: NativeEnvironment(args.native, c, s), emit)
                    runs.append(row); checkpoint()
                    print(json.dumps({k: row[k] for k in ("character", "seed", "backend", "placed_moves", "first_main_chain", "outcome")}), flush=True)
    manifest.update(source_unchanged=fingerprints() == manifest["source_sha256"],
        binaries_unchanged=all(sha(p) == h for p, h in manifest["binaries"].items()),
        config_unchanged=sha(args.config) == manifest["config_sha256"])
    write_json(out / "manifest.json", manifest)
    complete = len(runs) == manifest["expected_trials"] and all(manifest[k] for k in
        ("source_unchanged", "binaries_unchanged", "config_unchanged"))
    verification = audit(runs, steps, read_steps(args.baseline))
    verification.update(violations={k: dict(v) for k, v in violation_counts.items()},
        cost={label: cost([s["elapsed_ms"] for s in steps if s.get("backend") == label and "move" in s])
              for label in ("b0", "b1")})
    write_json(out / "verification.json", verification)
    checkpoint(complete)
    if not complete or violation_counts["b1"]:
        raise RuntimeError("incomplete or invalid experiment; outputs retained")
    print(json.dumps(dict(complete=True, gate=gate(runs, True))), flush=True)


def observations(saved):
    since, maximum = {}, {}
    for row in saved:
        key = row["character"], row["seed"]
        obs = Observation(tuple(row["before"]), tuple(row["queue"]), key[0], row["move"] - 1,
            row["move"] - 1, since.get(key, 0), maximum.get(key, 0))
        yield row, obs
        since[key] = 0 if row["chain"] else since.get(key, 0) + 1
        maximum[key] = max(maximum.get(key, 0), row["chain"])


def stable(reply):
    return {k: v for k, v in reply.items() if k != "search_ms"}


def fixed(args):
    out, manifest = prepare(args)
    positions = [(r, o) for r, o in observations(read_steps(args.baseline)) if r["move"] >= 34]
    manifest["positions"] = len(positions)
    write_json(out / "manifest.json", manifest)
    backends = {label: DeadlineBackend(args.native, args.config, label == "b1") for label in ("b0", "b1")}
    cases = []
    try:
        with (out / "decisions.jsonl").open("x", encoding="utf8") as log:
            for i, (row, obs) in enumerate(positions):
                results = {}
                for label in (("b0", "b1") if i % 2 == 0 else ("b1", "b0")):
                    backend = backends[label]
                    backend.engine.normal_build_cache = None
                    backend.enemy = None
                    processes = backend.processes(); before = process_sample(processes)
                    begin = time.perf_counter(); reply = backend.choose(obs)
                    elapsed = (time.perf_counter() - begin) * 1000
                    after = process_sample(processes)
                    results[label] = dict(reply=stable(reply), wall_ms=elapsed,
                        cpu_seconds={k: after[k]["cpu_seconds"] - before[k]["cpu_seconds"] for k in before
                                     if before[k]["cpu_seconds"] is not None and after[k]["cpu_seconds"] is not None},
                        process_sample=after, data=backend.last_diagnostics)
                # Compare original B0 reply/physics to the saved executed observation.
                b = results["b0"]["reply"]
                for k, v in (("x", row["x"]), ("r", row["r"]), ("next_field", row["after"]),
                             ("next_chain", row["chain"]), ("chain", row["expected_chain"])):
                    if b.get(k) != v:
                        raise ValueError(f"fixed B0 mismatch {obs.character}/{row['seed']}/{row['move']}/{k}")
                cases.append(dict(character=obs.character, seed=row["seed"], move=row["move"],
                    placement_changed=(results["b0"]["reply"]["x"], results["b0"]["reply"]["r"]) !=
                                      (results["b1"]["reply"]["x"], results["b1"]["reply"]["r"]), conditions=results))
                log.write(json.dumps(cases[-1], ensure_ascii=False) + "\n"); log.flush()
                print(json.dumps(dict(position=i + 1, total=len(positions))), flush=True)
    finally:
        for backend in backends.values():
            backend.close()
    manifest.update(source_unchanged=fingerprints() == manifest["source_sha256"],
        binaries_unchanged=all(sha(p) == h for p, h in manifest["binaries"].items()))
    write_json(out / "manifest.json", manifest)
    report = dict(positions=len(cases), placement_changes=sum(c["placement_changed"] for c in cases),
        cost={label: cost([c["conditions"][label]["wall_ms"] for c in cases]) for label in backends},
        cpu_seconds={label: sum(sum(c["conditions"][label]["cpu_seconds"].values()) for c in cases) for label in backends},
        native_peak_bytes={label: max(c["conditions"][label]["process_sample"]["backend_native"]["peak_bytes"] or 0 for c in cases) for label in backends},
        violations={label: dict(Counter(v for c in cases for v in c["conditions"][label]["data"]["violations"])) for label in backends},
        complete=manifest["source_unchanged"] and manifest["binaries_unchanged"],
        note="fixed-observation cost; not independent trials or a success-rate experiment")
    write_json(out / "summary.json", report)
    if not report["complete"] or report["violations"]["b1"]:
        raise RuntimeError("fixed experiment invalid")
    print(json.dumps(report), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("trials", "fixed"))
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--build-manifest", type=Path, required=True)
    p.add_argument("--config", type=Path, default=ROOT / "config.json")
    p.add_argument("--baseline", type=Path, default=DATA / "steps.jsonl")
    p.add_argument("--seeds", type=int, nargs="+")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    (trials if args.mode == "trials" else fixed)(args)


if __name__ == "__main__":
    main()
