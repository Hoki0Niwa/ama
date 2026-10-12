"""Deadline boundaries and parity against the real frozen reference solver."""
from dataclasses import replace
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import EMPTY, LegacyBackend, Observation
from fever_battle.first40_deadline_backend import DeadlineBackend
from fever_battle.worker import JsonProcess
from tools.bench_fever_first40_deadline import gate, observations, read_steps, stable


class ContractTests(unittest.TestCase):
    def test_disabled_delegates_without_reply_changes(self):
        backend = DeadlineBackend.__new__(DeadlineBackend)
        backend.enabled = False; backend.depth = 8
        obs = Observation(tuple(EMPTY), ("2:RR",) * 3, "raffina", 0, 0, 0, 0)
        reply = dict(x=0, r="U", benchmark_diagnostics=dict(capacity={}))
        with patch.object(LegacyBackend, "choose", return_value=reply) as delegate:
            self.assertIs(backend.choose(obs), reply)
            delegate.assert_called_once_with(obs)

    def test_invalid_clock_and_post_main_rejected_before_native(self):
        backend = DeadlineBackend.__new__(DeadlineBackend); backend.enabled = True
        obs = Observation(tuple(EMPTY), ("2:RR",) * 3, "raffina", 39, 0, 0, 0)
        for t in (-1, 40, True, 1.5):
            with self.assertRaisesRegex(ValueError, "placed_total"):
                backend.choose(replace(obs, placed_total=t))
        for maximum in (10, 15, -1):
            with self.assertRaisesRegex(ValueError, "first mainline"):
                backend.choose(replace(obs, normal_chain_max=maximum))
        with self.assertRaisesRegex(ValueError, "NEXT2"):
            backend.choose(replace(obs, visible=("2:RR",)))

    def test_development_gate_rejects_zero_gain_and_lost_success(self):
        def row(ch, seed, label, good):
            return dict(character=ch, seed=seed, backend=label,
                success={"40": good}, outcome="success" if good else "no_mainline")
        rows=[row("raffina", 1, "b0", False), row("raffina", 1, "b1", False)]
        self.assertFalse(gate(rows, True)["pass_to_additional_development"])
        rows[1] = row("raffina", 1, "b1", True)
        self.assertTrue(gate(rows, True)["pass_to_additional_development"])
        rows += [row("rafisol", 2, "b0", True), row("rafisol", 2, "b1", False)]
        self.assertFalse(gate(rows, True)["pass_to_additional_development"])
        self.assertFalse(gate(rows, False)["pass_to_additional_development"])


