"""2026-10-15: what makes the main chain "unready" for a disruption, and the floors of a pressed seed.

Overnight log of 2026-10-15 (doc/OVERNIGHT_LOG_ANALYSIS_2026-10-15.md, section 8): against an opponent in Fever,
hold 4-9 overpowers and hold 10+ jabs had gone once the links a piece buries were counted with the ones a
clear fires. Only fired links make the main unready (zeroing the disruption); buried links are still priced.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test'), str(ROOT/'tools')]
from fever_fixtures import NATIVE, SOLO, side, seed3
from fever_battle import tactics
from fever_battle.mode_engine import ModeBattleEngine

BOARD = '....../.....G/.Y...G/YG..YG/RYG.GR/BRY.GY/YGG.RY/BGRRGB/GBRYRB/YGGBBY/YBGBYR/BBYGGR/GGBBGR/GRRRBB'
QUEUE = ['2:BG', 'J:RRR', '4:GGBB']


class DisruptionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def test_buried_links_are_priced_but_are_not_fired_links(self):
        rows = BOARD.split('/')
        own = dict(character='ally', field=rows, queue=QUEUE, confirmed=0, unconfirmed=0, remainder=0,
                   garbage_phase=0, gauge=0, piece_id=0, mode_generation=0, normal_chain_max=0)
        policy = dict(self.engine.policy['normal_tactics'], budget_ms=0)
        forecast = tactics.evaluate(self.engine.native, self.engine.scoring, own, 120, 1, policy, enemy_events=[],
            enemy=side('fever', seed3()), pace=60, quiet=True,
            fever=dict(enemy_fever=True, enemy_reply_nuisance=272, their_end=0, disrupt_window=10000,
                       enemy_seed_level=8)).forecast
        small = [c for c in forecast['candidates'] if 0 < c['chain'] <= 3]
        self.assertTrue(small)
        for c in small:
            self.assertIn('main_links_fired', c)
            self.assertLessEqual(c['main_links_fired'], c['main_links_lost'])
        # 3D pops 2 standing on the trigger: it buries 11 links and fires none of them
        three_d = next(c for c in small if (c['x'], c['r']) == (3, 'D'))
        self.assertEqual((three_d['main_links_lost'], three_d['main_links_fired']), (11, 0))

    def test_a_timed_hit_is_not_replaced_by_the_window_build(self):
        engine = self.engine
        base = dict(decision_kind='stack', chain=0)
        own = dict(confirmed=0, mode='normal', field=BOARD.split('/'))
        cfg = dict(engine.policy['normal_tactics'], window_build=dict(hold=10, min_pieces=3))
        policy = dict(engine.policy, normal_tactics=cfg)
        for kind, expect_call in (('jab', False), ('overpower', False), ('none', True)):
            reply = dict(base, tactics_forecast=dict(choice=dict(disruption_kind=kind, projected_disrupt=1.0)))
            decision = type('D', (), dict(reply=reply))()
            with patch.object(engine, 'policy', policy), \
                 patch.object(engine, '_enemy_events', return_value=[]) as events:
                self.assertIsNone(engine._window_build({}, own, {}, {}, [], decision))
            self.assertEqual(events.called, expect_call, kind)

    def test_a_pressed_seed_needs_a_packet_worth_the_time(self):
        engine = self.engine
        own = dict(character='ally', seed_chain=5, confirmed=0, unconfirmed=0, normal_confirmed=0, normal_unconfirmed=0)
        for held, expected in ((0, None), (5, None), (29, None), (30, 'opponent_in_fever_holds_nuisance'),
                               (218, 'opponent_in_fever_holds_nuisance')):
            enemy = dict(mode='fever', character='rafisol', normal_confirmed=held, normal_unconfirmed=0, field=[])
            with patch.object(engine, 'enemy_analysis', None):
                self.assertEqual(engine._press({}, own, enemy, 120), expected, held)


if __name__ == '__main__':
    unittest.main()
