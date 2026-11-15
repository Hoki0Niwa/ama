"""A seed line that waits for puyos is weighed by the shapes of the character's cycle."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'test'))
from fever_fixtures import NATIVE, seed3
from fever_battle.model import Scoring
from fever_battle.timing import ChainTiming
from fever_battle.worker import JsonProcess


def seed_request(**extra):
    score = Scoring()
    base = dict(op='seed_search', field=seed3(), queue=['2:GY'], confirmed=0, unconfirmed=0, held_pending=0,
                remainder=0, garbage_phase=0, target_point=120, remaining_frames=900, seed_chain=3,
                safety_frames=8, count_chain_frames=True, width=64, max_nodes=8000,
                timing=ChainTiming.for_mode('fever').native(),
                powers=score.data['characters']['raffina']['fever'], bonuses=score.data['bonuses'])
    return {**base, **extra}


class SeedShapeOddsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = JsonProcess([NATIVE], cwd=ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.native.ask(dict(op='dropset_override', clear_all=True))
        cls.native.close()

    def waiting(self, **extra):
        # The best line that pops nothing, on a seed that the visible piece could fire.
        return self.native.ask(seed_request(width=250, max_nodes=0, **extra))['alternatives']['no_pop']['expected_points']

    def cycle(self, pattern):
        self.native.ask(dict(op='dropset_override', character='arle', pattern=pattern))
        return self.waiting(character='arle', dropset_index=0)

    def test_all_pairs_are_the_same_as_no_character(self):
        self.assertEqual(self.cycle('2' * 16), self.waiting())

    def test_a_big_puyo_coming_makes_waiting_worth_more(self):
        pairs = self.cycle('2' * 16)
        self.assertGreater(self.cycle('20' + '2' * 14), pairs)
        self.assertGreater(self.cycle('0' * 16), self.cycle('20' + '2' * 14))

    def test_a_special_piece_read_from_the_cycle_position(self):
        coming = self.cycle('20' + '2' * 14)
        self.assertEqual(coming, self.waiting(character='arle', dropset_index=0))
        self.assertLess(self.waiting(character='arle', dropset_index=3), coming)


if __name__ == '__main__':
    unittest.main()