@unittest.skipUnless(os.environ.get("AMA_TEST_F40_REFERENCE"), "requires frozen research native")
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = Path(os.environ["AMA_TEST_F40_REFERENCE"])
        cls.steps = read_steps(ROOT / "data/fever/baselines/2026-10-12-f40-diagnostics/b0-commit/steps.jsonl")
        cls.observations = {(r["character"], r["seed"], r["move"]): o for r, o in observations(cls.steps)}

    def backend(self, enabled):
        b = DeadlineBackend(self.native, ROOT / "config.json", enabled)
        self.addCleanup(b.close)
        return b

    def test_off_full_reply_parity_with_legacy(self):
        legacy = LegacyBackend(self.native, ROOT / "config.json"); self.addCleanup(legacy.close)
        off = self.backend(False)
        for key in (("raffina",31001,1), ("raffina",31001,30),
                    ("raffina",31002,38), ("rafisol",31002,40), ("rafisol",31020,26)):
            obs = self.observations[key]
            self.assertEqual(stable(legacy.choose(obs)), stable(off.choose(obs)))

    def test_real_depth_and_all_request_ranges_at_boundaries(self):
        capped = self.backend(True)
        for t, depth, visible in ((32,8,3), (33,7,3), (37,3,3), (38,2,2), (39,1,1)):
            obs = replace(self.observations["rafisol",31002,40], placed_total=t,
                          dropset_index=39, moves_since_chain=0)
            capped.engine.normal_build_cache = None
            reply = capped.choose(obs)
            diag = capped.last_diagnostics
            self.assertEqual((diag["effective_depth_limit"],diag["visible_count_searched"]), (depth,visible))
            self.assertFalse(diag["violations"])
            self.assertLessEqual(max(reply["search_virtual_depths"]),depth)
            self.assertLessEqual(reply.get("fire_moves",0),40-t)
            self.assertLessEqual(reply["benchmark_diagnostics"]["capacity"].get("available_moves",0),40-t)
            self.assertEqual({c["op"] for c in diag["native_calls"]}, {"solo","normal_capacity"})
            self.assertTrue(all(len(c["queue"])==visible for c in diag["native_calls"]))
            self.assertEqual(obs.visible, self.observations["rafisol",31002,40].visible)

    def test_all_piece_shapes_use_native_physics_and_preserve_phase(self):
        with JsonProcess([self.native], cwd=ROOT) as environment:
            queue = environment.ask(dict(op="queue",character="raffina",seed=1,count=20))["queue"]
            capped = self.backend(True)
            # Pair, both triples, QUAD and BIG; t independent of cycle position.
            self.assertEqual({queue[i][0] for i in (0,2,5,9,15)}, {"2","L","J","4","0"})
            for index in (0,2,5,9,15):
                obs = Observation(tuple(EMPTY),tuple(queue[index:index+3]),"raffina",39,index,0,0)
                reply = capped.choose(obs)
                tr = environment.ask(dict(op="transition",field=list(EMPTY),piece=queue[index],x=reply["x"],r=reply["r"]))
                self.assertEqual(reply["next_field"],tr["field"])
                self.assertEqual(reply["next_chain"],len(tr["links"]))
                calls = [c for c in capped.last_diagnostics["native_calls"] if c["op"]=="solo"]
                self.assertEqual(calls[0]["dropset_index"],index)
                if queue[index][0]=="0": self.assertIn(reply["color"],"RYGB")

    def test_expired_visible_colors_and_unobserved_future_do_not_change_last_move(self):
        capped = self.backend(True)
        obs = self.observations["rafisol",31002,40]
        first = stable(capped.choose(obs))
        changed = tuple([obs.visible[0]]+[p.replace("R","Y").replace("B","G") for p in obs.visible[1:]])
        capped.engine.normal_build_cache = None
        self.assertEqual(first, stable(capped.choose(replace(obs,visible=changed))))
        self.assertTrue(all(c["queue"]==[obs.visible[0]] for c in capped.last_diagnostics["native_calls"]))

    def test_clock_and_cap_prevent_cache_reuse_after_cleanup(self):
        capped = self.backend(True)
        obs = replace(self.observations["rafisol",31002,40],placed_total=38,moves_since_chain=0)
        capped.choose(obs)
        key_before = capped.engine.normal_build_cache[0]
        capped.choose(replace(obs,placed_total=39))
        self.assertNotEqual(key_before,capped.engine.normal_build_cache[0])
        self.assertEqual(capped.last_diagnostics["remaining_before"],1)
        self.assertTrue(any(c["op"]=="solo" for c in capped.last_diagnostics["native_calls"]))

    def test_real_same_observation_independent_of_environment_hidden_seed(self):
        # Environments differ beyond the observation. They never reach the backend.
        obs = self.observations["raffina",31002,38]
        replies=[]
        for seed in (1,999):
            with JsonProcess([self.native], cwd=ROOT) as environment:
                hidden=environment.ask(dict(op="queue",character="raffina",seed=seed,count=43))["queue"]
                self.assertEqual(len(hidden),43)
                capped = self.backend(True)
                replies.append(stable(capped.choose(obs)))
                self.assertEqual(set(Observation.__dataclass_fields__),
                    {"field","visible","character","placed_total","dropset_index","moves_since_chain","normal_chain_max"})
        self.assertEqual(replies[0],replies[1])


if __name__ == "__main__":
    unittest.main()
