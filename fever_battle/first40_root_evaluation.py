"""Offline R1: one forced root, then observable-only frozen B0 continuation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from functools import cmp_to_key
import hashlib
import json
import time

from .first40_benchmark import (HORIZON, MAINLINE, LegacyBackend, Observation,
    error_outcome, geometry, normal_side, normalize_step, terminal)
from .first40_provenance import process_sample
from .model import ROOT
from .worker import JsonProcess


class ResearchBudgetExpired(Exception):
    pass


def remaining_timeout(deadline):
    remaining = deadline - time.perf_counter() if deadline is not None else 10
    if remaining <= 0:
        raise ResearchBudgetExpired("research wall budget exhausted")
    return min(10, remaining)


def canonical_observation(obs):
    return json.dumps(asdict(obs), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def observation_hash(obs):
    return hashlib.sha256(canonical_observation(obs).encode()).hexdigest()


def read_observation(raw):
    if set(raw) != set(Observation.__dataclass_fields__):
        raise ValueError("public Observation fields only")
    obs = Observation(**dict(raw, field=tuple(raw["field"]), visible=tuple(raw["visible"])))
    if type(obs.placed_total) is not int or not 0 <= obs.placed_total < HORIZON:
        raise ValueError("placed_total outside opening")
    if type(obs.normal_chain_max) is not int or not 0 <= obs.normal_chain_max < MAINLINE:
        raise ValueError("first mainline already fired")
    if len(obs.visible) != 3:
        raise ValueError("current + NEXT2 required")
    return obs


def sample_seed(obs_hash, split, index):
    if split not in ("select", "validate") or type(index) is not int or not 0 <= index < 4:
        raise ValueError("fixed split and index 0..3 required")
    text = f"ama.first40.root-eval.v1|{obs_hash}|{split}|{index}"
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def stable_reply(reply):
    return {k: v for k, v in reply.items() if k not in ("search_ms", "research_diagnostics")}


def placement(reply):
    return {k: reply[k] for k in ("x", "r")}


class CapturedB0(LegacyBackend):
    """Same B0 policy; recording and response timeout do not change its input."""
    def __init__(self, native, config, deadline=None):
        super().__init__(native, config, width=250, depth=8)
        self.deadline = deadline
        self.calls = []
        self._ask = self.engine.native.ask
        self.engine.native.ask = self._capture

    def _capture(self, request, *args, **kwargs):
        if "seed" in request or "seed" in request.get("request", {}):
            raise ValueError("environment seed forbidden in B0 requests")
        kwargs["timeout"] = min(kwargs.get("timeout", 10), remaining_timeout(self.deadline))
        reply = self._ask(request, *args, **kwargs)
        if request.get("op") in ("solo", "normal_capacity"):
            self.calls.append(dict(request=deepcopy(request), reply=deepcopy(reply)))
        return reply

    def choose(self, obs):
        read_observation(asdict(obs))
        self.calls = []
        return super().choose(obs)


class WorldEnvironment:
    """Only this object owns the future. No actor receives this object or its ID."""
    def __init__(self, native, queue, start, deadline=None):
        if len(queue) < start + HORIZON + 3:
            raise ValueError("world must contain all observation windows")
        self.queue, self.start, self.deadline = tuple(queue), start, deadline
        self.worker = JsonProcess([native], cwd=ROOT)

    def visible(self, t):
        index = self.start + t
        return tuple(self.queue[index:index + 3])

    def transition(self, field, piece, decision):
        return self.worker.ask(dict(op="transition", field=list(field), piece=piece,
            **placement(decision)), timeout=remaining_timeout(self.deadline))

    def processes(self):
        return {"environment_native": self.worker.process}

    def close(self):
        self.worker.close()


def generate_world(worker, obs, seed, deadline=None):
    # The existing queue API begins at phase zero. Generate the prefix as well
    # for a nonzero phase, then expose only the appropriate observation window.
    start = (obs.dropset_index - obs.placed_total) % 16
    queue = worker.ask(dict(op="queue", character=obs.character, seed=seed,
        count=start + HORIZON + 3), timeout=remaining_timeout(deadline))["queue"]
    offset = start + obs.placed_total
    if [p[0] for p in queue[offset:offset + 3]] != [p[0] for p in obs.visible]:
        raise ValueError("visible shapes differ from character phase")
    queue[offset:offset + 3] = list(obs.visible)
    return queue, start


def aggregate_roots(search, options):
    if options.get("aim") or options.get("sustained") or options.get("rebuild"):
        raise ValueError("opening B0 comparator only")
    roots = {}
    for virtual in search["virtual_searches"]:
        for c in virtual["final_candidates"]:
            key = c["x"], c["r"]
            if key not in roots:
                roots[key] = dict(x=c["x"], r=c["r"], score_sum=0, aim_sum=0,
                    chain=0, next_room=c["next_room"], virtual_chains=[])
            root = roots[key]
            if root["next_room"] != c["next_room"]:
                raise ValueError("root room differed across virtual worlds")
            root["score_sum"] += c["score"]
            root["aim_sum"] += c["aim"]
            root["chain"] = max(root["chain"], c["chain"])
            root["virtual_chains"].append(c["chain"])
    if any(len(c["virtual_chains"]) != 6 for c in roots.values()):
        raise ValueError("six complete root results required")
    def compare(a, b):
        if bool(a["next_room"]) != bool(b["next_room"]):
            return -1 if a["next_room"] else 1
        ascending = (not options.get("stretch", True) and
            a["chain"] >= options["trigger"] and b["chain"] >= options["trigger"])
        va, vb = a["score_sum"], b["score_sum"]
        return ((va > vb) - (va < vb)) * (1 if ascending else -1)
    return sorted(roots.values(), key=cmp_to_key(compare))


def transition_identity(tr):
    return json.dumps([tr["field"], tr["links"], tr["discarded"]], sort_keys=True)


def transition_valid(tr, margin):
    return (not tr["dead"] and tr["discarded"] == 0 and len(tr["links"]) < MAINLINE
        and all(v >= 0 for v in geometry(tr["field"], margin)["margin_headroom"]))


def guard_accepts(backend, obs, original, root, tr):
    """Execute the existing Python adoption guards with an injected solo reply.

    No guard is copied or relaxed. Cache and solo method are always restored.
    Any native transition used by the guard remains the unchanged physics.
    """
    engine = backend.engine
    options = deepcopy(original["benchmark_diagnostics"]["options"])
    own = normal_side(obs.character)
    own.update(field=list(obs.field), queue=list(obs.visible), piece_id=obs.placed_total,
        observed_frame=obs.placed_total, dropset_index=obs.dropset_index,
        moves_since_chain=obs.moves_since_chain, normal_chain_max=obs.normal_chain_max)
    fake = {k: deepcopy(v) for k, v in original.items() if k != "benchmark_diagnostics"}
    fake.update(**placement(root), chain=root["chain"], eval=root["score_sum"] // 6,
        fire=False, next_field=tr["field"], next_chain=len(tr["links"]),
        next_score=sum(engine.scoring.chain(obs.character, tr["links"])),
        next_discarded=tr["discarded"], next_all_clear=tr["all_clear"])
    if obs.visible[0][0] == "0":
        fake["color"] = "RYGB"["URDL".index(root["r"])]
    saved_ask, saved_cache = engine.solo.ask, engine.normal_build_cache
    engine.normal_build_cache = None
    engine.solo.ask = lambda *args, **kwargs: deepcopy(fake)
    try:
        adopted = engine._solo_build(own, options)
        accepted = (placement(adopted) == placement(root) and not adopted.get("fire")
            and not adopted.get("normal_main_retained") and not adopted.get("normal_extension_selected")
            and adopted["next_field"] == tr["field"] and adopted["next_chain"] == len(tr["links"]))
        return accepted, stable_reply(adopted)
    finally:
        engine.solo.ask, engine.normal_build_cache = saved_ask, saved_cache


def propose(backend, diagnostic_worker, environment_worker, obs):
    backend.engine.normal_build_cache = None
    backend.enemy = None
    reply = backend.choose(obs)
    calls = deepcopy(backend.calls)
    solo = [c for c in calls if c["request"]["op"] == "solo"]
    if len(solo) != 1:
        raise ValueError("one fresh B0 solo call required")
    request, native = solo[0]["request"], solo[0]["reply"]
    diag_request = dict(deepcopy(request), research_diagnostics=True,
        research_placed_total=obs.placed_total, research_detail_all=False)
    started = time.perf_counter()
    diagnostic = diagnostic_worker.ask(diag_request, timeout=remaining_timeout(backend.deadline))
    diag_ms = (time.perf_counter() - started) * 1000
    if stable_reply(diagnostic) != stable_reply(native):
        raise ValueError("diagnostic changed B0 reply")
    options = reply["benchmark_diagnostics"]["options"]
    def transition(root):
        return environment_worker.ask(dict(op="transition", field=list(obs.field),
            piece=obs.visible[0], **placement(root)), timeout=remaining_timeout(backend.deadline))
    a0_tr = transition(reply)
    if a0_tr["field"] != reply["next_field"] or len(a0_tr["links"]) != reply["next_chain"]:
        raise ValueError("B0 transition mismatch")
    report = dict(a0=placement(reply), a1=None, b0_reply=reply,
        native_request=request, native_reply=native, diagnostic=diagnostic,
        diagnostic_wall_ms=diag_ms, rejected=[], root_order=[], baseline_transition=a0_tr)
    if (reply.get("fire") or reply.get("normal_main_retained") or reply.get("normal_extension_selected")
            or placement(reply) != placement(native)):
        report["fixed_reason"] = "fire_or_adoption_guard"
        return report
    searches = diagnostic["research_diagnostics"]["searches"]
    if not searches:
        raise ValueError("diagnostic root search missing")
    search = searches[-1]  # A margin-zero retry, if present, is a separate search.
    roots = aggregate_roots(search, options)
    report["root_order"] = roots
    transitions = {(c["x"], c["r"]): transition(c) for c in roots}
    chosen = roots[0]
    if options.get("preserve_build"):
        quiet = [c for c in roots if c["next_room"] > 0 and
            len(transitions[c["x"], c["r"]]["links"]) <= 2]
        if quiet:
            chosen = quiet[0]
    if (placement(chosen) != placement(native) or chosen["chain"] != native["chain"]
            or chosen["score_sum"] // 6 != native["eval"]):
        raise ValueError("reconstructed B0 comparator/preserve_build differs")
    eligible = []
    for c in roots:
        tr = transitions[c["x"], c["r"]]
        reason = None
        if c["next_room"] <= 0:
            reason = "no_next_room"
        elif not transition_valid(tr, search["margin"]):
            reason = "first_step_safety"
        elif transition_identity(tr) == transition_identity(a0_tr):
            reason = "same_executed_state"
        else:
            accepted, guarded = guard_accepts(backend, obs, reply, c, tr)
            if not accepted:
                reason = "python_adoption_guard"
                report["rejected"].append(dict(**placement(c), reason=reason, guard_reply=guarded))
                continue
        if reason:
            report["rejected"].append(dict(**placement(c), reason=reason))
        else:
            eligible.append(c)
    supported = [c for c in eligible if c["chain"] >= 15]
    if eligible:
        selected = (supported or eligible)[0]
        report.update(a1=placement(selected), alternate_root=selected,
            alternate_transition=transitions[selected["x"], selected["r"]],
            proposal_reason="virtual15_proposal" if supported else "next_b0_root")
    else:
        report["fixed_reason"] = "no_distinct_guard_accepted_root"
    return report


def continue_world(obs, forced, environment, backend_factory, emit, deadline=None):
    """Intermediate start with absolute moves; first-mainline failures absorb."""
    records, backend = [], None
    outcome, failure, first = None, None, None
    field, since, maximum = obs.field, obs.moves_since_chain, obs.normal_chain_max
    processes = environment.processes()
    cpu_start = process_sample(processes)
    begin_trial = time.perf_counter()
    timings, request_count = [], 0
    try:
        remaining_timeout(deadline)
        if environment.visible(obs.placed_total) != obs.visible:
            raise ValueError("world must preserve the three observed pieces")
        backend = backend_factory()
        processes.update(backend.processes())
        cpu_start = process_sample(processes)
        for t in range(obs.placed_total, HORIZON):
            remaining_timeout(deadline)
            visible = environment.visible(t)
            current = Observation(tuple(field), visible, obs.character, t,
                obs.dropset_index + t - obs.placed_total, since, maximum)
            decision = forced
            elapsed, cpu = None, None
            if t > obs.placed_total:
                before = process_sample(processes)
                start = time.perf_counter()
                request_count += 1
                try:
                    decision = backend.choose(current)
                finally:
                    elapsed = (time.perf_counter() - start) * 1000
                    timings.append(elapsed)
                after = process_sample(processes)
                cpu = {k: after[k]["cpu_seconds"] - v["cpu_seconds"]
                    if after[k]["cpu_seconds"] is not None and v["cpu_seconds"] is not None else None
                    for k, v in before.items()}
            tr = environment.transition(field, visible[0], decision)
            if t > obs.placed_total and (decision["next_field"] != tr["field"] or decision["next_chain"] != len(tr["links"])):
                raise ValueError("B0 reply differs from executed physics")
            info = decision.get("benchmark_diagnostics", {})
            record = normalize_step(dict(move=t + 1, before=list(field), queue=list(visible),
                after=tr["field"], links=tr["links"], **placement(decision), dead=tr["dead"],
                discarded=tr["discarded"], elapsed_ms=elapsed, cpu_seconds=cpu,
                forced_first=t == obs.placed_total, observation=asdict(current),
                options=info.get("options"), capacity=info.get("capacity"),
                expected_chain=decision.get("chain"), fire=decision.get("fire"),
                fire_moves=decision.get("fire_moves"),
                retained_override=decision.get("normal_main_retained", False),
                extension_override=decision.get("normal_extension_selected", False),
                search_depths=decision.get("search_virtual_depths")))
            emit(record); records.append(record)
            if record["chain"] >= MAINLINE:
                first = dict(move=t + 1, chain=record["chain"])
            outcome = terminal(record)
            if outcome:
                break
            field = tuple(tr["field"])
            since = 0 if record["chain"] else since + 1
            maximum = max(maximum, record["chain"])
    except Exception as error:
        budget = isinstance(error, ResearchBudgetExpired) or (
            isinstance(error, TimeoutError) and deadline is not None and time.perf_counter() >= deadline)
        outcome = "unfinished" if budget else error_outcome(error)
        failure = dict(type=type(error).__name__, message=str(error),
            attempted_move=obs.placed_total + len(records) + 1)
        emit(dict(event="failure", outcome=outcome, **failure))
    finally:
        final = process_sample(processes)
        if backend:
            backend.close()
    success_move = first["move"] if outcome == "success" else None
    cpu = {k: v["cpu_seconds"] - cpu_start[k]["cpu_seconds"]
        if v["cpu_seconds"] is not None and cpu_start.get(k, {}).get("cpu_seconds") is not None else None
        for k, v in final.items()}
    return dict(start_t=obs.placed_total, continuation_placements=len(records),
        outcome=outcome, complete=outcome != "unfinished", failure=failure,
        first_main_move=first["move"] if first else None,
        first_main_chain=first["chain"] if first else None, success_move=success_move,
        success={str(h): bool(success_move is not None and success_move <= h) for h in (30, 35, 40)},
        cleanup_1_3=sum(1 <= r["chain"] <= 3 for r in records),
        sub10_bins={f"{lo}_{hi}": sum(lo <= r["chain"] <= hi for r in records)
                    for lo, hi in ((1, 3), (4, 6), (7, 9))},
        popped_colored=sum(r["popped_colored"] for r in records),
        discarded=sum(r["discarded"] for r in records),
        timings_ms=timings, choose_count=request_count, wall_seconds=time.perf_counter() - begin_trial,
        cpu_seconds_by_process=cpu, peak_working_set_bytes={k: v["peak_bytes"] for k, v in final.items()},
        final_geometry=records[-1]["after_geometry"] if records else geometry(obs.field))


def select_arm(rows, has_alternate):
    if not has_alternate:
        return "a0"
    by = {arm: [r for r in rows if r["arm"] == arm] for arm in ("a0", "a1")}
    if any(len(v) != 4 or not all(r["complete"] for r in v) for v in by.values()):
        return "a0"
    successes = {arm: sum(r["success"]["40"] for r in rr) for arm, rr in by.items()}
    unsafe = {arm: sum(r["outcome"] in ("dead", "nomove") for r in rr) for arm, rr in by.items()}
    return "a1" if successes["a1"] > successes["a0"] and unsafe["a1"] <= unsafe["a0"] else "a0"
