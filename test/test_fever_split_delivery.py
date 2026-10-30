"""A longer split must not disappear into the previous pieces' cadence."""
import sys
import json
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'test'))
from fever_fixtures import NATIVE, SOLO, side, request
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply, identity, preview_prepared
from fever_battle.timing import ChainTiming
from fever_battle import tactics
from fever_battle.uncertainty import choose
from fever_battle.nuisance import link_amount


class SplitDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT / 'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def setUp(self):
        self.engine.pace = 70
        heights = [1, 8, 8, 1, 0, 0]
        rows = [''.join('RG'[(x + y) % 2] if y < h else '.'
                        for x, h in enumerate(heights)) for y in reversed(range(14))]
        self.own = side('normal', rows, ['2:BY'])
        self.own.update(unconfirmed=200, normal_unconfirmed=200)
        self.events = [dict(type='end', frame=75)]

    def evaluate(self, move):
        decision = tactics.evaluate(self.engine.native, self.engine.scoring, self.own,
            120, 1, self.engine.policy['normal_tactics'], enemy_events=self.events,
            allowed=[move], pace=70)
        return decision.forecast['choice']

    def test_split_catches_final_packet_and_kills_high_board(self):
        choice = self.evaluate(dict(x=1, r='L'))
        self.assertEqual(choice['chain'], 0)
        self.assertEqual(choice['dropped'], 30)
        self.assertFalse(choice['current_survives'])

    def test_flat_placement_finishes_before_same_packet(self):
        choice = self.evaluate(dict(x=4, r='U'))
        self.assertEqual(choice['chain'], 0)
        self.assertEqual(choice['dropped'], 0)
        self.assertTrue(choice['current_survives'])

    def test_unknown_drop_columns_also_keep_split_time(self):
        result = choose(self.engine.native, self.engine.scoring, self.own, 120,
            allowed_placements={(1, 'L')}, enemy_events=self.events, pace=70)
        self.assertEqual(result['choice']['dropped'], 30)
        self.assertTrue(result['choice']['dead'])

    def test_confirmation_at_check_is_inclusive(self):
        move = dict(x=1, r='L')
        check = self.engine._placement_timing(self.own, dict(action='place', **move))['model_check_in']
        for frame, dropped in ((check, 30), (check + 1, 0)):
            with self.subTest(frame=frame):
                self.events = [dict(type='end', frame=frame)]
                self.assertEqual(self.evaluate(move)['dropped'], dropped)

    def test_search_avoids_lethal_split_when_flat_placement_is_available(self):
        decision = tactics.evaluate(self.engine.native, self.engine.scoring, self.own,
            120, 1, self.engine.policy['normal_tactics'], enemy_events=self.events,
            allowed=[dict(x=1, r='L'), dict(x=4, r='U')], pace=70)
        self.assertEqual((decision.reply['x'], decision.reply['r']), (4, 'U'))
        self.assertFalse(decision.reply['selected_move_loses'])

    def test_preparation_and_diagnostic_use_same_split_clock(self):
        move = dict(x=1, r='L')
        timing = self.engine._placement_timing(self.own, dict(action='place', **move))
        self.assertGreater(timing['split_extra'], 0)
        self.assertEqual(timing['model_lock_in'], 42 + timing['split_extra'])
        self.assertGreater(timing['model_check_in'], 75)
        self.assertEqual(self.engine._until_next_piece(self.own, move),
                         timing['model_lock_in'] + 28)

    def test_no_pace_keeps_physical_split_duration(self):
        self.assertEqual(ChainTiming().lock_frames(33), 47)
        self.assertEqual(ChainTiming().lock_frames(0, 70), 42)

    def test_build_window_rechecks_the_actual_placement(self):
        req = request(self.own)
        req['normal_tactics'] = dict(window_build=dict(min_pieces=1, fire_pieces=0))
        placements = self.engine.native.ask(dict(op='placements', field=self.own['field'],
                                                piece=self.own['queue'][0]))['placements']
        reply = dict(x=1, r='L', decision_kind='stack', chain=0)
        decision = tactics.Decision('defense', reply)
        with patch.object(self.engine, '_enemy_events', return_value=self.events), \
             patch.object(self.engine.native, 'ask', return_value=dict(longest=10)), \
             patch.object(self.engine, '_solo_build', return_value=dict(x=1, r='L')), \
             patch.object(self.engine, '_normal_builder_reply', return_value=dict(x=1, r='L')):
            self.assertIsNone(self.engine._window_build(req, self.own, req['enemy'], {}, placements, decision))

    def counter_request(self):
        req = json.loads((ROOT / 'data/fever/golden/counter-flight-delivery.json').read_text(encoding='utf-8'))['request']
        self.engine.enemy_analysis = None
        return req

    def test_logged_last_link_retains_observed_counter_amount(self):
        req = self.counter_request()
        events = self.engine._enemy_events(req, req['enemy'])
        counter = [e for e in events if e.get('source') == 'observed_counter_flight']
        self.assertEqual([(e['frame'], e['nuisance']) for e in counter], [(4, 46)])
        self.engine.margin = {}
        self.assertEqual(self.engine._delivered_until(req, req['self'], req['enemy'], 3), (0, 0))
        self.assertEqual(self.engine._delivered_until(req, req['self'], req['enemy'], 60), (46, 0))

    def test_logged_split_catches_return_even_when_all_links_are_scored(self):
        req = self.counter_request()
        own = {**req['self'], 'queue': req['self']['queue'][:1]}
        events = self.engine._enemy_events(req, req['enemy'])
        result = tactics.evaluate(self.engine.native, self.engine.scoring, own, 120, 1,
            self.engine.policy['normal_tactics'], enemy_events=events, enemy=req['enemy'],
            allowed=[dict(x=3, r='U')]).forecast['choice']
        self.assertEqual(result['dropped'], 30)
        self.assertFalse(result['current_survives'])

    def test_observed_counter_is_not_converted_or_remainder_credited_again(self):
        event = dict(nuisance=46, points=46)
        for rate in (1, 60, 120, 200):
            self.assertEqual(link_amount(event, 108, rate, 0), (46, 108))

    def test_counter_offsets_enemy_pending_before_relaunch(self):
        req = self.counter_request()
        enemy = {**req['enemy'], 'normal_confirmed': 20, 'confirmed': 20}
        self.engine.margin = {}
        self.assertEqual(self.engine._delivered_until(req, req['self'], enemy, 60), (26, 0))

    def test_cross_board_flight_is_not_added_twice(self):
        req = self.counter_request()
        req['observation']['in_flight']['enemy']['attacks_in_flight'][0]['counter'] = False
        events = self.engine._enemy_events(req, req['enemy'])
        self.assertFalse(any(e.get('source') == 'observed_counter_flight' for e in events))

    def test_flight_change_invalidates_prepared_signature(self):
        req = self.counter_request()
        self.engine.margin = {}
        before = self.engine._signature(req, req['self'])
        req['observation']['in_flight']['enemy']['attacks_in_flight'][0]['amount'] += 1
        self.assertNotEqual(before, self.engine._signature(req, req['self']))

    def test_new_counter_blocks_nonclear_authorization_but_allows_clear(self):
        latest = self.counter_request()
        old = json.loads(json.dumps(latest))
        old['observation']['in_flight']['enemy']['attacks_in_flight'] = []
        reply = dict(action='place', decision_identity=identity(old), fire=False)
        with self.assertRaisesRegex(ValueError, 'counter flight changed'):
            authorize_mode_reply(old, reply, latest)
        reply.update(fire=True, chain=1)
        self.assertTrue(authorize_mode_reply(old, reply, latest))

    def test_new_counter_blocks_local_prefetch_preview(self):
        latest = self.counter_request()
        old = json.loads(json.dumps(latest))
        old['observation']['in_flight']['enemy']['attacks_in_flight'] = []
        reply = dict(action='place', decision_identity=identity(old), fire=False)
        state = dict(match_id=old['match_id'], execution_request=old,
                     prepared=[None, 0, reply, None, len(old['self']['queue'])])
        self.assertIsNone(preview_prepared(state, latest))

    def test_logged_full_request_chooses_clear_instead_of_lethal_split(self):
        req = self.counter_request()
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT / 'data/fever/golden/counter-flight-config.json')
        try:
            reply = engine.answer(req)
        finally:
            engine.close()
        self.assertTrue(reply['fire'])
        self.assertFalse(reply['selected_move_loses'])
        self.assertEqual(reply['tactics_forecast']['choice']['dropped'], 0)


if __name__ == '__main__':
    unittest.main()
