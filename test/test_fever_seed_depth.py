"""The seed search past the visible pieces: the normal builder's virtual queues, a visible plan returned."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'test'))
from fever_fixtures import NATIVE, SOLO, side, request, seed3
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.seed_solver import SeedSolver
from fever_battle.model import Scoring
from fever_battle.timing import ChainTiming
from fever_battle.worker import JsonProcess


def seed_request(**extra):
    score = Scoring()
    base = dict(op='seed_search', field=seed3(), queue=['2:RY', '2:GB', '2:YG'],
                confirmed=0, unconfirmed=0, held_pending=0, remainder=0, garbage_phase=0,
                target_point=120, remaining_frames=900, seed_chain=3, safety_frames=8, count_chain_frames=True,
                width=64, max_nodes=8000, timing=ChainTiming.for_mode('fever').native(),
                powers=score.data['characters']['raffina']['fever'], bonuses=score.data['bonuses'])
    return {**base, **extra}


class SeedDepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = JsonProcess([NATIVE], cwd=ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.native.close()

    def test_without_depth_only_the_visible_pieces_are_read(self):
        result = self.native.ask(seed_request())
        self.assertEqual((result['beam_depth'], result['virtual_count'], result['virtual_values']), (3, 0, []))
        self.assertFalse(result['virtual_line_truncated'])

    def test_depth_reads_six_virtual_queues_and_returns_a_visible_plan(self):
        result = self.native.ask(seed_request(beam_depth=8, width=20, max_nodes=0, character='raffina', dropset_index=0))
        self.assertEqual((result['beam_depth'], result['virtual_count'], len(result['virtual_values'])), (8, 6, 6))
        self.assertLessEqual(len(result['path']), 3)
        self.assertEqual(result['searched_visible'], 3)
        # The first move is a real placement of the visible piece.
        first = result['choice']
        after = self.native.ask(dict(op='transition', field=seed3(), piece='2:RY', x=first['x'], r=first['r']))
        self.assertEqual(after['field'], first['field'])
        self.assertEqual(result['path'][-1]['expected_points'], sum(result['virtual_values']) // 6)

    def test_depth_needs_the_character_and_its_cycle_position(self):
        with self.assertRaises(Exception):
            self.native.ask(seed_request(beam_depth=8))
        with self.assertRaises(Exception):
            self.native.ask(seed_request(beam_depth=8, character='nobody', dropset_index=0))
        with self.assertRaises(Exception):
            self.native.ask(seed_request(beam_depth=2, character='raffina', dropset_index=0))  # under the visible count

    def test_no_node_limit_reads_every_line_of_the_width(self):
        result = self.native.ask(seed_request(max_nodes=0, width=1000))
        self.assertFalse(result['cutoff'])

    def test_the_seed_search_is_never_narrowed(self):
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        try:
            message = dict(seed_options=dict(width=250, depth=16, max_nodes=0))
            for cold in (True, False):
                engine.cold_spawn = cold
                self.assertEqual(engine._seed_options(message, None, None)[0], dict(width=250, depth=16, max_nodes=0))
            self.assertEqual(message['seed_options']['width'], 250)    # the request is not changed
        finally:
            engine.close()

    def test_the_engine_passes_depth_from_seed_options(self):
        SeedSolver.validate_options(dict(width=50, depth=8, max_nodes=0))
        with self.assertRaises(ValueError):
            SeedSolver.validate_options(dict(depth=65))
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        try:
            message = request(side('fever', seed3(), ['2:RY', '2:GG']))
            message['seed_options'] = dict(width=20, depth=8, max_nodes=0)
            reply = engine.answer(message)
            self.assertEqual(reply['seed_forecast']['beam_depth'], 8)
            self.assertEqual(reply['seed_forecast']['virtual_count'], 6)
        finally:
            engine.close()


if __name__ == '__main__':
    unittest.main()
