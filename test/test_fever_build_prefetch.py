"""Reuse solo construction while refreshing delivery tactics on real observations."""
import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, request, side, seed3, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply


class BuildPrefetchTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    def tearDown(self):
        self.engine.close()

    def active(self):
        enemy = side('fever', ['......']*13+['RRR...'])
        req = request(side('normal', queue=['2:RY', '2:BG']), enemy)
        req['enemy_chain'] = dict(trigger_field=['......']*13+['RRRR..'],
            elapsed=0, scored_links=0, mode_generation=1, seed_id=1)
        return req

    def prepared(self):
        req = self.active(); ahead = copy.deepcopy(req); ahead['op'] = 'prepare_observed'
        result = self.engine.answer(ahead)
        self.assertFalse(result['prepared'])  # Delivery tactics cannot authorize a preinput hint.
        self.assertTrue(result['normal_build_prepared'])
        self.assertNotIn('plan', result)
        req['self']['queue'].append('L:RRY')
        req['frame'] = 10; req['observation'].update(frame_before=10, frame_after=10)
        for p in ('self', 'enemy'): req[p]['observed_frame'] = 10
        req['enemy']['remaining_frames'] -= 10
        req['enemy_chain']['elapsed'] = 10
        return req

    def test_enemy_fever_clock_and_chain_motion_refresh_tactics_without_solo_search(self):
        current = self.prepared()
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            reply = self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_build_search_reused'])
        self.assertEqual(reply['normal_build_searched_visible'], 2)
        self.assertFalse(reply.get('search_reused', False))
        self.assertEqual(reply['decision_identity']['frame'], 10)

    def test_flying_packet_updates_do_not_repeat_construction(self):
        current = self.prepared()
        current['self'].update(unconfirmed=20, normal_unconfirmed=20)
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            reply = self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_build_search_reused'])
        self.assertEqual(reply['reason'], 'fever_wait_hoard_until_drop')

    def test_observed_post_garbage_board_can_prepare_build_during_enemy_fever(self):
        current = self.active()
        current['self']['field'][-1] = '#.....'
        ahead = copy.deepcopy(current); ahead['op'] = 'prepare_observed'
        result = self.engine.answer(ahead)
        self.assertTrue(result['normal_build_prepared'])
        current['self']['queue'].append('L:RRY')
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            reply = self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_build_search_reused'])
        self.assertEqual(reply['next_field'][-1][0], '#')

    def test_future_margin_change_refreshes_tactics_without_disabling_build_prefetch(self):
        current = self.active(); current.pop('enemy_chain')
        current['margin_policy'] = dict(start_frame=50, initial_target_point=120)
        ahead = copy.deepcopy(current); ahead['op'] = 'prepare_observed'
        result = self.engine.answer(ahead)
        self.assertFalse(result['prepared'])
        self.assertTrue(result['normal_build_prepared'])
        current['self']['queue'].append('L:RRY')
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            reply = self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_build_search_reused'])
        self.assertTrue(reply['margin_forecast']['rate_events'])

    def test_changed_board_queue_generation_piece_options_or_match_discard_build(self):
        for change in ('board', 'queue', 'generation', 'piece', 'options', 'match'):
            self.engine.normal_build_cache = None
            current = self.prepared()
            if change == 'board': current['self']['field'][-1] = '.....R'
            elif change == 'queue': current['self']['queue'][0] = '2:GY'
            elif change == 'generation': current['self']['mode_generation'] += 1
            elif change == 'piece': current['self']['piece_id'] += 1
            elif change == 'options': current['solo_options']['beam_width'] += 1
            else: current['match_id'] += '-new'
            with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
                self.engine.answer(current)
            build.assert_called_once()

    def test_prediction_is_refused_if_enemy_end_can_deliver_on_current_placement(self):
        req = self.active(); req['self']['queue'].append('L:RRY')
        req['enemy_chain']['elapsed'] = 30
        req.update(op='prepare', placement=dict(x=5, r='U'))
        result = self.engine.answer(req)
        self.assertFalse(result['prepared'])
        self.assertEqual(result['reason'], 'enemy_delivery_can_change_next_board')

    def test_prediction_can_prepare_build_before_later_enemy_end(self):
        req = self.active(); req['self']['queue'].append('L:RRY')
        req.update(op='prepare', placement=dict(x=5, r='U'))
        result = self.engine.answer(req)
        self.assertFalse(result['prepared'])
        self.assertTrue(result['normal_build_prepared'])
        self.assertEqual(result['searched_visible'], 2)

    def test_flying_packets_do_not_cancel_chosen_steering_but_confirmed_delivery_does(self):
        req = self.active(); req.pop('enemy_chain')
        reply = self.engine.answer(req)
        latest = copy.deepcopy(req)
        latest['self'].update(unconfirmed=200, normal_unconfirmed=200)
        self.assertTrue(authorize_mode_reply(req, reply, latest))
        latest['self'].update(confirmed=30, normal_confirmed=30)
        with self.assertRaisesRegex(ValueError, 'self state changed'):
            authorize_mode_reply(req, reply, latest)

    def test_held_normal_packets_do_not_cancel_fever_input_but_changed_board_does(self):
        req = request(side('fever', seed3()))
        reply = self.engine.answer(req)
        latest = copy.deepcopy(req)
        latest['self'].update(normal_confirmed=200, normal_unconfirmed=100)
        self.assertTrue(authorize_mode_reply(req, reply, latest))
        latest['self']['field'][-1] = 'G.YBRR'
        with self.assertRaisesRegex(ValueError, 'self state changed'):
            authorize_mode_reply(req, reply, latest)

    def test_confirming_attack_does_not_abandon_proven_small_offset(self):
        own = side('normal', seed_with_small_green(), ['2:GY'])
        own.update(gauge=6, unconfirmed=200, normal_unconfirmed=200)
        req = request(own); reply = self.engine.answer(req)
        self.assertEqual(reply['chain'], 1)
        latest = copy.deepcopy(req)
        latest['self'].update(confirmed=200, normal_confirmed=200, unconfirmed=0, normal_unconfirmed=0)
        self.assertTrue(authorize_mode_reply(req, reply, latest))
        latest['self']['field'][-1] = '#.YBRR'
        with self.assertRaisesRegex(ValueError, 'self state changed'):
            authorize_mode_reply(req, reply, latest)


if __name__ == '__main__': unittest.main()
