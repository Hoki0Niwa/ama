"""Fever-rule tactics: stock up until a drop is due, and end Fever without an idle fire."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'test'))
from fever_fixtures import NATIVE, SOLO, request, side, seed3, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine


class TacticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def waiting(self, **nuisance):
        own = side('normal', seed_with_small_green(), ['2:GY'])
        own.update(nuisance)
        return own

    def test_unconfirmed_attack_is_not_answered_with_the_main_chain(self):
        for phase in (0, None):
            own = self.waiting(unconfirmed=200, normal_unconfirmed=200, garbage_phase=phase)
            if phase is None:
                own['garbage_phase_status'] = 'unknown'
            reply = self.engine.answer(request(own))
            self.assertEqual(reply['reason'], 'tactics_stack')
            self.assertEqual(reply['chain'], 0)
            self.assertFalse(reply['tactics_forecast']['choice']['drop_due'])
            self.assertEqual(reply['decision_dependencies'], ['self'])

    def test_enemy_fever_chain_in_progress_is_stocked_against_until_it_ends(self):
        enemy = side('fever', ['......']*13 + ['RRR...'])
        req = request(self.waiting(), enemy)
        req['enemy_chain'] = dict(trigger_field=['......']*13 + ['RRRR..'], elapsed=0, scored_links=0,
            mode_generation=enemy['mode_generation'], seed_id=enemy['seed_id'])
        events = self.engine._enemy_events(req, enemy)
        self.assertTrue(events)
        reply = self.engine.answer(req)
        self.assertLess(reply['chain'], 3)
        self.assertIn(reply['reason'], ('tactics_stack', 'tactics_offset'))

    def test_due_drop_is_stopped_with_a_small_offset_not_the_main_chain(self):
        reply = self.engine.answer(request(self.waiting(confirmed=18, normal_confirmed=18)))
        self.assertEqual(reply['reason'], 'tactics_offset')
        self.assertEqual(reply['chain'], 1)
        self.assertEqual(reply['gauge_forecast']['gauge_after'], 1)

    def test_one_offset_from_fever_enters_at_once(self):
        own = self.waiting(gauge=6, unconfirmed=200, normal_unconfirmed=200)
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['chain'], 1)
        self.assertTrue(reply['entry_pending_after_chain'])

    def test_board_too_high_to_take_a_drop_counts_a_clear_as_due(self):
        rows = ['......']*5 + ['RYRY..', 'YRYR..']*4 + ['RYRYGB']
        own = side('normal', rows, ['2:GB'])
        own.update(unconfirmed=60, normal_unconfirmed=60)
        forecast = self.engine.answer(request(own))['tactics_forecast']
        # Nothing has been confirmed, but the board would not stand it: an
        # offset here is not an early one. (This piece pops nothing anywhere.)
        self.assertTrue(all(c['drop_due'] for c in forecast['candidates']))
        low = side('normal', seed_with_small_green(), ['2:GB'])
        low.update(unconfirmed=60, normal_unconfirmed=60)
        forecast = self.engine.answer(request(low))['tactics_forecast']
        self.assertFalse(any(c['drop_due'] for c in forecast['candidates']))

    def test_zero_gain_keeps_the_gauge_free_routine(self):
        own = self.waiting(unconfirmed=200, normal_unconfirmed=200)
        req = request(own); req['gauge_gain_on_offset'] = 0
        self.assertNotIn('tactics_forecast', self.engine.answer(req))

    def test_stacking_plays_the_chain_builder_move(self):
        own = self.waiting(unconfirmed=12, normal_unconfirmed=12)
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=5, r='U')):
            reply = self.engine.answer(request(own))
        self.assertEqual((reply['x'], reply['r'], reply['reason']), (5, 'U', 'tactics_stack'))

    def test_recovery_without_nuisance_does_not_fire_the_longest_reachable_chain(self):
        req = request(self.waiting())
        req.update(op='recover_placement', reachable_placements=[dict(x=x, r='U') for x in range(6)])
        reply = self.engine.answer(req)
        self.assertEqual(reply['chain'], 0)

    def test_enemy_chain_with_an_empty_tray_is_not_answered_with_the_main_chain(self):
        enemy = side('fever', ['......']*13 + ['RRR...'])
        for phase in (0, None):
            own = side('normal', seed_with_small_green(), ['2:GY'])
            own['garbage_phase'] = phase
            if phase is None:
                own['garbage_phase_status'] = 'unknown'
            req = request(own, enemy)
            req['enemy_chain'] = dict(trigger_field=['......']*13 + ['RRRR..'], elapsed=0, scored_links=0,
                mode_generation=enemy['mode_generation'], seed_id=enemy['seed_id'])
            reply = self.engine.answer(req)
            self.assertLess(reply['chain'], 3, reply['reason'])

    def ending(self, **nuisance):
        own = side('fever', ['......']*13 + ['GGG.RR'], ['2:GY'])
        own.update(seed_chain=5, seed_base=5, remaining_frames=20)
        own.update(nuisance)
        return own

    def test_fever_ends_without_a_fire_when_nothing_is_carried(self):
        reply = self.engine.answer(request(self.ending()))
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['reason'], 'fever_end_without_pointless_fire')
        self.assertTrue(reply['seed_forecast']['quiet_fever_end'])
        self.assertEqual(reply['seed_forecast']['choice']['carried_nuisance'], 0)

    def test_harmless_held_nuisance_does_not_force_a_failed_fire(self):
        reply = self.engine.answer(request(self.ending(normal_confirmed=4)))
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['seed_forecast']['choice']['carried_nuisance'], 4)

    def test_harmful_held_nuisance_keeps_the_last_offset(self):
        reply = self.engine.answer(request(self.ending(normal_confirmed=50)))
        self.assertGreater(reply['chain'], 0)
        self.assertFalse(reply['seed_forecast']['quiet_fever_end'])

    def test_stored_board_that_cannot_take_the_drop_is_not_called_harmless(self):
        own = self.ending(normal_confirmed=4)
        own['stored_field'] = ['......', '..RY..'] + ['..YR..', '..RY..']*6
        self.assertEqual(self.engine._quiet_carry_limit(own), 0)
        self.assertGreater(self.engine.answer(request(own))['chain'], 0)

    def test_fever_side_drop_is_taken_on_the_fever_board_instead_of_carried(self):
        own = self.ending(confirmed=24, fever_confirmed=24)
        own['remaining_frames'] = 60
        reply = self.engine.answer(request(own))
        first = reply['seed_forecast']['choice']
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(first['dropped'], 24)
        self.assertEqual(first['carried_nuisance'], 0)
        self.assertFalse(first['dead'])

    def test_seed_reaching_fire_is_still_made_at_the_end(self):
        own = side('fever', seed3(), ['2:RY'])
        own.update(remaining_frames=60)
        self.assertGreaterEqual(self.engine.answer(request(own))['chain'], 3)


if __name__ == '__main__':
    unittest.main()
