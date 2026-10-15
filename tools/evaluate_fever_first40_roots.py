"""One frozen R1 offline experiment; no online selector or production changes."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import random
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import Observation, percentile
from fever_battle.first40_provenance import fingerprints, process_sample, sha
from fever_battle.first40_root_evaluation import (CapturedB0, WorldEnvironment,
    canonical_observation, continue_world, generate_world, observation_hash,
    placement, propose, read_observation, sample_seed, select_arm)
from fever_battle.worker import JsonProcess
from tools.bench_fever_first40 import write_json
from tools.bench_fever_first40_deadline import prepare as native_prepare, read_steps

PLAN = ROOT / "data/fever/baselines/2026-10-12-f40-root-plan/selection.json"
PLAN_SHA = "d1a672e9c2dce2788a227da76e66990d92e761c3c0f2f577dafde7d0a2770084"
DIAGNOSTIC_SHA = "3980df0481c52dd8e3d01ef1c4a65ef66dee58dddd2202ffe23d1df02ba0543e"
COMPARE = ("before", "queue", "x", "r", "after", "links", "chain", "discarded")


def source_rows(plan):
    rows = {}
    for name, expected in plan["input_sha256"].items():
        path = ROOT / name
        if sha(path) != expected:
            raise ValueError("frozen input changed: " + name)
        if path.suffix == ".jsonl":
            for r in read_steps(path):
                if r["backend"] == "b0" and "move" in r:
                    rows[r["character"], r["seed"], r["move"]] = r
    return rows


def replay_observation(rows, key):
    character, seed, move = key
    since, maximum = 0, 0
    for m in range(1, move):
        r = rows[character, seed, m]
        since = 0 if r["chain"] else since + 1
        maximum = max(maximum, r["chain"])
    r = rows[key]
    return Observation(tuple(r["before"]), tuple(r["queue"]), character, move - 1,
        move - 1, since, maximum)


def unfinished(obs):
    return dict(start_t=obs.placed_total, continuation_placements=0, outcome="unfinished",
        complete=False, started=False, failure=None, first_main_chain=None,
        success={str(h): False for h in (30, 35, 40)}, timings_ms=[], choose_count=0)


def success_bounds(rows):
    n = len(rows)
    k = sum(r["success"]["40"] for r in rows)
    pending = sum(not r["complete"] for r in rows)
    return dict(planned=n, started=sum(r.get("started", True) for r in rows),
        completed=n - pending, unfinished=pending, successes=k,
        rate_bounds=[k / n, (k + pending) / n] if n else None)


def metric(row, name):
    if name in ("30", "35", "40"):
        return int(row["success"][name])
    if name in ("13", "14"):
        return int((row.get("first_main_chain") or 0) >= int(name))
    return int(row["outcome"] in ("dead", "nomove"))


def bootstrap(cases):
    groups = defaultdict(list)
    for c in cases:
        groups[c["source_seed"]].append(c["difference_counts"]["40"] / 4)
    if not groups:
        return None
    keys = sorted(groups); rng = random.Random(0xF401)
    values = []
    for _ in range(10000):
        sample = [v for key in rng.choices(keys, k=len(keys)) for v in groups[key]]
        values.append(statistics.mean(sample))
    values.sort()
    return [values[249], values[9749]]


def analyze(main, runs, selected):
    cases = []
    for c in main:
        rr = [r for r in runs if r["case_id"] == c["case_id"] and r["split"] == "validate"]
        baseline = {r["world_index"]: r for r in rr if r["arm"] == "a0"}
        alternative = {r["world_index"]: r for r in rr if r["arm"] == "a1"}
        arm = selected.get(c["case_id"], "a0")
        chosen = alternative if arm == "a1" else baseline
        complete = len(baseline) == 4 and len(chosen) == 4 and all(
            r["complete"] for r in [*baseline.values(), *chosen.values()])
        counts = {m: sum(metric(chosen[i], m) - metric(baseline[i], m)
            for i in baseline if i in chosen) for m in ("30", "35", "40", "13", "14", "unsafe")}
        gains = sum(chosen[i]["success"]["40"] and not baseline[i]["success"]["40"]
            for i in baseline if i in chosen)
        losses = sum(baseline[i]["success"]["40"] and not chosen[i]["success"]["40"]
            for i in baseline if i in chosen)
        cases.append(dict(case_id=c["case_id"], character=c["character"],
            source_seed=c["source_seed"], move=c["move"], selected=arm,
            has_alternate=c["a1"] is not None, complete=complete, difference_counts=counts,
            gains=gains, losses=losses,
            baseline_counts={m: sum(metric(r, m) for r in baseline.values()) for m in counts},
            selected_counts={m: sum(metric(r, m) for r in chosen.values()) for m in counts},
            posthoc_best_success_count=max(sum(r["success"]["40"] for r in baseline.values()),
                sum(r["success"]["40"] for r in alternative.values()))))
    by_character = {}
    for ch in ("raffina", "rafisol"):
        cc = [c for c in cases if c["character"] == ch]
        n = 4 * len(cc)
        by_character[ch] = dict(conditional_worlds=n,
            baseline_counts={m: sum(c["baseline_counts"][m] for c in cc) for m in cases[0]["difference_counts"]},
            selected_counts={m: sum(c["selected_counts"][m] for c in cc) for m in cases[0]["difference_counts"]},
            difference_counts={m: sum(c["difference_counts"][m] for c in cc) for m in cases[0]["difference_counts"]},
            gains=sum(c["gains"] for c in cc), losses=sum(c["losses"] for c in cc),
            paired_difference=sum(c["difference_counts"]["40"] for c in cc) / n,
            cluster_bootstrap95=bootstrap(cc))
    switches = [c for c in cases if c["selected"] == "a1"]
    positive_by_seed = defaultdict(int)
    for c in cases:
        positive_by_seed[c["source_seed"]] += c["difference_counts"]["40"]
    positive_seeds = sorted(k for k, v in positive_by_seed.items() if v > 0)
    all_complete = len(cases) == 16 and all(c["complete"] for c in cases) and all(
        r["complete"] for r in runs if r["scope"] == "main")
    enough = (len({c["source_seed"] for c in switches}) >= 4 and
        {c["character"] for c in switches} == {"raffina", "rafisol"} and
        any(c["move"] == 24 for c in switches))
    positive = (sum(c["difference_counts"]["40"] for c in cases) > 0 and
        all(v["difference_counts"]["40"] >= 0 for v in by_character.values()) and len(positive_seeds) >= 3)
    safe = all(v["difference_counts"]["unsafe"] <= 0 and all(
        v["difference_counts"][m] >= 0 for m in ("30", "35", "13", "14")) for v in by_character.values())
    passed = all_complete and enough and positive and safe
    disposition = "pass_to_design_only" if passed else (
        "reject_r1" if all_complete and enough and not positive else "hold_insufficient_evidence")
    return dict(cases=cases, by_character=by_character, cluster_bootstrap95=bootstrap(cases),
        conditional_worlds=4 * len(cases), gains=sum(c["gains"] for c in cases),
        losses=sum(c["losses"] for c in cases), switch_cases=len(switches),
        switch_source_seeds=sorted({c["source_seed"] for c in switches}), positive_source_seeds=positive_seeds,
        gate=dict(all_complete=all_complete, enough_switches=enough, positive_confirmation=positive,
            no_auxiliary_regression=safe, pass_to_lightweight_design=passed, disposition=disposition),
        inference="conditional development observations, not empty-board P15_first@40; controls excluded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sha(PLAN) != PLAN_SHA or sha(args.diagnostic) != DIAGNOSTIC_SHA:
        raise ValueError("frozen plan/diagnostic fingerprint mismatch")
    args.mode, args.baseline = "root-evaluation", PLAN
    out, manifest = native_prepare(args)  # Reuse raw native archive/provenance validation.
    spec = ROOT / "doc/contracts/FIRST40_ROOT_EVALUATION.md"
    (out / "experiment-spec.md").write_bytes(spec.read_bytes())
    (out / "selection-plan.json").write_bytes(PLAN.read_bytes())
    plan = json.loads(PLAN.read_text(encoding="utf8")); rows = source_rows(plan)
    manifest.update(experiment="R1 two roots with observable-only B0 continuation",
        specification_sha256=sha(spec), selection_plan_sha256=PLAN_SHA,
        input_sha256=plan["input_sha256"], diagnostic_sha256=sha(args.diagnostic),
        plan=plan, global_wall_cap_seconds=1800,
        contract=dict(horizon=40, first_main_threshold=10, goal=15, visible=3,
            initial_field="16 saved intermediate observations", seed_role="conditional development",
            deadline_policy="B0 depth8 unchanged; actual judge absorbs first10/dead/40",
            colors="prototype_splitmix4, not Steam", selection_worlds=4, validation_worlds=4,
            denominator="all planned continuations; started/completed/unfinished separately recorded",
            threads=6, trial_parallelism=1), settings=dict(width=250, depth=8, virtual_queues=6))
    manifest["binaries"][str(args.diagnostic.resolve())] = sha(args.diagnostic)
    write_json(out / "manifest.json", manifest)
    start = time.perf_counter(); deadline = start + 1800
    proposals, runs, selected, replay_checks = [], [], {}, []
    with JsonProcess([args.diagnostic], cwd=ROOT) as diagnostic, JsonProcess([args.native], cwd=ROOT) as worker:
        with gzip.open(out / "proposals.jsonl.gz", "wt", encoding="utf8") as trace:
            for index, c in enumerate(plan["selected_observations"]):
                obs = read_observation(c["observation"])
                if observation_hash(obs) != c["observation_sha256"]:
                    raise ValueError("observation fingerprint mismatch")
                backend = CapturedB0(args.native, args.config, deadline)
                try:
                    processes = dict(**backend.processes(), diagnostic_native=diagnostic.process,
                                     proposal_environment_native=worker.process)
                    before = process_sample(processes); begin = time.perf_counter()
                    proposal = propose(backend, diagnostic, worker, obs)
                    after = process_sample(processes)
                    proposal["cost"] = dict(wall_ms=(time.perf_counter()-begin)*1000,
                        cpu_seconds={k: after[k]["cpu_seconds"]-v["cpu_seconds"]
                            if after[k]["cpu_seconds"] is not None and v["cpu_seconds"] is not None else None
                            for k,v in before.items()}, process_memory=after)
                finally:
                    backend.close()
                saved = rows[c["character"], c["source_seed"], c["move"]]
                tr = proposal["baseline_transition"]
                if proposal["a0"] != {k: saved[k] for k in ("x", "r")} or tr["field"] != saved["after"] or tr["links"] != saved["links"]:
                    raise ValueError("B0 observed placement changed")
                entry = dict(deepcopy(c), case_id=f"main-{index:02}", scope="main",
                    a0=proposal["a0"], a1=proposal["a1"],
                    fixed_reason=proposal.get("fixed_reason"), proposal_reason=proposal.get("proposal_reason"),
                    proposal_cost=proposal["cost"])
                proposals.append(entry)
                trace.write(json.dumps(dict(case=entry, proposal=proposal), ensure_ascii=False) + "\n"); trace.flush()
                print(json.dumps(dict(stage="proposal", case=entry["case_id"], a0=entry["a0"], a1=entry["a1"])), flush=True)
        write_json(out / "candidates.json", proposals)
        manifest["candidate_manifest_sha256"] = sha(out / "candidates.json")
        # Replay original futures for B0 parity before evaluating any sampled world.
        with gzip.open(out / "replay.jsonl.gz", "wt", encoding="utf8") as trace:
            for c in proposals:
                obs = read_observation(c["observation"])
                queue = worker.ask(dict(op="queue", character=obs.character, seed=c["source_seed"], count=43))["queue"]
                env = WorldEnvironment(args.native, queue, 0, deadline)
                count = [0]
                def emit(r):
                    trace.write(json.dumps(dict(case_id=c["case_id"], record=r)) + "\n")
                    if "move" in r:
                        saved = rows[c["character"], c["source_seed"], r["move"]]
                        if any(r[k] != saved[k] for k in COMPARE):
                            raise ValueError("B0 cold continuation differed from saved trajectory")
                        count[0] += 1
                try:
                    result = continue_world(obs, c["a0"], env,
                        lambda: CapturedB0(args.native, args.config, deadline), emit, deadline)
                finally:
                    env.close()
                if result["failure"] or not result["complete"]:
                    # A known original nomove is a valid matching failure, not a parity error.
                    expected_failure = result["outcome"] == "nomove" and (c["character"], c["source_seed"]) == ("raffina", 41002)
                    if not expected_failure:
                        raise ValueError("original B0 replay failed: " + str(result["failure"]))
                replay_checks.append(dict(case_id=c["case_id"], matched_steps=count[0], result=result))
        write_json(out / "replay-verification.json", replay_checks)
        controls = []
        for index, c in enumerate(plan["known_explanatory_controls"]):
            obs = replay_observation(rows, (c["character"], c["source_seed"], c["move"]))
            controls.append(dict(c, scope="control", case_id=f"control-{index}",
                observation=asdict(obs), observation_sha256=observation_hash(obs),
                a0=dict(x=int(c["placements"][0][0]), r=c["placements"][0][1]),
                a1=dict(x=int(c["placements"][1][0]), r=c["placements"][1][1])))
        write_json(out / "controls.json", controls)
        with gzip.open(out / "steps.jsonl.gz", "wt", encoding="utf8") as trace, (out / "worlds.jsonl").open("x", encoding="utf8") as worldlog:
            def batch(split, cases):
                for c in cases:
                    obs = read_observation(c["observation"])
                    for index in range(4):
                        seed = sample_seed(c["observation_sha256"], split, index)
                        queue, offset = (None, None) if time.perf_counter() >= deadline else generate_world(worker, obs, seed, deadline)
                        worldlog.write(json.dumps(dict(case_id=c["case_id"], split=split,
                            world_index=index, sample_seed=seed, queue=queue, offset=offset)) + "\n"); worldlog.flush()
                        arms = ["a0", "a1"] if c["a1"] else ["a0"]
                        if index % 2:
                            arms.reverse()
                        for arm in arms:
                            identity = dict(case_id=c["case_id"], scope=c["scope"], character=c["character"],
                                source_seed=c["source_seed"], move=c["move"], split=split, world_index=index, arm=arm)
                            if queue is None or time.perf_counter() >= deadline:
                                result = unfinished(obs)
                            else:
                                env = WorldEnvironment(args.native, queue, offset, deadline)
                                def emit(record):
                                    trace.write(json.dumps(dict(**identity, record=record), ensure_ascii=False) + "\n"); trace.flush()
                                try:
                                    result = continue_world(obs, c[arm], env,
                                        lambda: CapturedB0(args.native, args.config, deadline), emit, deadline)
                                finally:
                                    env.close()
                                result["started"] = True
                            runs.append(dict(**identity, **result))
                            write_json(out / "runs.json", runs)
                    print(json.dumps(dict(stage=split, case=c["case_id"],
                        outcomes=dict(Counter(r["outcome"] for r in runs if r["case_id"] == c["case_id"] and r["split"] == split)))), flush=True)
            batch("select", proposals)
            decisions = []
            for c in proposals:
                rr = [r for r in runs if r["case_id"] == c["case_id"] and r["split"] == "select"]
                arm = select_arm(rr, c["a1"] is not None); selected[c["case_id"]] = arm
                decisions.append(dict(case_id=c["case_id"], selected=arm, placement=c[arm],
                    selection_counts={a: dict(success=sum(r["success"]["40"] for r in rr if r["arm"] == a),
                        unsafe=sum(r["outcome"] in ("dead", "nomove") for r in rr if r["arm"] == a)) for a in ("a0", "a1")}))
            write_json(out / "selected-arms.json", decisions)
            decision_hash = sha(out / "selected-arms.json")
            manifest["selection_decisions_sha256_before_validation"] = decision_hash
            write_json(out / "manifest.json", manifest)
            batch("validate", proposals)
            batch("select", controls); batch("validate", controls)
    analysis = analyze(proposals, runs, selected)
    if sha(out / "selected-arms.json") != decision_hash:
        raise ValueError("selection changed after validation")
    main_runs = [r for r in runs if r["scope"] == "main"]
    times = [t for r in runs for t in r["timings_ms"]]
    resources = dict(wall_seconds=time.perf_counter() - start, choose_count=sum(r["choose_count"] for r in runs),
        choose_mean_ms=statistics.mean(times) if times else None, choose_p95_ms=percentile(times, .95),
        choose_max_ms=max(times, default=None), over_250ms=sum(t > 250 for t in times),
        cpu_seconds_by_process={k: sum(r.get("cpu_seconds_by_process", {}).get(k) or 0 for r in runs)
            for k in ("python_driver", "backend_native", "environment_native")},
        peak_working_set_bytes={k: max((r.get("peak_working_set_bytes", {}).get(k) or 0 for r in runs), default=0)
            for k in ("backend_native", "environment_native")})
    resources.update(proposal_wall_ms=sum(c["proposal_cost"]["wall_ms"] for c in proposals),
        proposal_cpu_seconds={k:sum(c["proposal_cost"]["cpu_seconds"].get(k) or 0 for c in proposals)
            for k in ("python_driver","backend_native","diagnostic_native","proposal_environment_native")},
        replay_cpu_seconds={k:sum(c["result"]["cpu_seconds_by_process"].get(k) or 0 for c in replay_checks)
            for k in ("python_driver","backend_native","environment_native")},
        interpretation="continuation CPU excludes process initialization; proposal/replay costs separate; lifetime RSS peaks not additive")
    manifest.update(source_unchanged=fingerprints() == manifest["source_sha256"],
        binaries_unchanged=all(sha(p) == h for p, h in manifest["binaries"].items()),
        config_unchanged=sha(args.config) == manifest["config_sha256"],
        output_sha256={p.name: sha(p) for p in out.iterdir() if p.is_file() and p.name != "manifest.json"})
    if not all(manifest[k] for k in ("source_unchanged", "binaries_unchanged", "config_unchanged")):
        raise ValueError("measurement inputs changed")
    write_json(out / "manifest.json", manifest)
    write_json(out / "results.json", dict(analysis=analysis, resources=resources,
        main_bounds=success_bounds(main_runs), all_bounds=success_bounds(runs),
        controls=[r for r in runs if r["scope"] == "control"], replay_cases=len(replay_checks),
        matched_replay_steps=sum(r["matched_steps"] for r in replay_checks),
        manifest_sha256=sha(out / "manifest.json")))
    print(json.dumps(dict(complete=analysis["gate"]["all_complete"], gate=analysis["gate"], resources=resources)), flush=True)


if __name__ == "__main__":
    main()
