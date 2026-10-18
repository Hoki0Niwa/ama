"""The policy's margin on the normal board's nuisance check (timing.nuisance_check_margin, 2026-10-15)."""
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_battle import timing
from fever_battle.timing import ChainTiming
from fever_fixtures import NATIVE, SOLO
from fever_battle.mode_engine import ModeBattleEngine


class NuisanceMarginTests(unittest.TestCase):
    def tearDown(self):
        timing.set_normal_check_margin(0)

    def test_margin_is_added_to_the_normal_check_only(self):
        timing.set_normal_check_margin(0)
        base = ChainTiming.for_mode('normal').native()['nuisance_check_frames']
        fever = ChainTiming.for_mode('fever').native()['nuisance_check_frames']
        timing.set_normal_check_margin(10)
        self.assertEqual(ChainTiming.for_mode('normal').native()['nuisance_check_frames'], base + 10)
        self.assertEqual(ChainTiming.for_mode('fever').native()['nuisance_check_frames'], fever)

    def test_explicit_linear_costs_are_left_alone(self):
        timing.set_normal_check_margin(10)
        linear = ChainTiming(pop_frames=50, placement_frames=10, spawn_frames=0, nuisance_check_frames=0)
        self.assertFalse(linear.geometry_enabled)
        self.assertEqual(linear.native()['nuisance_check_frames'], 0)

    def test_the_engine_takes_the_margin_from_the_policy(self):
        policy = json.loads((ROOT/'data/fever/battle_policy.json').read_text(encoding='utf-8'))
        expected = policy['timing']['nuisance_check_margin']
        timing.set_normal_check_margin(0)
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        try:
            self.assertEqual(ChainTiming.for_mode('normal').check_frames, 16 + expected)
        finally:
            engine.close()


if __name__ == '__main__':
    unittest.main()
