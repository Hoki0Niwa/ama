"""Research-only first-mainline evaluator. Does not change live engine policy.

The environment owns the seed and hidden queue. Backends receive exactly three
pieces and observable history; only executed transitions determine success.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import math
import statistics
import time
from typing import Protocol

from .model import EMPTY, ROOT
from .worker import JsonProcess

HORIZON = 40
MAINLINE = 10
TARGET = 15
SCHEMA = "ama.first40.v1"


@dataclass(frozen=True)
class Observation:
    field: tuple[str, ...]
    visible: tuple[str, ...]
    character: str
    placed_total: int
    dropset_index: int
    moves_since_chain: int
    normal_chain_max: int


class Backend(Protocol):
    def choose(self, observation: Observation) -> dict: ...
    def processes(self) -> dict: ...
    def close(self) -> None: ...


def normal_side(character):
    return dict(character=character, field=list(EMPTY), mode="normal", gauge=0,
        observed_frame=0, phase="controllable", moves_since_chain=0,
        dropset_index=0, piece_id=0, queue=[], confirmed=0, unconfirmed=0,
        remainder=0, garbage_phase=None, garbage_phase_status="unknown",
        mode_generation=0, seed_id=0, prepared_frames=900, remaining_frames=0,
        clock_running=False, seed_base=5, seed_chain=5, stored_field=None,
        normal_confirmed=0, normal_unconfirmed=0, fever_confirmed=0,
        fever_unconfirmed=0, normal_chain_max=0)


class LegacyBackend:
    """Unmodified _normal_options / _solo_build path, not tactical answer().

    A future backend implements choose(Observation) with the same reply fields
    x/r/next_field/next_chain. No future/seed argument is part of this interface.
    """
    def __init__(self, native, config, width=250, depth=8):
        from .mode_engine import ModeBattleEngine
        self.engine = ModeBattleEngine.__new__(ModeBattleEngine)
        try:
            self.engine.__init__(native, ROOT / "bin/fever/fever.exe", config)
        except Exception:
            if hasattr(self.engine, "native"):
                self.engine.native.close()
            raise
        self.engine.build_match = "first40"
        self.width, self.depth = width, depth
        self.enemy = None

    def choose(self, observation):
        if len(observation.visible) != 3:
            raise ValueError("backend requires current + NEXT2")
        own = normal_side(observation.character)
        own.update(field=list(observation.field), queue=list(observation.visible),
            dropset_index=observation.dropset_index, piece_id=observation.placed_total,
            observed_frame=observation.placed_total,
            moves_since_chain=observation.moves_since_chain,
            normal_chain_max=observation.normal_chain_max)
        if self.enemy is None:
            self.enemy = normal_side(observation.character)
            self.enemy["queue"] = list(observation.visible)
        request = dict(self=own, enemy=self.enemy, gauge_gain_on_offset=1,
            solo_options=dict(trigger=15, beam_width=self.width, beam_depth=self.depth))
        options = self.engine._normal_options(request, own)
        result = self.engine._solo_build(own, options)
        return dict(result, benchmark_diagnostics=dict(options=deepcopy(options),
            capacity=deepcopy(getattr(self.engine, "normal_capacity", {}))))

    def processes(self):
        return {"backend_native": self.engine.native.process}

    def close(self):
        self.engine.close()


class NativeEnvironment:
    def __init__(self, native, character, seed):
        self.worker = JsonProcess([native], cwd=ROOT)
        try:
            self.queue = self.worker.ask(dict(op="queue", character=character,
                seed=seed, count=HORIZON + 3))["queue"]
            if len(self.queue) < HORIZON + 2:
                raise ValueError("incomplete environment queue")
        except Exception:
            self.worker.close()
            raise

    def visible(self, placed_total):
        return tuple(self.queue[placed_total:placed_total + 3])

    def transition(self, field, piece, decision):
        return self.worker.ask(dict(op="transition", field=list(field), piece=piece,
            x=decision["x"], r=decision["r"]))

    def processes(self):
        return {"environment_native": self.worker.process}

    def close(self):
        self.worker.close()


def occupied(field):
    return sum(c != "." for row in field for c in row)


def colored(field):
    return sum(c in "RYGB" for row in field for c in row)


def piece_mass(piece):
    return {"2": 2, "L": 3, "J": 3, "4": 4, "0": 4}[piece[0]]


def geometry(field, margin=1):
    heights = [sum(row[x] != "." for row in field) for x in range(6)]
    # Static capacity for surviving settled boards; not a count of legal moves.
    return dict(occupied=occupied(field), colored=colored(field), heights=heights,
        static_capacity=74, static_remaining=74 - occupied(field),
        margin_capacity=74 - 2 * margin,
        margin_remaining=74 - 2 * margin - occupied(field),
        death_column_headroom=[11 - heights[x] for x in (2, 3)],
        margin_headroom=[11 - margin - heights[x] for x in (2, 3)])


def normalize_step(record, historical=False):
    """Decorate live or historical executed transitions without editing inputs."""
    record = deepcopy(record)
    chain = len(record["links"])
    if record.get("chain", chain) != chain:
        raise ValueError("chain differs from executed links")
    record["chain"] = chain
    popped = sum(sum(link["groups"]) for link in record["links"])
    mass = piece_mass(record["queue"][0])
    inferred = occupied(record["before"]) + mass - popped - occupied(record["after"])
    if inferred < 0:
        raise ValueError("negative cell balance")
    if not historical and inferred != record["discarded"]:
        raise ValueError("transition cell balance mismatch")
    # Old solver-reply discarded may be stale. Preserve it separately and mark
    # inference explicitly; live records must use actual transition.discarded.
    if historical:
        record["legacy_reply_discarded"] = record.get("discarded")
        record["discarded"] = inferred
        record["discarded_source"] = "cell_balance_inference"
    else:
        record["discarded_source"] = "executed_transition"
    record.update(popped_colored=popped, input_colored=mass,
        cell_balance_ok=True, before_geometry=geometry(record["before"]),
        after_geometry=geometry(record["after"]), placed_total=record["move"],
        remaining=HORIZON - record["move"])
    return record


def terminal(record):
    # User contract: deaths are failures even if an actual 15 also occurred.
    if record.get("dead"):
        return "dead"
    if record["chain"] >= MAINLINE:
        return "success" if record["chain"] >= TARGET else "first_below_target"
    if record["move"] == HORIZON:
        return "no_mainline"
    return None


def trial_result(character, seed, backend, records, outcome=None, failure=None, **extra):
    prefix = []
    stop = None
    for record in records:
        if record["move"] != len(prefix) + 1:
            raise ValueError("non-contiguous trial")
        if record["move"] > HORIZON:
            break
        prefix.append(record)
        stop = terminal(record)
        if stop:
            break
    outcome = stop or outcome or "incomplete"
    first = next((r for r in prefix if r["chain"] >= MAINLINE), None)
    success = outcome == "success"
    move = first["move"] if success else None
    small = [r for r in prefix if 1 <= r["chain"] <= 3]
    nonmain = [r for r in prefix if 1 <= r["chain"] <= 9]
    return dict(character=character, seed=seed, backend=backend, outcome=outcome,
        placed_moves=len(prefix), first_main_move=first["move"] if first else None,
        first_main_chain=first["chain"] if first else None, success_move=move,
        success={str(h): bool(success and move <= h) for h in (30, 35, 40)},
        cleanup_1_3=len(small), cleanup_popped=sum(r["popped_colored"] for r in small),
        sub10_fires=[dict(move=r["move"], chain=r["chain"], popped=r["popped_colored"])
                     for r in nonmain],
        sub10_bins={f"{lo}_{hi}": sum(lo <= r["chain"] <= hi for r in prefix)
                    for lo, hi in ((1, 3), (4, 6), (7, 9))},
        popped_colored=sum(r["popped_colored"] for r in prefix),
        discarded=sum(r["discarded"] for r in prefix),
        final_geometry=prefix[-1]["after_geometry"] if prefix else geometry(EMPTY),
        timings_ms=[r["elapsed_ms"] for r in prefix if r.get("elapsed_ms") is not None],
        first_main_popped=first["popped_colored"] if first else None,
        dead=any(r.get("dead", False) for r in prefix), failure=failure, **extra)


def error_outcome(error):
    if isinstance(error, TimeoutError):
        return "timeout"
    if str(error) == "no placement survives":
        return "nomove"
    return "engine_error"


def run_trial(character, seed, label, backend_factory, environment_factory, emit):
    """Factory failures also yield a denominator entry; no retry cherry-picking."""
    from .first40_provenance import process_sample
    records, backend, environment = [], None, None
    outcome, failure = None, None
    processes, cpu_start, final_sample = {}, {}, {}
    cpu_wall_start = None
    started = time.perf_counter()
    failed_think_ms = None
    try:
        environment = environment_factory(character, seed)
        backend = backend_factory()
        processes = {**environment.processes(), **backend.processes()}
        cpu_start = process_sample(processes)
        cpu_wall_start = time.perf_counter()
        field = tuple(EMPTY)
        since, maximum = 0, 0
        for t in range(HORIZON):
            observation = Observation(field, environment.visible(t), character, t, t, since, maximum)
            sample_before = process_sample(processes)
            begin = time.perf_counter()
            try:
                decision = backend.choose(observation)
            except Exception:
                failed_think_ms = (time.perf_counter() - begin) * 1000
                raise
            elapsed = (time.perf_counter() - begin) * 1000
            sample_after = process_sample(processes)
            transition = environment.transition(field, observation.visible[0], decision)
            if decision["next_field"] != transition["field"] or decision["next_chain"] != len(transition["links"]):
                raise ValueError("solver prediction differs from executed transition")
            diagnostics = decision.get("benchmark_diagnostics", {})
            record = normalize_step(dict(character=character, seed=seed, backend=label,
                move=t + 1, before=list(field), queue=list(observation.visible),
                after=transition["field"], links=transition["links"],
                x=decision["x"], r=decision["r"], dead=transition["dead"],
                discarded=transition["discarded"], elapsed_ms=elapsed,
                cpu_seconds={key: (sample_after[key]["cpu_seconds"] - value["cpu_seconds"]
                    if value["cpu_seconds"] is not None and sample_after[key]["cpu_seconds"] is not None else None)
                    for key, value in sample_before.items()},
                options=diagnostics.get("options"), capacity=diagnostics.get("capacity"),
                expected_chain=decision.get("chain"), fire=decision.get("fire"),
                fire_moves=decision.get("fire_moves"),
                retained_override=decision.get("normal_main_retained", False),
                extension_override=decision.get("normal_extension_selected", False),
                search_depths=decision.get("search_virtual_depths"),
                nodes=decision.get("search_nodes"),
                diagnostics_unavailable=["geometry_witness", "root_survival", "tail_reachability"]))
            emit(record)
            records.append(record)
            outcome = terminal(record)
            if outcome:
                break
            field = tuple(transition["field"])
            since = 0 if record["chain"] else since + 1
            maximum = max(maximum, record["chain"])
    except Exception as error:
        outcome = error_outcome(error)
        failure = dict(attempted_move=len(records) + 1, type=type(error).__name__, message=str(error))
        emit(dict(event="failure", character=character, seed=seed, backend=label,
            outcome=outcome, **failure, elapsed_ms=failed_think_ms))
    finally:
        final_sample = process_sample(processes)
        cpu_wall = time.perf_counter() - cpu_wall_start if cpu_wall_start is not None else None
        for resource in (backend, environment):
            if resource is not None:
                resource.close()
    cpu = {key: (value["cpu_seconds"] - cpu_start[key]["cpu_seconds"]
        if value["cpu_seconds"] is not None and cpu_start.get(key, {}).get("cpu_seconds") is not None else None)
        for key, value in final_sample.items()}
    wall = time.perf_counter() - started
    total_cpu = sum(cpu.values()) if cpu and all(v is not None for v in cpu.values()) else None
    return trial_result(character, seed, label, records, outcome, failure,
        failed_think_ms=failed_think_ms, trial_wall_seconds=wall,
        cpu_seconds_by_process=cpu, total_cpu_seconds=total_cpu,
        cpu_window="after_initialization_to_before_shutdown",
        cpu_wall_seconds=cpu_wall,
        cpu_core_equivalents=total_cpu / cpu_wall if total_cpu is not None and cpu_wall else None,
        peak_working_set_bytes={key: value["peak_bytes"] for key, value in final_sample.items()})


def percentile(values, q):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * q) - 1)] if values else None


def wilson(k, n):
    if not n:
        return None
    z = 1.959963984540054
    denominator = 1 + z * z / n
    center = (k / n + z * z / (2 * n)) / denominator
    half = z * math.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / denominator
    return [center - half, center + half]


def summarize(runs):
    summary = {}
    for backend, character in sorted({(r["backend"], r["character"]) for r in runs}):
        rows = [r for r in runs if (r["backend"], r["character"]) == (backend, character)]
        n = len(rows)
        times = [v for r in rows for v in r["timings_ms"]]
        times += [r["failed_think_ms"] for r in rows if r.get("failed_think_ms") is not None]
        moves = sorted(r["success_move"] for r in rows if r["success_move"] is not None)
        metrics = {f"P15_first@{h}": dict(successes=sum(r["success"][str(h)] for r in rows),
            trials=n, rate=sum(r["success"][str(h)] for r in rows) / n,
            wilson95=wilson(sum(r["success"][str(h)] for r in rows), n)) for h in (30, 35, 40)}
        cpu_measured = all(r.get("total_cpu_seconds") is not None for r in rows)
        cpu_total = sum(r["total_cpu_seconds"] for r in rows) if cpu_measured else None
        cpu_wall = sum(r["cpu_wall_seconds"] for r in rows) if cpu_measured else None
        summary[f"{backend}/{character}"] = dict(n=n, metrics=metrics,
            outcomes=dict(Counter(r["outcome"] for r in rows)),
            first_main_distribution=dict(Counter(str(r["first_main_chain"]) for r in rows)),
            first13=sum(r["first_main_chain"] == 13 for r in rows),
            first14=sum(r["first_main_chain"] == 14 for r in rows),
            no_first_main=sum(r["first_main_move"] is None for r in rows),
            success_moves=moves, conditional_median_move=statistics.median(moves) if moves else None,
            all_trials_success_median_reached=2 * len(moves) >= n,
            all_trials_success_median_move=moves[math.ceil(n / 2) - 1] if 2 * len(moves) >= n else None,
            timing=dict(decisions=len(times), mean_ms=statistics.mean(times) if times else None,
                p50_ms=percentile(times, .5), p95_ms=percentile(times, .95), max_ms=max(times, default=None)),
            cleanup_relation={bucket: dict(trials=sum(test(r) for r in rows),
                successes=sum(test(r) and r["success"]["40"] for r in rows))
                for bucket, test in [("0", lambda r: r["cleanup_1_3"] == 0),
                    ("1_2", lambda r: 1 <= r["cleanup_1_3"] <= 2),
                    ("3_plus", lambda r: r["cleanup_1_3"] >= 3)]},
            total_cpu_seconds=cpu_total, cpu_window_wall_seconds=cpu_wall,
            cpu_core_equivalents=cpu_total / cpu_wall if cpu_wall else None,
            peak_working_set_bytes_by_process={name: max(r["peak_working_set_bytes"].get(name) or 0
                for r in rows) or None for name in {key for r in rows for key in r.get("peak_working_set_bytes", {})}},
            safety_or_tail_cause="unmeasured; capacity reason is observational, not a causal label")
    return summary


def paired_comparison(runs):
    labels = list(dict.fromkeys(r["backend"] for r in runs))
    result = {}
    if len(labels) < 2:
        return result
    reference = labels[0]
    for label in labels[1:]:
        for character in sorted({r["character"] for r in runs}):
            old = {r["seed"]: r for r in runs if r["backend"] == reference and r["character"] == character}
            new = {r["seed"]: r for r in runs if r["backend"] == label and r["character"] == character}
            if old.keys() != new.keys():
                raise ValueError("paired comparison requires identical seed sets")
            gains = sum(new[s]["success"]["40"] and not old[s]["success"]["40"] for s in old)
            losses = sum(old[s]["success"]["40"] and not new[s]["success"]["40"] for s in old)
            result[f"{reference}->{label}/{character}"] = dict(n=len(old), gains=gains, losses=losses,
                paired_difference=(gains - losses) / len(old),
                inference="small regression only; not a final adoption test")
    return result
