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
        # The full decision is kept. Delivery, scoring and own-state guards still run on spawn.
        self.assertTrue(result['prepared'] and result['speculative'] and result['plan']['speculative'])
        self.assertTrue(result['normal_build_prepared'])
        self.assertIsNotNone(self.engine.prepared)
        req['self']['queue'].append('L:RRY')
        req['frame'] = 10; req['observation'].update(frame_before=10, frame_after=10)
        for p in ('self', 'enemy'): req[p]['observed_frame'] = 10
        req['enemy']['remaining_frames'] -= 10
        req['enemy_chain']['elapsed'] = 10
        return req

    def test_enemy_fever_clock_and_chain_motion_reuse_the_complete_normal_decision(self):
        current = self.prepared()
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            reply = self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_search_reused'])
        self.assertTrue(reply.get('search_reused', False))
        self.assertEqual(reply['decision_identity']['frame'], 10)

    def test_flying_packet_updates_do_not_repeat_construction(self):
        current = self.prepared()
        current['self'].update(unconfirmed=20, normal_unconfirmed=20)
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            reply = self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_build_search_reused'])
        self.assertEqual(reply['reason'], 'tactics_stack')

    def test_normal_preparation_refreshes_when_enemy_delivery_is_now_due(self):
        current = self.prepared()
        current['frame'] = 55
        current['observation'].update(frame_before=55, frame_after=55)
        for name in ('self', 'enemy'): current[name]['observed_frame'] = 55
        current['enemy']['remaining_frames'] = 845
        current['enemy_chain']['elapsed'] = 55
        with patch.object(self.engine, '_tactics', wraps=self.engine._tactics) as tactics:
            reply = self.engine.answer(current)
        tactics.assert_called_once()
        self.assertFalse(reply.get('search_reused', False))

    def test_normal_preparation_reuses_after_scoring_with_the_same_final_packet(self):
        current = self.prepared(); current['enemy_chain']['scored_links'] = 1
        current['enemy']['remainder'] = 40
        with patch.object(self.engine, '_tactics', wraps=self.engine._tactics) as tactics:
            reply = self.engine.answer(current)
        tactics.assert_not_called()
        self.assertTrue(reply.get('search_reused', False))

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
        self.assertTrue(reply['normal_search_reused'])
        self.assertEqual(reply['next_field'][-1][0], '#')

    def test_unchanged_future_rate_schedule_reuses_the_complete_decision(self):
        current = self.active(); current.pop('enemy_chain')
        current['margin_policy'] = dict(start_frame=50, initial_target_point=120)
        ahead = copy.deepcopy(current); ahead['op'] = 'prepare_observed'
        result = self.engine.answer(ahead)
        self.assertTrue(result['prepared'] and result['speculative'])
        self.assertIsNotNone(self.engine.prepared)
        self.assertTrue(result['normal_build_prepared'])
        current['self']['queue'].append('L:RRY')
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            reply = self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_search_reused'])
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

    def test_speculative_plan_names_the_placement_the_spawn_decides_when_nothing_changed(self):
        req = self.active(); ahead = copy.deepcopy(req); ahead['op'] = 'prepare_observed'
        plan = self.engine.answer(ahead)['plan']
        req['self']['queue'].append('L:RRY')
        reply = self.engine.answer(req)
        self.assertTrue(reply.get('search_reused', False))       # unchanged attack: already decided
        self.assertEqual((reply['x'], reply['r']), (plan['placement']['x'], plan['placement']['r']))

    def test_fever_seed_under_an_enemy_chain_gets_a_speculative_plan(self):
        enemy = side('fever', ['......']*13+['RRR...'])
        req = request(side('fever', seed3(), ['2:BB', '2:RY']), enemy)
        req['enemy_chain'] = dict(trigger_field=['......']*13+['RRRR..'],
            elapsed=0, scored_links=0, mode_generation=1, seed_id=1)
        req['op'] = 'prepare_observed'
        result = self.engine.answer(req)
        self.assertTrue(result['prepared'] and result['speculative'])
        self.assertEqual(result['plan']['mode'], 'fever')
        self.assertIsNotNone(self.engine.prepared)

    def prepared_during_attack(self, frame=14):
        enemy = side('fever', ['......']*13+['RRR...'])
        req = request(side('fever', seed3(), ['2:BB', '2:RY']), enemy)
        req['enemy_chain'] = dict(trigger_field=['......']*13+['RRRR..'],
            elapsed=0, scored_links=0, mode_generation=1, seed_id=1)
        req['op'] = 'prepare_observed'
        self.assertTrue(self.engine.answer(req)['prepared'])
        latest = copy.deepcopy(req); latest['op'] = 'think'
        latest.update(frame=frame, observation=dict(frame_before=frame, frame_after=frame, match_status='running'))
        for name in ('self', 'enemy'):
            latest[name].update(observed_frame=frame, remaining_frames=900-frame)
        latest['enemy_chain']['elapsed'] = frame
        latest['self']['queue'].append('L:RRY')
        return latest

    def test_fever_seed_reuses_preparation_as_the_same_enemy_chain_advances(self):
        latest = self.prepared_during_attack()
        with patch.object(self.engine.seed_solver, 'solve', wraps=self.engine.seed_solver.solve) as solve:
            reply = self.engine.answer(latest)
        self.assertTrue(reply['seed_search_reused'])
        solve.assert_not_called()

    def test_fever_preparation_is_refreshed_when_delivery_can_now_fall_on_it(self):
        latest = self.prepared_during_attack(55)
        with patch.object(self.engine.seed_solver, 'solve', wraps=self.engine.seed_solver.solve) as solve:
            reply = self.engine.answer(latest)
        self.assertFalse(reply['seed_search_reused'])
        solve.assert_called_once()

    def test_fever_preparation_is_refreshed_after_a_scoring_link_or_new_attack(self):
        for change in ('scored', 'new_attack', 'nuisance'):
            latest = self.prepared_during_attack()
            if change == 'scored': latest['enemy_chain']['scored_links'] = 1
            elif change == 'new_attack': latest['enemy_chain']['elapsed'] = 3
            else: latest['self'].update(unconfirmed=12, fever_unconfirmed=12)
            with patch.object(self.engine.seed_solver, 'solve', wraps=self.engine.seed_solver.solve) as solve:
                reply = self.engine.answer(latest)
            self.assertFalse(reply['seed_search_reused'], change)
            solve.assert_called_once()

    def test_scored_packet_with_unchanged_final_balance_reuses_fever_stacking(self):
        latest = self.prepared_during_attack()
        self.assertFalse(self.engine.prepared[2]['fire'])
        latest['enemy_chain']['scored_links'] = 1
        latest['enemy']['remainder'] = 40
        with patch.object(self.engine.seed_solver, 'solve', wraps=self.engine.seed_solver.solve) as solve:
            reply = self.engine.answer(latest)
        solve.assert_not_called()
        self.assertTrue(reply['seed_search_reused'])

    def test_fever_fire_reuses_a_known_attack_after_scoring_bookkeeping(self):
        enemy = side('fever', ['......']*13+['RRR...'])
        enemy['normal_confirmed'] = 60
        req = request(side('fever', seed3(), ['2:RY','2:BB']), enemy)
        req['enemy_chain'] = dict(trigger_field=['......']*13+['RRRR..'],
            elapsed=0, scored_links=0, mode_generation=1, seed_id=1)
        req['op'] = 'prepare_observed'
        self.engine.answer(req)
        self.assertTrue(self.engine.prepared[2]['fire'])
        req['op'] = 'think'
        req['enemy_chain']['scored_links'] = 1
        req['enemy'].update(normal_confirmed=59, remainder=40)
        with patch.object(self.engine.seed_solver, 'solve', wraps=self.engine.seed_solver.solve) as solve:
            reply = self.engine.answer(req)
        solve.assert_not_called()
        self.assertTrue(reply['seed_search_reused'])

    def test_flying_tray_transfer_from_known_scored_links_does_not_search_again(self):
        locked = ['......']*7+['.....R','.....R','.....B','.....B','...BRR','.YYYBB','.RYBRR']
        enemy = side('fever', seed3())
        req = request(side('fever',seed3(),['2:BB','2:RY']), enemy)
        req['enemy_chain'] = dict(trigger_field=locked,elapsed=0,scored_links=0,mode_generation=1,seed_id=1)
        req['op'] = 'prepare_observed'
        self.engine.answer(req)
        req['op'] = 'think'; req['frame'] = 80
        req['observation'].update(frame_before=80,frame_after=80)
        for player in ('self','enemy'):
            req[player].update(observed_frame=80,remaining_frames=820)
        req['enemy_chain'].update(elapsed=80,scored_links=2)
        req['enemy']['remainder'] = 40
        req['self'].update(unconfirmed=2,fever_unconfirmed=2)
        with patch.object(self.engine.seed_solver,'solve',wraps=self.engine.seed_solver.solve) as solve:
            reply = self.engine.answer(req)
        solve.assert_not_called()
        self.assertTrue(reply['seed_search_reused'])

    def test_known_attack_prediction_is_resolved_only_once(self):
        req = self.active()
        with patch.object(self.engine.native, 'ask', wraps=self.engine.native.ask) as native:
            before = self.engine._enemy_events(req, req['enemy'])
            req['frame'] = 10; req['enemy_chain']['elapsed'] = 10
            after = self.engine._enemy_events(req, req['enemy'])
        resolves = [c for c in native.call_args_list if c.args[0]['op'] == 'resolve']
        self.assertEqual(len(resolves), 1)
        self.assertEqual(before[-1]['frame'] - after[-1]['frame'], 10)

    def test_a_changed_absolute_rate_schedule_discards_preparation(self):
        current = self.active(); current.pop('enemy_chain')
        current['margin_policy'] = dict(start_frame=50, initial_target_point=120)
        ahead = copy.deepcopy(current); ahead['op'] = 'prepare_observed'
        self.engine.answer(ahead)
        current['margin_policy']['start_frame'] = 60
        with patch.object(self.engine, '_tactics', wraps=self.engine._tactics) as think:
            reply = self.engine.answer(current)
        think.assert_called_once()
        self.assertFalse(reply.get('search_reused', False))

    def test_bookkeeping_updates_do_not_cancel_current_input(self):
        for mode in ('normal', 'fever'):
            req = request(side(mode, seed3(), ['2:BB']))
            reply = self.engine.answer(req)
            latest = copy.deepcopy(req)
            latest['self'].update(remainder=45, prepared_frames=960, prepared_frames_status='observed')
            self.assertTrue(authorize_mode_reply(req, reply, latest))

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
        self.assertTrue(result['prepared'] and result['speculative'])
        self.assertIsNotNone(self.engine.prepared)
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
        req = request(own, side('fever', seed3())); reply = self.engine.answer(req)
        self.assertEqual(reply['chain'], 1)
        latest = copy.deepcopy(req)
        latest['self'].update(confirmed=200, normal_confirmed=200, unconfirmed=0, normal_unconfirmed=0)
        self.assertTrue(authorize_mode_reply(req, reply, latest))
        latest['self']['field'][-1] = '#.YBRR'
        with self.assertRaisesRegex(ValueError, 'self state changed'):
            authorize_mode_reply(req, reply, latest)


if __name__ == '__main__': unittest.main()
