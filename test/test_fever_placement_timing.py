"""The log fields of a placement's split and the model's nuisance check (reply['arrival'], 2026-10-16)."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, request, side
from fever_battle import timing
from fever_battle.mode_engine import ModeBattleEngine


class PlacementTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_a_normal_placement_logs_its_split_and_check_time(self):
        rows = ['......'] * 11 + ['RGBY..', 'RGBY..', 'RGBYR.']
        req = request(own=side('normal', rows, ['2:RY', '2:BG', 'L:RRY']))
        reply = self.engine.answer(req)
        arrival = reply['arrival']
        for key in ('split_rows', 'split_extra', 'model_lock_in', 'model_check_in'):
            self.assertIn(key, arrival)
        table = timing.ChainTiming.for_mode('normal')
        self.assertEqual(arrival['split_extra'], table.split_extra_frames[arrival['split_rows']])
        self.assertEqual(arrival['model_check_in'], arrival['model_lock_in'] + table.check_frames)
        self.assertGreaterEqual(arrival['model_lock_in'], table.placement_frames)


if __name__ == '__main__':
    unittest.main()
