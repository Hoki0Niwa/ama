"""A placement that pops something small and stands on the trigger of the main chain is charged the links it buries.

Board: AI 2, round-44 of the bridge's 2026-10-14 overnight log (doc/OVERNIGHT_LOG_ANALYSIS_2026-10-14.md), a
12 chain held with the opponent's 11 chain under way. 3D pops 2 and leaves 1; it was charged 0 because the
loss was measured from the board after the piece stood on the trigger. The opponent's remaining links are
synthetic (tools/investigate_main_keep.py `events`); the board, queue and pending count are logged.
"""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test'), str(ROOT/'tools')]
from fever_fixtures import NATIVE, SOLO
from fever_battle import tactics
from fever_battle.mode_engine import ModeBattleEngine
from investigate_main_keep import events

BOARD = '....../.....G/.Y...G/YG..YG/RYG.GR/BRY.GY/YGG.RY/BGRRGB/GBRYRB/YGGBBY/YBGBYR/BBYGGR/GGBBGR/GRRRBB'
QUEUE = ['2:BG', 'J:RRR', '4:GGBB']


class ClearBurialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def test_a_small_clear_that_buries_the_main_is_charged(self):
        native = self.engine.native
        rows = BOARD.split('/')
        held = native.ask(dict(op='holding', field=rows))['longest']
        self.assertEqual(held, 12)
        own = dict(character='ally', field=rows, queue=QUEUE, confirmed=0, unconfirmed=3, remainder=0,
                   garbage_phase=0, gauge=0, piece_id=0, mode_generation=0, normal_chain_max=0)
        policy = dict(self.engine.policy['normal_tactics'], budget_ms=0)
        forecast = tactics.evaluate(native, self.engine.scoring, own, 120, 1, policy,
                                    enemy_events=events(240, 825), enemy=dict(mode='normal', gauge=0), pace=60).forecast
        placed = native.ask(dict(op='placements', field=rows, piece=QUEUE[0]))['placements']
        left = {(p['x'], p['r']): native.ask(dict(op='holding', field=p['field']))['longest']
                for p in placed if not p['dead']}
        small_burying = [c for c in forecast['candidates']
                         if 0 < c['chain'] <= 3 and left.get((c['x'], c['r']), held) <= held - 4]
        self.assertTrue(small_burying)                      # 3D is one
        for c in small_burying:
            # the links the clear fires and cancels are not losses (when it is due); the ones it buries are
            self.assertGreaterEqual(c['main_links_lost'], held - left[(c['x'], c['r'])] - c['chain'], (c['x'], c['r']))


if __name__ == '__main__':
    unittest.main()
