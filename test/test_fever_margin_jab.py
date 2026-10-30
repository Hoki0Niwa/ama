"""A single link against an opponent's Fever stays a candidate after the opening, and a recovery answers quickly."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, request, seed3, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine


class MarginJabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def decision(self, generation, rate=3):
        own = side('normal', seed_with_small_green(), ['2:GY'])
        own.update(character='arle', mode_generation=generation)
        enemy = side('fever', seed3())
        enemy.update(seed_chain=15, awaiting_seed=True, fever_entry_frame=0)
        req = request(own, enemy)
        req['target_point'] = rate
        self.engine.enemy_analysis = None
        events = self.engine._enemy_events(req, enemy)
        return self.engine._tactical_decision(req, own, enemy, rate, build=lambda: dict(x=5, r='U'))

    def test_a_single_link_is_weighed_against_a_fever_opponent_after_the_opening(self):
        opening = self.decision(0)
        after = self.decision(1)
        self.assertEqual(opening.status, after.status)
        self.assertNotEqual(after.status, 'build')
        self.assertIn(after.reply['tactics_forecast']['choice']['disruption_kind'], ('jab', 'overpower', 'main_pressure'))

    def test_a_late_observed_preparation_keeps_the_configured_seed_width(self):
        own = side('fever', seed3())
        own['queue'] = ['2:RY', '2:GB']
        req = request(own, side('fever', seed3()))
        req.update(op='prepare_observed', cold_spawn=True)
        req['seed_options']['width'] = 250
        widths = []
        solve = self.engine.seed_solver.solve

        def spy(own_, rate, count, options, **kwargs):
            widths.append(options.get('width'))
            return solve(own_, rate, count, options, **kwargs)
        with patch.object(self.engine.seed_solver, 'solve', side_effect=spy):
            reply = self.engine.answer(req)
        self.assertTrue(reply['prepared'])
        self.assertEqual(widths, [250])

    def test_a_recovery_keeps_the_configured_seed_width(self):
        own = side('fever', seed3())
        enemy = side('fever', seed3())
        placements = self.engine.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
        allowed = [dict(x=p['x'], r=p['r']) for p in placements[:3]]
        req = request(own, enemy)
        req.update(op='recover_placement', reachable_placements=allowed, target_point=30)
        req['seed_options']['width'] = 250
        widths = []
        solve = self.engine.seed_solver.solve

        def spy(own_, rate, count, options, **kwargs):
            widths.append(options.get('width'))
            return solve(own_, rate, count, options, **kwargs)
        with patch.object(self.engine.seed_solver, 'solve', side_effect=spy):
            self.engine.answer(req)
        self.assertEqual(widths, [250])


if __name__ == '__main__':
    unittest.main()
