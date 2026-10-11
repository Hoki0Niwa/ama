"""Meaningful termination/denominator/isolation tests; no new search algorithm."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import (EMPTY, Observation, geometry, normalize_step,
    paired_comparison, run_trial, summarize, terminal, trial_result)


def steps(events, limit=40, dead_at=None):
    return [dict(move=m, chain=events.get(m, 0), dead=m == dead_at,
        popped_colored=4 * events.get(m, 0), discarded=0, elapsed_ms=float(m),
        after_geometry=geometry(EMPTY)) for m in range(1, limit + 1)]


def evaluate(events, limit=40, dead_at=None):
    return trial_result("raffina", 1, "legacy", steps(events, limit, dead_at))


class First40ContractTests(unittest.TestCase):
    def test_first_short_main_absorbs_later_success(self):
        result = evaluate({29: 14, 35: 15})
        self.assertEqual((result["outcome"], result["placed_moves"]), ("first_below_target", 29))
        self.assertFalse(any(result["success"].values()))

    def test_40_inclusive_41_excluded_and_secondary_boundaries(self):
        for m, expected in ((30, [True, True, True]), (35, [False, True, True]),
                            (40, [False, False, True]), (41, [False, False, False])):
            row = evaluate({m: 15}, limit=41)
            self.assertEqual(list(row["success"].values()), expected)
            self.assertLessEqual(row["placed_moves"], 40)

    def test_cleanup_and_4_to_9_continue_absolute_clock(self):
        row = evaluate({17: 3, 18: 9, 40: 15})
        self.assertEqual(row["success_move"], 40)
        self.assertEqual(row["cleanup_1_3"], 1)
        self.assertEqual(row["sub10_bins"], {"1_3": 1, "4_6": 0, "7_9": 1})
        self.assertEqual(row["sub10_fires"][1]["chain"], 9)

    def test_dead_is_failure_even_with_15_and_in_denominator(self):
        dead = evaluate({30: 15}, dead_at=30)
        good = evaluate({30: 15})
        self.assertEqual(dead["outcome"], "dead")
        self.assertFalse(dead["success"]["40"])
        metric = summarize([dead, good])["legacy/raffina"]["metrics"]["P15_first@40"]
        self.assertEqual((metric["successes"], metric["trials"], metric["rate"]), (1, 2, .5))

    def test_nomove_timeout_error_factory_failures_count(self):
        for error, outcome in ((ValueError("no placement survives"), "nomove"),
                (TimeoutError("deadline"), "timeout"), (RuntimeError("closed"), "engine_error")):
            def broken(c, s):
                raise error
            emitted = []
            result = run_trial("raffina", 2, "legacy", lambda: None, broken, emitted.append)
            self.assertEqual(result["outcome"], outcome)
            self.assertEqual(result["placed_moves"], 0)
            self.assertFalse(result["success"]["40"])
            self.assertEqual(emitted[0]["event"], "failure")
            self.assertEqual(summarize([result])["legacy/raffina"]["n"], 1)

    def test_live_balance_uses_transition_not_solver_reply(self):
        field = ["......"] * 13 + ["RR...."]
        record = dict(move=1, queue=["2:RR", "2:YY", "L:BBR"], before=list(EMPTY),
            after=field, links=[], discarded=0)
        row = normalize_step(record)
        self.assertEqual(row["input_colored"], 2)
        self.assertEqual(row["after_geometry"]["margin_remaining"], 70)
        with self.assertRaisesRegex(ValueError, "balance mismatch"):
            normalize_step(dict(record, discarded=1))
        old = normalize_step(dict(record, discarded=1), historical=True)
        self.assertEqual((old["legacy_reply_discarded"], old["discarded"]), (1, 0))

    def test_popped_cells_and_signed_capacity(self):
        before = ["......"] * 12 + ["RR....", "RR...."]
        record = dict(move=2, queue=["2:YY", "2:YY", "L:BBR"], before=before,
            after=["......"] * 13 + ["YY...."], links=[dict(groups=[4], colors=1)], discarded=0)
        self.assertEqual(normalize_step(record)["popped_colored"], 4)
        self.assertEqual(geometry(["RRRRRR"] * 14)["static_remaining"], -10)

    def test_noncontiguous_prefix_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-contiguous"):
            trial_result("raffina", 1, "legacy", steps({}, 2)[1:])

    def test_adapter_interface_does_not_contain_environment_seed_or_future(self):
        fields = set(Observation.__dataclass_fields__)
        self.assertFalse(fields & {"seed", "queue", "future", "hidden"})
        self.assertIn("placed_total", fields)

    def test_runner_stops_at_40_and_cleanup_does_not_reset_clock(self):
        seen, emitted = [], []
        def transition(field, move):
            chain = {17: 1, 40: 15}.get(move, 0)
            count = sum(c != "." for row in field for c in row) + 2 - 4 * chain
            flat = "." * (84 - count) + "R" * count
            after = [flat[i:i + 6] for i in range(0, 84, 6)]
            return dict(field=after, links=[dict(groups=[4], colors=1)] * chain, discarded=0, dead=False)
        class Environment:
            def visible(self, t): return ("2:RR",) * 3
            def transition(self, field, piece, decision): return transition(field, len(seen))
            def processes(self): return {}
            def close(self): pass
        class Solver:
            def choose(self, observation):
                seen.append(observation)
                tr = transition(observation.field, observation.placed_total + 1)
                return dict(x=0, r="U", next_field=tr["field"], next_chain=len(tr["links"]))
            def processes(self): return {}
            def close(self): pass
        result = run_trial("raffina", 1, "fake", Solver, lambda c, s: Environment(), emitted.append)
        self.assertEqual(result["success_move"], 40)
        self.assertEqual(len(seen), 40)
        self.assertEqual((seen[17].placed_total, seen[17].moves_since_chain), (17, 0))
        self.assertTrue(all(len(observation.visible) == 3 for observation in seen))

    def test_equal_visible_observation_independent_of_hidden_queue(self):
        decisions = []
        class Environment:
            def __init__(self, hidden): self.private_queue = ["2:RR"] * 3 + [hidden] * 40
            def visible(self, t): return tuple(self.private_queue[t:t+3])
            def processes(self): return {}
            def close(self): pass
            def transition(self, field, piece, decision):
                decisions.append(decision)
                raise ValueError("stop after observing first decision")
        class Solver:
            def choose(self, observation):
                return dict(x=len(observation.visible), r="U", next_field=[], next_chain=0)
            def processes(self): return {}
            def close(self): pass
        for hidden in ("2:YY", "4:BB"):
            run_trial("raffina", 999, "fake", Solver,
                lambda c, s: Environment(hidden), lambda row: None)
        self.assertEqual(decisions[0], decisions[1])

    def test_paired_denominator_and_reference_preserve_input_order(self):
        old = evaluate({35: 15}); old["backend"] = "z_old"
        new = evaluate({29: 14}); new["backend"] = "a_new"
        result = paired_comparison([old, new])["z_old->a_new/raffina"]
        self.assertEqual((result["gains"], result["losses"], result["paired_difference"]), (0, 1, -1))
        new["seed"] = 2
        with self.assertRaisesRegex(ValueError, "identical seed sets"):
            paired_comparison([old, new])

    def test_historical_baseline_and_no_overwrite(self):
        original = ROOT / "data/fever/baselines/2026-10-11-chain15-research/current-mode.json"
        if not original.exists():
            self.skipTest("historical dataset not present in this checkout")
        with tempfile.TemporaryDirectory(dir=ROOT / "bin") as temp:
            output = Path(temp) / "replay"
            command = [sys.executable, str(ROOT / "tools/bench_fever_first40.py"), "replay",
                "--experiment", str(original), "--output", str(output)]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads((output / "results.json").read_text(encoding="utf-8"))
            for character, expected in (("raffina", [1, 6, 6]), ("rafisol", [2, 4, 5])):
                summary = report["summary"][f"legacy_saved/{character}"]
                self.assertEqual(summary["n"], 24)
                self.assertEqual([summary["metrics"][f"P15_first@{h}"]["successes"]
                    for h in (30, 35, 40)], expected)
            before = (output / "results.json").read_bytes()
            repeated = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("FileExistsError", repeated.stderr)
            self.assertEqual(before, (output / "results.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
