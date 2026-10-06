"""Mode boundaries, queue routing, deadlines and real native seed transitions."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode import ModeReferee, next_seed
from fever_battle.model import EMPTY, Scoring
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply
from fever_battle.replay import replay
from fever_battle.reference_seeds import decode
from fever_battle.mode_tactics import seed_strategy
from fever_battle.worker import JsonProcess
from fever_battle.uncertainty import outcomes
from fever_battle.finish import choose as fast_finish, placement_frames
from fever_battle.gauge_wait import choose as wait_move
from fever_battle.normal_colors import inspect as inspect_colors

from fever_fixtures import NATIVE, SOLO, request, seed3, seed_with_small_green, side


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.ref = ModeReferee(['raffina', 'ally'])
        self.order = 0

    def event(self, kind, player=0, frame=0, **kwargs):
        self.order += 1
        return self.ref.apply(dict(type=kind, player=player, frame=frame, order=self.order, **kwargs))

    def chain(self, count=1, player=0, all_clear=False, frame=0, points=40):
        name = str(self.order)
        rows = list(EMPTY)
        if not all_clear:
            rows[-1] = '.Y....'
        self.event('place', player, frame, chain=name, result=dict(field=rows, links=[{}]*count))
        for link in range(1, count+1):
            self.event('link', player, frame, chain=name, link=link, points=points)
        return name

    def enter(self, player=0, frame=0):
        self.ref.players[player].gauge = 7
        return self.event('enter', player, frame, clock_running=True)

    def test_offset_per_link_and_enemy_preparation(self):
        self.event('incoming', count=50, confirmed=True, chain='attack', destination='normal')
        name = self.chain(7)
        self.assertEqual(self.ref.players[0].gauge, 7)
        self.assertEqual(self.ref.players[1].prepared_frames, 1320)
        with self.assertRaises(ValueError):
            self.event('enter', clock_running=True)
        self.event('end', chain=name)
        self.event('enter', clock_running=True)
        self.assertEqual(self.ref.players[0].mode, 'fever')

    def test_zero_gain_regression_and_no_unearned_gauge(self):
        self.ref = ModeReferee(['raffina', 'ally'], gauge_gain_on_offset=0)
        self.event('incoming', count=30, confirmed=True, chain='attack', destination='normal')
        self.chain(2, points=40)
        self.assertEqual(self.ref.players[0].gauge, 0)
        self.assertEqual(self.ref.players[1].prepared_frames, 1020)

    def test_preserve_normal_board_and_merge_both_queues(self):
        self.ref.players[0].rows[-1] = 'G.....'
        self.ref.players[0].garbage_phase = 4
        self.event('incoming', count=8, confirmed=True, chain='old', destination='normal')
        self.enter()
        self.event('incoming', count=3, confirmed=True, chain='new', destination='fever')
        self.event('clock', remaining_frames=0, running=False)
        self.event('exit')
        p = self.ref.players[0]
        self.assertEqual(p.rows[-1], 'G.....')
        self.assertEqual(p.pending(True), 11)
        self.assertEqual((p.garbage_phase, p.gauge, p.prepared_frames), (4, 0, 900))

    def test_fever_offsets_active_before_held_and_drops_only_active(self):
        self.event('incoming', count=5, confirmed=True, chain='held', destination='normal')
        self.enter()
        self.event('seed', field=seed3(), seed_id=1, seed_chain=5)
        self.event('incoming', count=2, confirmed=True, chain='active', destination='fever')
        name = self.chain(points=360)
        self.assertEqual(self.ref.players[0].active_pending(), 0)
        self.assertEqual(self.ref.players[0].pending(), 4)
        self.event('end', chain=name)
        self.event('seed', field=seed3(), seed_id=2, seed_chain=3)
        effect = self.event('place', result=dict(field=seed3(), links=[]))
        self.assertEqual(effect['dropped'], 0)
        self.assertEqual(self.ref.players[0].pending(), 4)

    def test_confirmation_survives_recipient_mode_switch(self):
        name = self.chain(points=600, player=1)
        self.enter()
        self.event('end', player=1, chain=name)
        self.assertEqual(self.ref.players[0].held_packets[0].count, 5)
        self.assertTrue(self.ref.players[0].held_packets[0].confirmed)

    def test_remainder_cursor_continues_through_fever_drop_and_return(self):
        self.ref.players[0].garbage_phase = 4
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        self.event('incoming', count=1, confirmed=True, chain='active', destination='fever')
        effect = self.event('place', result=dict(field=seed3(), links=[]))
        self.assertEqual(effect['garbage_phase'], 5)
        self.event('clock', remaining_frames=0, running=False)
        self.event('exit')
        self.assertEqual(self.ref.players[0].garbage_phase, 5)

    def test_timer_stop_resume_and_no_revival_after_expiry(self):
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        self.event('clock', frame=100, remaining_frames=800, running=False)
        self.event('tick', frame=200)
        self.assertEqual(self.ref.players[0].remaining_frames, 800)
        self.event('clock', frame=200, remaining_frames=800, running=True)
        name = self.chain(3, frame=200, all_clear=True)
        self.event('end', frame=1001, chain=name)
        self.assertEqual(self.ref.players[0].remaining_frames, 0)
        self.assertFalse(self.ref.players[0].awaiting_seed)
        self.event('exit', frame=1001)

    def test_any_clear_requires_observed_next_seed(self):
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        name = self.chain(5)
        effect = self.event('end', chain=name)
        self.assertEqual(effect['seed_chain'], 6)
        self.assertEqual(effect['remaining_frames'], 990)
        self.assertTrue(effect['awaiting_seed'])
        before = self.ref.snapshot()
        with self.assertRaises(ValueError):
            self.event('seed', field=seed3(), seed_id=1, seed_chain=6)
        self.assertEqual(self.ref.snapshot(), before)
        with self.assertRaises(ValueError):
            self.event('place', result=dict(field=seed3(), links=[]))
        self.event('seed', field=seed3(), seed_id=2, seed_chain=6)

    def test_failure_rules_and_limits(self):
        self.assertEqual([next_seed(7, n) for n in (7, 6, 5, 4)], [8, 7, 6, 5])
        self.assertEqual(next_seed(4, 1), 3)
        self.assertEqual(next_seed(9, 9, True), 12)
        self.assertEqual(next_seed(15, 15, True), 15)
        self.assertEqual(next_seed(5, 3, displayed=7), 4)
        self.assertEqual(next_seed(5, 1, displayed=7), 3)

    def test_single_clear_fails_seed_and_cannot_continue_cleaned_board(self):
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        name = self.chain(1)
        effect = self.event('end', chain=name)
        self.assertEqual(effect['seed_chain'], 3)
        self.assertTrue(effect['awaiting_seed'])
        with self.assertRaises(ValueError):
            self.event('place', result=dict(field=seed3(), links=[]))
        self.event('seed', field=seed3(), seed_chain=3, seed_id=2)
        self.assertEqual(self.ref.players[0].seed_id, 2)

    def test_all_clear_entry_boost_and_time_cap(self):
        self.ref.players[0].prepared_frames = 1790
        name = self.chain(all_clear=True)
        self.event('end', chain=name)
        effect = self.enter()
        self.assertEqual(effect['seed_chain'], 7)
        self.assertEqual(effect['remaining_frames'], 1800)
        self.assertEqual(self.ref.players[0].seed_base, 5)

    def test_normal_all_clear_seed_consumes_entry_bonus(self):
        name = self.chain(all_clear=True)
        self.event('end', chain=name)
        self.event('seed', field=seed3(), seed_chain=4, seed_id=1)
        self.assertEqual(self.enter()['seed_chain'], 5)

    def test_invalid_event_rolls_back_clock_and_mode_and_replay(self):
        self.event('incoming', count=50, confirmed=True, chain='attack', destination='normal')
        name = self.chain(7)
        self.event('end', chain=name)
        self.event('enter', clock_running=True)
        before = self.ref.snapshot()
        with self.assertRaises(ValueError):
            self.event('exit', frame=20)
        self.assertEqual(self.ref.snapshot(), before)
        self.assertTrue(replay(dict(characters=['raffina', 'ally'], events=self.ref.log,
                                    state=self.ref.snapshot()))['state_matches'])


class NativeModeTests(unittest.TestCase):
    def test_lethal_nuisance_chooses_fast_contact_and_keeps_all_split_time(self):
        rows=['......']*3 + ['.....#']*5 + ['######']*6
        own=side('normal',rows,['2:RY','2:GB']); own.update(confirmed=120,normal_confirmed=120)
        result=fast_finish(self.engine.native,own,budget_ms=1000)
        self.assertIsNotNone(result)
        self.assertLessEqual(result['selected']['finish_after_drops'],2)
        self.assertEqual(result['selected']['estimated_frames'],min(c['estimated_frames'] for c in result['candidates']))
        self.assertTrue(all(d==0 for d in result['selected']['split_distances']))
        c=dict(x=2,r='R',contact_height=10,split_distances=[0,6])
        self.assertGreater(placement_frames(c),placement_frames({**c,'split_distances':[0,0]}))

    def test_no_rescue_dies_by_second_drop_and_never_waits_for_third(self):
        rows=['......']*12+['######']*2
        own=side('normal',rows,['2:RY','2:GB']); own.update(confirmed=120,normal_confirmed=120,
            garbage_phase=None,garbage_phase_status='unknown')
        result=fast_finish(self.engine.native,own,budget_ms=1000)
        self.assertIsNotNone(result)
        self.assertTrue(all(c['finish_after_drops']<=2 for c in result['candidates']))
        answer=self.engine.answer(request(own))
        self.assertEqual(answer['reason'],'no_rescue_fast_finish')
        self.assertTrue(answer['selected_move_loses'])

    def test_possible_offset_and_inconclusive_budget_keep_ordinary_play(self):
        own=side('normal',['......']*13+['RRR...'],['2:RY','2:GB'])
        own.update(confirmed=120,normal_confirmed=120,gauge=6,remainder=100)
        self.assertIsNone(fast_finish(self.engine.native,own,budget_ms=1000))
        self.assertIsNone(fast_finish(self.engine.native,own,budget_ms=0))
        answer=self.engine.answer(request(own))
        self.assertTrue(answer['entry_pending_after_chain'])
        self.assertNotEqual(answer['reason'],'no_rescue_fast_finish')

    def test_empty_board_lethal_queue_selects_second_drop_loss_before_third(self):
        own=side('normal',queue=['2:RY','2:GB','L:YYG'])
        own.update(confirmed=300,normal_confirmed=300,garbage_phase=None,garbage_phase_status='unknown')
        result=fast_finish(self.engine.native,own,budget_ms=1000)
        self.assertIsNotNone(result)
        self.assertTrue(all(c['finish_after_drops']<=2 for c in result['candidates']))
        self.assertIn(result['selected']['x'],(2,3))

    def test_enemy_piece_updates_do_not_discard_own_only_normal_decision(self):
        req=request(side('normal'))
        reply=self.engine.answer(req)
        latest=copy.deepcopy(req); latest['enemy'].update(piece_id=1,dropset_index=1,phase='placing')
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        latest['self'].update(confirmed=30,normal_confirmed=30)
        with self.assertRaises(ValueError):authorize_mode_reply(req,reply,latest)

    def test_live_blocked_spawn_returns_current_drop_without_killing_worker(self):
        own=side('normal',['......']*2+['######']*12)
        own.update(confirmed=300,normal_confirmed=300)
        req=request(own); req['active_placement']=dict(x=2,r='U')
        result=self.engine.answer(req)
        self.assertEqual(result['action'],'place')
        self.assertEqual(result['finish_proof'],'blocked_spawn_observed_current_pose')
        self.assertTrue(result['selected_move_loses'])
        with self.assertRaisesRegex(ValueError,'already dead'):
            self.engine.native.ask(dict(op='placements',field=own['field'],piece=own['queue'][0]))

    def test_observed_current_drop_can_rescue_a_board_above_search_death_threshold(self):
        own=side('normal',['......']*2+['..R...']*3+['.##...']*9)
        own.update(confirmed=120,normal_confirmed=120,remainder=100)
        req=request(own); req['active_placement']=dict(x=1,r='U')
        result=self.engine.answer(req)
        self.assertEqual(result['reason'],'observed_current_pose_drop')
        self.assertFalse(result['selected_move_loses'])
        self.assertTrue(result['fire'])

    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_big_puyo_color_is_present_in_all_live_policy_branches(self):
        for mode in ('normal', 'fever'):
            for unknown in (False, True):
                own=side(mode, seed3() if mode=='fever' else EMPTY,
                    ['0:R','2:GB','2:YY'])
                own['dropset_index']=5
                if unknown:
                    own.update(garbage_phase=None,garbage_phase_status='unknown',confirmed=3)
                    own['fever_confirmed' if mode=='fever' else 'normal_confirmed']=3
                reply=self.engine.answer(request(own))
                self.assertEqual(reply['action'],'place')
                self.assertEqual(reply['color'],'RYGB'['URDL'.index(reply['r'])])

    def test_big_puyo_preparation_has_the_color_required_before_spawn(self):
        own=side('normal',queue=['2:RY','0:R','2:GB']); own['dropset_index']=4
        req=request(own); first=self.engine.answer(req)
        req.update(op='prepare_normal',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(req)
        self.assertTrue(prepared['prepared'])
        placement=prepared['plan']['placement']
        self.assertEqual(placement['color'],'RYGB'['URDL'.index(placement['r'])])

    def prepared_next_request(self):
        original=request(side('normal',queue=['2:RY','2:BB','L:RRY']))
        first=self.engine.answer(original)
        preparation=copy.deepcopy(original)
        preparation.update(op='prepare_normal',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'])
        self.assertEqual(prepared['searched_visible'],2)
        plan=prepared['plan']
        self.assertEqual(plan['field'],first['next_field'])
        self.assertEqual(plan['queue'],original['self']['queue'][1:])
        self.assertEqual(plan['source_queue'],original['self']['queue'])
        self.assertEqual((plan['piece_id'],plan['dropset_index']),(1,1))
        current=copy.deepcopy(original)
        current['self'].update(field=first['next_field'],queue=original['self']['queue'][1:],
            piece_id=1,dropset_index=1,moves_since_chain=1)
        return current

    def test_normal_prefetch_reuses_visible_two_with_fresh_battle_identity(self):
        current=self.prepared_next_request()
        # A newly observed NEXT2 is included in the live request but not in the
        # already completed two-visible-piece preparation.
        current['self']['queue'].append('2:GY')
        current['frame']=20
        current['observation'].update(frame_before=20,frame_after=20)
        for side_ in (current['self'],current['enemy']):side_['observed_frame']=20
        current['enemy']['phase']='placing'
        # Opponent changes do not force repeating the own-board builder.
        with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
            reply=self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_search_reused'])
        self.assertEqual(reply['decision_identity']['frame'],20)
        self.assertEqual(reply['searched_visible'],2)
        self.assertTrue(authorize_mode_reply(current,reply,current))

    def test_normal_prefetch_misses_on_changed_board_piece_or_generation(self):
        for change in ('board','queue','mode_generation'):
            current=self.prepared_next_request()
            if change=='board':current['self']['field'][-1]=current['self']['field'][-1][:5]+'G'
            elif change=='queue':current['self']['queue'][0]='2:GG'
            else:current['self']['mode_generation']+=1
            with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
                reply=self.engine.answer(current)
            self.assertFalse(reply['normal_search_reused'])
            build.assert_called_once()

    def test_normal_prefetch_bypassed_when_incoming_nuisance_changes(self):
        current=self.prepared_next_request()
        current['self'].update(confirmed=3,normal_confirmed=3,garbage_phase=None,garbage_phase_status='unknown')
        reply=self.engine.answer(current)
        self.assertNotIn('normal_search_reused',reply)
        self.assertIn('nuisance_uncertainty',reply)

    def test_normal_prefetch_never_predicts_after_a_clear(self):
        own=side('normal',queue=['2:RR','2:BB','L:RRY'])
        own['field'][-1]='RRR...'
        req=request(own)
        placements=self.engine.native.ask(dict(op='placements',field=own['field'],piece='2:RR'))['placements']
        fired=next(p for p in placements if p['links'])
        req.update(op='prepare_normal',placement=dict(x=fired['x'],r=fired['r']))
        result=self.engine.answer(req)
        self.assertFalse(result['prepared'])
        self.assertIsNone(self.engine.prepared)

    def prepared_seed_request(self, remaining=900):
        original=request(side('fever',seed3(),['2:GG','2:RY','L:RRY']))
        original['self'].update(remaining_frames=remaining)
        original['seed_options']['strategy']='extend'
        first=self.engine.answer(original)
        self.assertEqual((first['action'],first['chain']),('place',0))
        preparation=copy.deepcopy(original)
        preparation.update(op='prepare',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'],prepared)
        plan=prepared['plan']
        self.assertEqual((plan['mode'],plan['piece_id'],plan['dropset_index']),('fever',1,1))
        self.assertEqual(plan['field'],first['next_field'])
        self.assertEqual((plan['queue'],plan['source_queue']),(original['self']['queue'][1:],original['self']['queue']))
        current=copy.deepcopy(original)
        # Fever mode: estimated input 14 + measured nonclearing lock-to-ready 26.
        current['self'].update(field=first['next_field'],queue=original['self']['queue'][1:]+['2:BY'],
            piece_id=1,dropset_index=1,moves_since_chain=1,remaining_frames=remaining-40)
        return current,plan

    def seed_searches(self, current):
        with patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as ask:
            reply=self.engine.answer(current)
        return reply,sum(call.args[0]['op']=='seed_search' for call in ask.call_args_list)

    def test_fever_prefetch_reuses_the_seed_search_made_while_the_piece_fell(self):
        current,plan=self.prepared_seed_request()
        reply,searches=self.seed_searches(current)
        self.assertEqual(searches,0)
        self.assertTrue(reply['seed_search_reused'])
        self.assertEqual(reply['searched_visible'],2)
        self.assertEqual((reply['x'],reply['r']),(plan['placement']['x'],plan['placement']['r']))
        self.assertEqual(reply['decision_identity']['piece_id'],1)
        self.assertTrue(authorize_mode_reply(current,reply,current))
        # One use: the same request asked again is searched.
        reply,searches=self.seed_searches(current)
        self.assertEqual((searches,reply['seed_search_reused']),(1,False))

    def test_fever_prefetch_misses_on_another_board_piece_seed_or_delivery(self):
        for change in ('board','queue','seed_id','delivery'):
            current,_=self.prepared_seed_request()
            if change=='board':current['self']['field'][-1]=('B' if current['self']['field'][-1][0]=='G' else 'G')+current['self']['field'][-1][1:]
            elif change=='queue':current['self']['queue'][0]='2:BB'
            elif change=='seed_id':current['self']['seed_id']+=1
            else:current['self'].update(confirmed=4,fever_confirmed=4)
            reply,searches=self.seed_searches(current)
            self.assertEqual((searches,reply['seed_search_reused']),(1,False),change)

    def test_fever_prefetch_rechecks_flying_and_held_nuisance_for_strategy_selection(self):
        current,plan=self.prepared_seed_request()
        self.assertEqual(plan['nuisance'],dict(confirmed=0))
        current['self'].update(unconfirmed=54,fever_unconfirmed=54,remainder=31)
        reply,searches=self.seed_searches(current)
        self.assertEqual((searches,reply['seed_search_reused']),(1,False))
        self.assertTrue(authorize_mode_reply(current,reply,current))
        current,_=self.prepared_seed_request()
        current['self']['normal_unconfirmed']=12
        reply,searches=self.seed_searches(current)
        self.assertEqual((searches,reply['seed_search_reused']),(1,False))

    def test_one_preparation_serves_both_modes_from_an_observed_board(self):
        # After a chain, a delivery or a new seed there is no placement to predict from: the board
        # standing between two pieces is read, with the two pieces visible by then.
        for mode in ('normal','fever'):
            own=side(mode,seed3(),['2:RY','L:RRY'])
            own.update(dropset_index=1,piece_id=1)
            if mode=='normal':own['field'][-1]='#'+own['field'][-1][1:]       # a delivery has landed
            ahead=request(own); ahead['op']='prepare_observed'
            prepared=self.engine.answer(ahead)
            self.assertTrue(prepared['prepared'],prepared)
            plan=prepared['plan']
            self.assertEqual((plan['mode'],plan['field'],plan['queue']),(mode,own['field'],own['queue']))
            self.assertNotIn('source_queue',plan)
            current=request(copy.deepcopy(own)); current['self']['queue'].append('2:GB')
            if mode=='fever':current['self']['remaining_frames']-=14
            with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
                reply,searches=self.seed_searches(current)
            build.assert_not_called()
            self.assertEqual(searches,0)
            self.assertTrue(reply['search_reused'])
            self.assertEqual((reply['x'],reply['r']),(plan['placement']['x'],plan['placement']['r']))
            self.assertTrue(authorize_mode_reply(current,reply,current))

    def test_normal_preparation_inherits_nuisance_in_flight_but_not_a_changed_count(self):
        original=request(side('normal',queue=['2:RY','2:BB','L:RRY']))
        original['self'].update(unconfirmed=6,normal_unconfirmed=6)
        first=self.engine.answer(original)
        self.assertEqual(first['action'],'place')
        if first['fire']:self.skipTest('the first move clears; nothing to predict')
        preparation=copy.deepcopy(original)
        preparation.update(op='prepare',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'],prepared)
        self.assertEqual(prepared['plan']['nuisance'],dict(confirmed=0,unconfirmed=6))
        kept=self.engine.prepared
        for unconfirmed,reused in ((6,True),(9,False)):
            self.engine.prepared=kept
            current=copy.deepcopy(original)
            current['self'].update(field=first['next_field'],queue=original['self']['queue'][1:]+['2:GY'],
                piece_id=1,dropset_index=1,moves_since_chain=1,unconfirmed=unconfirmed,normal_unconfirmed=unconfirmed)
            reply=self.engine.answer(current)
            self.assertEqual(bool(reply.get('search_reused')),reused,unconfirmed)
        # A confirmed delivery falls with a placement that clears nothing: no board to predict.
        original['self'].update(confirmed=2,normal_confirmed=2,garbage_phase=None,garbage_phase_status='unknown')
        preparation=copy.deepcopy(original)
        preparation.update(op='prepare',placement=dict(x=first['x'],r=first['r']))
        self.assertFalse(self.engine.answer(preparation)['prepared'])

    def test_fever_prefetch_checks_the_clock_only_when_time_is_short(self):
        # Plenty of time: a split or a long fall beyond the estimate changes nothing the search weighed.
        current,_=self.prepared_seed_request()
        current['self']['remaining_frames']-=60
        self.assertEqual(self.seed_searches(current)[1],0)
        # Short of time (the seed is being fired): 30 frames of slack, then it is searched again.
        for late,searches in ((30,0),(31,1)):
            current,_=self.prepared_seed_request(remaining=230)
            current['seed_options']['strategy']='extend'
            current['self']['remaining_frames']-=late
            self.assertEqual(self.seed_searches(current)[1],searches,late)

    def test_fever_prefetch_never_predicts_a_clear_or_a_delivery(self):
        fire=request(side('fever',seed3(),['2:GG','2:RY','L:RRY']))
        moves=self.engine.native.ask(dict(op='placements',field=fire['self']['field'],piece='2:GG'))['placements']
        quiet=next(p for p in moves if not p['links'] and not p['dead'])
        for change in ('clear','nuisance'):
            req=copy.deepcopy(fire); placement=dict(x=quiet['x'],r=quiet['r'])
            if change=='clear':
                req['self']['field'][-1]='GG'+req['self']['field'][-1][2:]
                moves=self.engine.native.ask(dict(op='placements',field=req['self']['field'],piece='2:GG'))['placements']
                fired=next(p for p in moves if p['links'])
                placement=dict(x=fired['x'],r=fired['r'])
            else:req['self'].update(confirmed=2,fever_confirmed=2)
            req.update(op='prepare',placement=placement)
            self.assertFalse(self.engine.answer(req)['prepared'],change)
            self.assertIsNone(self.engine.prepared)

    def test_opponent_changes_never_take_back_a_decided_move(self):
        for own in (side('fever',seed3()),side('normal',queue=['2:RY','2:BB','L:RRY'])):
            req=request(own); reply=self.engine.answer(req)
            reply.pop('decision_dependencies',None)       # whatever the policy says it looked at
            latest=copy.deepcopy(req)
            latest['enemy']=side('fever',seed3(),['2:BG'])
            latest['enemy'].update(piece_id=7,remainder=55,phase='waiting_seed',remaining_frames=411,
                                   unconfirmed=30,fever_unconfirmed=30)
            self.assertTrue(authorize_mode_reply(req,reply,latest))
            latest['self']['field']=list(latest['self']['field']); latest['self']['field'][-1]='G.....'
            with self.assertRaisesRegex(ValueError,'self state changed'):
                authorize_mode_reply(req,reply,latest)

    def test_unknown_history_continues_without_inventing_a_cursor(self):
        own = side('normal')
        own.update(garbage_phase=None, garbage_phase_status='unknown',
                   moves_since_chain=None, moves_since_chain_status='unknown')
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['action'], 'place')
        self.assertIsNone(own['garbage_phase'])
        own.update(confirmed=3, normal_confirmed=3)
        reply = self.engine.answer(request(own))
        forecast = reply['nuisance_uncertainty']
        self.assertEqual(forecast['possible_drop_boards'], 20)
        self.assertIsNone(reply['next_field'])
        self.assertEqual(forecast['uncertainty'], 'all_remainder_column_subsets')

    def test_fever_unknown_preparation_and_cursor_use_observed_seed(self):
        own = side('fever', seed3(), ['2:RY', '2:BB', 'L:RRY'])
        own.update(garbage_phase=None, garbage_phase_status='unknown',
                   prepared_frames=None, prepared_frames_status='unknown',
                   moves_since_chain=None, moves_since_chain_status='unknown')
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['action'], 'place')
        self.assertEqual(reply['seed_forecast']['garbage_phase_status'], 'unknown_no_confirmed_drop_forecast')
        own.update(confirmed=3, fever_confirmed=3)
        reply = self.engine.answer(request(own))
        self.assertEqual(len(reply['seed_forecast']['path']), 1)
        self.assertEqual(reply['seed_forecast']['strategy'], 'quick')
        self.assertEqual(reply['seed_forecast']['garbage_phase_status'], 'unknown_all_remainder_column_subsets')
        rows=list(EMPTY); rows[-1]='RRR...'
        own.update(field=rows,queue=['2:RR'],normal_confirmed=500)
        reply=self.engine.answer(request(own)); first=reply['seed_forecast']['choice']
        actual=self.engine.native.ask(dict(op='transition',field=rows,piece='2:RR',x=first['x'],r=first['r']))
        self.assertEqual(first['locked_field'],actual['locked_field'])
        self.assertEqual(first['field'],actual['field'])
        self.assertGreater(first['end_at'],first['fire_at'])
        self.assertEqual(first['sent'],0)  # active and held nuisance both absorb the chain
        self.assertFalse(reply['seed_forecast']['solved'])  # one clear still fails a three-chain seed

    def test_unknown_without_provenance_is_rejected(self):
        own = side()
        own['garbage_phase'] = None
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.engine.answer(request(own))

    def test_unknown_columns_do_not_bypass_solver_option_validation(self):
        own=side('fever',seed3())
        own.update(garbage_phase=None,garbage_phase_status='unknown',confirmed=3,fever_confirmed=3)
        for options in (dict(strategy='invalid'),dict(width=0),dict(hidden_queue=True)):
            req=request(own); req['seed_options']=options
            with self.assertRaises(ValueError):self.engine.answer(req)

    def test_remainder_uncertainty_includes_noncyclic_columns_and_loss(self):
        cases = list(outcomes(EMPTY, 3))
        self.assertEqual(len(cases), 20)
        self.assertIn('###...', [rows[-1] for rows, _ in cases])
        rows = list(EMPTY)
        rows[-11:] = ['..R...']*11
        cases = list(outcomes(rows, 1))
        self.assertEqual(sum(losing for _, losing in cases), 1)

    def test_tables_and_mode_dependent_score(self):
        score = Scoring()
        self.assertEqual(score.link('raffina', 10, [4], 1, 'fever'), 6760)
        self.assertEqual(score.link('paprisu', 17, [4], 1, 'fever'), 16400)
        self.assertEqual(score.link('schezo', 17, [4], 1, 'fever'), 13120)
        for c in score.data['characters']:
            self.assertEqual(len(score.data['characters'][c]['fever']), 17)
        with self.assertRaises(ValueError):
            score.link('raffina', 18, [4], 1, 'fever')

    def test_steam_internal_clock_keeps_the_full_observed_deadline(self):
        req = request()
        req['clock_policy']['frame_domain'] = 'pc_15209927_internal'
        req['self']['prepared_frames'] = req['self']['remaining_frames'] = 1860
        reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        latest = copy.deepcopy(req)
        latest['frame'] = latest['observation']['frame_before'] = latest['observation']['frame_after'] = 5
        for name in ('self', 'enemy'):
            latest[name]['observed_frame'] = 5
        latest['self']['remaining_frames'] -= 5
        self.assertTrue(authorize_mode_reply(req, reply, latest))
        latest['clock_policy']['frame_domain'] = 'model'
        with self.assertRaisesRegex(ValueError, 'clock_policy changed'):
            authorize_mode_reply(req, reply, latest)

    def test_raw_clock_requires_explicit_domain_and_rejects_unknown_units(self):
        req = request()
        req['self']['prepared_frames'] = 1860
        with self.assertRaises(ValueError):
            self.engine.answer(req)
        req['clock_policy']['frame_domain'] = 'seconds'
        with self.assertRaisesRegex(ValueError, 'clock frame domain'):
            self.engine.answer(req)
        req['clock_policy']['frame_domain'] = 'pc_15209927_internal'
        req['self']['remaining_frames'] = 1861
        with self.assertRaises(ValueError):
            self.engine.answer(req)

    def test_three_chain_native_path_matches_scoring(self):
        req = request()
        req['seed_options']['strategy'] = 'quick'
        reply = self.engine.answer(req)
        self.assertTrue(reply['seed_forecast']['solved'])
        self.assertGreaterEqual(reply['chain'], 3)
        step = self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:RY',
                                          x=reply['x'], r=reply['r']))
        self.assertEqual(step['field'], reply['next_field'])
        self.assertEqual(self.engine.scoring.chain('raffina', step['links'], 'fever'), reply['link_points'])
        self.assertTrue(authorize_mode_reply(req, reply, copy.deepcopy(req)))

    def test_seed_decision_survives_enemy_soft_drop_score_and_observation_updates(self):
        req=request(); reply=self.engine.answer(req)
        self.assertEqual(reply['decision_dependencies'],['self'])
        latest=copy.deepcopy(req)
        latest['enemy'].update(remainder=17,board_observed_frame=3,moves_since_chain=1)
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        for key,value in (('field',seed3()),('queue',['2:BG']),('phase','chain')):
            changed=copy.deepcopy(latest); changed['enemy'][key]=value
            self.assertTrue(authorize_mode_reply(req,reply,changed))

    def test_recovery_excludes_cached_unreachable_move_and_scores_real_alternative(self):
        req=request(side(rows='....../....../....../....../.....B/.....B/.....R/.....R/....BG/....BG/...GGB/...RYB/.RRGRG/.BBRRG'.split('/'),queue=['L:RRR','0:G','2:YB']))
        req['self'].update(character='rafisol', dropset_index=10)
        req.update(op='recover_placement',reachable_placements=[dict(x=2,r='U'),dict(x=3,r='U')])
        self.engine.prepared=('stale',0,dict(x=4,r='D'))
        reply=self.engine.answer(req)
        self.assertIn((reply['x'],reply['r']),[(2,'U'),(3,'U')])
        self.assertEqual(reply['reason'],'observed_reachable_recovery')
        self.assertIsNone(self.engine.prepared)
        step=self.engine.native.ask(dict(op='transition',field=req['self']['field'],piece='L:RRR',x=reply['x'],r=reply['r']))
        self.assertEqual(step['field'],reply['next_field'])
        self.assertTrue(authorize_mode_reply(req,reply,req))
        req['reachable_placements']=[]
        with self.assertRaisesRegex(ValueError,'requires observed'):self.engine.answer(req)

    def test_threatened_seed_ignores_enemy_motion_and_flying_packets_but_rejects_delivery(self):
        req=request(side('fever', seed3(), ['2:GG'])); req['self'].update(unconfirmed=206,fever_unconfirmed=206)
        reply=self.engine.answer(req)
        self.assertFalse(reply['fire'])
        self.assertEqual(reply['decision_dependencies'],['self'])
        latest=copy.deepcopy(req)
        latest['enemy'].update(piece_id=2,queue=['2:BG'],field=seed3(),phase='placing',remainder=3)
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        latest['self'].update(unconfirmed=205,fever_unconfirmed=205)
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        latest['self'].update(confirmed=1,fever_confirmed=1)
        with self.assertRaisesRegex(ValueError,'self state changed'):
            authorize_mode_reply(req,reply,latest)

    def test_two_move_solution_and_stop_at_first_clear(self):
        req = request(side('fever', seed3(), ['2:GG', '2:RY']))
        req['seed_options']['strategy'] = 'quick'
        reply = self.engine.answer(req)
        forecast = reply['seed_forecast']
        self.assertTrue(forecast['solved'])
        self.assertEqual(len(forecast['path']), 2)
        self.assertEqual(forecast['path'][0]['chain'], 0)
        self.assertGreaterEqual(forecast['path'][1]['chain'], 3)

    def test_cutoff_returns_legal_fallback_and_no_hidden_colors(self):
        req = request(side('fever', queue=['2:GY']))
        req['seed_options']['max_nodes'] = 1
        reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        self.assertFalse(reply['seed_forecast']['solved'])
        self.assertTrue(reply['seed_forecast']['cutoff'])
        self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:GY',
                                    x=reply['x'], r=reply['r']))
        req['self']['queue'] = ['2:GY'] * 4
        with self.assertRaises(ValueError):
            self.engine.answer(req)

    def test_nuisance_cleanup_single_is_terminal_failure_not_setup(self):
        rows = list(EMPTY)
        rows[-1] = 'RRR#BB'
        own = side('fever', rows, ['2:RY'])
        own['seed_base'] = own['seed_chain'] = 5
        own['remaining_frames'] = 40  # No time to draw another piece for repair.
        req = request(own); req['seed_options']['strategy'] = 'quick'
        # Solver alone; in a battle this idle clean-up fire is skipped (test_fever_tactics).
        result = self.engine.seed_solver.solve(req['self'], 120, True, req['seed_options'], match_id='mode-test')
        self.assertFalse(result['solved'])
        self.assertTrue(all(p['chain'] == 0 for p in result['path'][:-1]))
        self.assertEqual(result['path'][-1]['chain'], 1)
        self.assertFalse(any('#' in r for r in result['path'][-1]['field']))
        self.assertTrue(result['requires_new_seed_after_clear'])

    def test_low_seed_builds_beyond_visible_fire_and_reports_only_a_heuristic(self):
        req = request()
        req['seed_options']['strategy']='extend'
        reply = self.engine.answer(req)
        forecast = reply['seed_forecast']
        self.assertFalse(reply['fire'])
        self.assertFalse(forecast['solved'])
        self.assertFalse(forecast['requires_new_seed_after_clear'])
        self.assertEqual(forecast['objective'], 'max_chain_for_next_fever_entry')
        self.assertEqual(forecast['desired_chain'], 15)
        self.assertTrue(forecast['choice']['target_ignition_preserved'])
        self.assertGreater(forecast['choice']['all_clear_setup_bonus'], 0)
        self.assertEqual(forecast['choice']['extension_potential']['status'],
                         'geometric_heuristic_not_visible_solution')
        req['seed_options']['strategy'] = 'quick'
        fire = self.engine.answer(req)
        self.assertEqual(fire['chain'], 3)
        self.assertEqual(fire['seed_forecast']['objective'], 'deadline_score_and_seed_turnover')

    def test_normal_identifies_mainline_color_deficits_and_separate_counter_colors(self):
        own = side('normal', seed_with_small_green(), ['2:GB'])
        needs = inspect_colors(self.engine.native, own)['needs']
        self.assertEqual(needs['mainline_chain'], 3)
        self.assertTrue(any(p['color'] == 'Y' and p['needed_cells'] == 1 and
                            p['missing_visible_cells'] == 1 for p in needs['mainline']))
        self.assertTrue(any(p['color'] == 'G' and p['chain'] == 1 and
                            p['visible_supply'] == 1 for p in needs['offsets']))
        self.assertGreater(needs['reserve_weights']['Y'], needs['reserve_weights']['G'])

    def test_mainline_builder_move_stands_when_nothing_is_incoming(self):
        own = side('normal', seed3(), ['2:GB', '2:RR', '2:BB']); own['character'] = 'arle'
        req = request(own); req['match_id'] = 'protect-next-red'
        self.engine.prepared = None
        # The one-piece colour heuristic would move this elsewhere to keep the
        # red trigger. Measured builds were shorter with that override (9.0
        # against 12.7 links), so the needs are reported and the move kept.
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=4, r='R')):
            reply = self.engine.answer(req)
        self.assertEqual(reply['reason'], 'normal_build_or_fire')
        self.assertEqual((reply['x'], reply['r']), (4, 'R'))
        self.assertEqual(reply['normal_color_needs']['mainline_chain'], 3)
        self.assertFalse(reply['fire'])
        self.assertTrue(authorize_mode_reply(req, reply, req))

    def test_prepared_normal_choice_is_the_builder_move_and_is_reused(self):
        own = side('normal', seed3(), ['2:GB', '2:RR', '2:BB']); own['character'] = 'arle'
        req = request(own); req['match_id'] = 'prepared-protect-next-red'
        preparation = copy.deepcopy(req); preparation['op'] = 'prepare_observed'
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=4, r='R')):
            prepared = self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'])
        self.assertEqual(prepared['plan']['reason'], 'normal_build_or_fire')
        self.assertEqual(prepared['plan']['placement'], dict(x=4, r='R'))
        with patch.object(self.engine.solo, 'ask', side_effect=AssertionError('unexpected new search')):
            reply = self.engine.answer(req)
        self.assertTrue(reply['normal_search_reused'])
        self.assertEqual(reply['reason'], 'normal_build_or_fire')
        self.assertEqual(reply['searched_visible'], 2)
        self.assertTrue(authorize_mode_reply(req, reply, req))

    def test_normal_missing_mainline_color_can_use_small_clear_to_hold_garbage(self):
        own = side('normal', seed_with_small_green(), ['2:GB'])
        own.update(confirmed=18, normal_confirmed=18, garbage_phase=None, garbage_phase_status='unknown')
        req = request(own); req['gauge_gain_on_offset'] = 0
        reply = self.engine.answer(req)
        self.assertEqual(reply['chain'], 1)
        self.assertTrue(reply['intentional_small_clear'])
        self.assertTrue(reply['hold_nuisance_for_missing_color'])
        self.assertEqual(reply['nuisance_uncertainty']['dropped'], 0)
        self.assertEqual(sum(row.count('R') for row in reply['next_field']),
                         sum(row.count('R') for row in own['field']))
        self.assertEqual(inspect_colors(self.engine.native,
            {**own, 'field':reply['next_field'], 'confirmed':0})['needs']['mainline_chain'], 3)

    def test_fever_wait_preserves_mainline_colors_with_the_same_small_counter(self):
        own = side('normal', seed_with_small_green(), ['2:GB'])
        own.update(gauge=6, unconfirmed=200, normal_unconfirmed=200)
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['chain'], 1)
        self.assertTrue(reply['entry_pending_after_chain'])
        self.assertEqual(reply['needed_color_consumed'], 0)
        self.assertGreater(reply['normal_color_needs']['reserve_weights']['Y'], 0)

    def test_matching_color_keeps_mainline_fire_instead_of_small_hold(self):
        own = side('normal', seed_with_small_green(), ['2:GY'])
        own.update(confirmed=18, normal_confirmed=18, garbage_phase=None, garbage_phase_status='unknown')
        req = request(own); req['gauge_gain_on_offset'] = 0
        reply = self.engine.answer(req)
        self.assertGreaterEqual(reply['chain'], 3)
        self.assertFalse(reply.get('intentional_small_clear', False))

    def test_losing_immediate_target_port_does_not_force_seed_failure_while_an_ignition_survives(self):
        own = side('fever', seed_with_small_green(), ['2:GB'])
        own.update(confirmed=18, fever_confirmed=18, garbage_phase=None, garbage_phase_status='unknown')
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['chain'], 0)
        self.assertFalse(reply.get('intentional_seed_failure', False))
        first = reply['seed_forecast']['choice']
        self.assertEqual(first['dropped'], 18)
        self.assertFalse(first['dead'])
        self.assertGreater(first['extension_potential']['chain'], 0)
        self.assertTrue(reply['seed_forecast']['early_failure_deferred'])
        self.assertFalse(reply['seed_forecast']['solved'])
        self.assertFalse(reply['replaces_seed_on_clear'])
        self.assertEqual(len(reply['seed_forecast']['path']), 1)

    def test_offline_seed_geometry_keeps_missing_history_explicit(self):
        own = side('fever', seed3())
        for key in ('mode_generation','seed_id','piece_id'):
            del own[key]
        result = self.engine.seed_solver.solve(own, 120, True, dict(strategy='quick'))
        self.assertTrue(result['solved'])
        self.assertEqual(result['extension_history_status'], 'unavailable_offline_single_seed')

    def test_extension_history_does_not_force_fire_and_resets_for_next_seed(self):
        req = request(); req['match_id'] = 'extension-patience'
        req['seed_options']['strategy']='extend'
        first = self.engine.answer(req)['seed_forecast']
        self.assertEqual(first['extension_moves'], 0)
        self.assertEqual(self.engine.answer(req)['seed_forecast']['extension_moves'], 0)
        req['self']['piece_id'] += first['extension_patience'] + 20
        self.assertFalse(self.engine.answer(req)['fire'])
        self.assertEqual(self.engine.answer(req)['seed_forecast']['extension_stop_policy'],
                         'time_and_space_no_fixed_move_limit')
        req['self']['seed_id'] += 1
        reset = self.engine.answer(req)['seed_forecast']
        self.assertEqual(reset['extension_moves'], 0)
        self.assertEqual(reset['choice']['chain'], 0)

    def test_seed_goal_is_large_extension_instead_of_a_small_fixed_gain(self):
        results = []
        for target in (3, 9, 15):
            own = side('fever', seed3()); own.update(seed_chain=target, seed_base=target)
            results.append(self.engine.answer(request(own))['seed_forecast'])
        self.assertEqual([r['extension_patience'] for r in results], [12, 6, 0])
        self.assertEqual([r['desired_chain'] for r in results], [15, 15, 15])

    def test_seed_accepts_two_garbage_rows_when_target_ignition_remains(self):
        for count in (6, 12):
            own = side('fever', seed3())
            own.update(confirmed=count, fever_confirmed=count, garbage_phase=None, garbage_phase_status='unknown')
            req=request(own);req['seed_options']['strategy']='extend'
            reply = self.engine.answer(req); first = reply['seed_forecast']['choice']
            self.assertEqual(first['chain'], 0)
            self.assertEqual(first['dropped'], count)
            self.assertTrue(first['target_ignition_preserved'])
            self.assertFalse(first['dead'])
            self.assertTrue(first['post_drop_field_known'])
            self.assertGreaterEqual(first['extension_potential']['chain'], own['seed_chain'])
            # Controlled favorable NEXT colors prove that this accepted shape
            # can actually fire after the drop, rather than only surviving.
            future = side('fever', reply['next_field'], ['2:RR', 'L:RRR'])
            future.update(dropset_index=1, piece_id=1)
            req = request(future); req['seed_options']['strategy'] = 'quick'
            fired = self.engine.answer(req)['seed_forecast']
            self.assertTrue(fired['solved'])
            self.assertGreaterEqual(fired['path'][-1]['chain'], own['seed_chain'])
        own.update(confirmed=18, fever_confirmed=18)
        reply = self.engine.answer(request(own))
        self.assertGreaterEqual(reply['chain'], own['seed_chain'])
        self.assertEqual(reply['seed_forecast']['choice']['dropped'], 0)

    def test_small_unconfirmed_pressure_does_not_trigger_small_counter(self):
        own = side('fever', seed3())
        own.update(unconfirmed=206, fever_unconfirmed=206)
        reply = self.engine.answer(request(own))
        self.assertFalse(reply['fire'])
        self.assertEqual(reply['seed_forecast']['choice']['dropped'], 0)
        self.assertTrue(reply['seed_forecast']['choice']['target_ignition_preserved'])

    def test_fever_recovery_keeps_extension_inside_observed_reachable_moves(self):
        req = request(); req.update(op='recover_placement', reachable_placements=[dict(x=2, r='U')])
        req['seed_options']['strategy']='extend'
        reply = self.engine.answer(req)
        self.assertEqual((reply['x'], reply['r']), (2, 'U'))
        self.assertFalse(reply['fire'])
        self.assertEqual(reply['recovery_forecast']['objective'], 'max_chain_for_next_fever_entry')
        self.assertTrue(authorize_mode_reply(req, reply, req))

    def test_uncertain_seed_drop_checks_all_subsets_before_reobservation(self):
        own = side('fever', seed3(), ['2:GG'])
        own.update(confirmed=3, fever_confirmed=3, garbage_phase=None, garbage_phase_status='unknown')
        reply = self.engine.answer(request(own)); result = reply['seed_forecast']; first = result['choice']
        self.assertEqual(first['chain'], 0)
        self.assertEqual(first['possible_drop_boards'], 20)
        self.assertEqual(len(result['path']), 1)
        self.assertFalse(first['post_drop_field_known'])
        self.assertIsNone(reply['next_field'])
        self.assertEqual(result['searched_visible'], 1)
        self.assertEqual(first['target_ignition_preserved'], first['all_drop_cases_preserve_target'])

    def test_all_clear_can_outweigh_an_under_target_chain(self):
        own = side('fever', list(EMPTY), ['2:RR'])
        own['field'][-1] = 'RRR...'
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['chain'], 1)
        self.assertTrue(reply['next_all_clear'])
        self.assertEqual(reply['next_field'], list(EMPTY))
        self.assertTrue(reply['replaces_seed_on_clear'])
        self.assertFalse(reply['seed_forecast']['solved'])

    def test_deadline_scores_whole_chain_and_separates_next_seed_opportunity(self):
        req = request(); req['self']['remaining_frames'] = 50
        reply = self.engine.answer(req); last = reply['seed_forecast']['path'][-1]
        self.assertEqual(reply['chain'], 3)
        self.assertGreater(last['end_at'], 50)
        self.assertFalse(last['completed_before_timeout'])
        self.assertFalse(last['next_seed_input_fits'])
        self.assertEqual(last['total_points'], sum(last['link_points']))
        self.assertGreater(last['total_points'], last['points_before_timeout'])
        req['seed_options']['strategy'] = 'quick'
        req['self']['remaining_frames'] = 900
        last = self.engine.answer(req)['seed_forecast']['path'][-1]
        self.assertTrue(last['completed_before_timeout'])
        self.assertTrue(last['next_seed_input_fits'])

    def test_mode_or_seed_change_rejects_old_input(self):
        req = request()
        reply = self.engine.answer(req)
        for key in ('seed_id', 'mode_generation'):
            latest = copy.deepcopy(req)
            latest['self'][key] += 1
            with self.assertRaises(ValueError):
                authorize_mode_reply(req, reply, latest)
        latest = copy.deepcopy(req)
        latest['frame'] = 5
        latest['observation'].update(frame_before=5, frame_after=5)
        for name in ('self', 'enemy'):
            latest[name]['observed_frame'] = 5
        latest['self']['remaining_frames'] -= 5
        self.assertTrue(authorize_mode_reply(req, reply, latest))

    def test_short_and_expired_timer_finish_the_observed_active_piece(self):
        req = request()
        req['self']['remaining_frames'] = 1
        self.assertEqual(self.engine.answer(req)['action'], 'place')
        req['self']['remaining_frames'] = 0
        self.assertEqual(self.engine.answer(req)['action'], 'place')

    def test_normal_return_uses_normal_scoring_with_fever_enemy(self):
        req = request(side(), side('fever', seed3()))
        req['self']['field'][-1] = 'RRR.BB'
        req['self']['queue'] = ['2:RG']
        reply = self.engine.answer(req)
        self.assertEqual(reply['mode'], 'normal')
        result = self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:RG',
                                            x=reply['x'], r=reply['r']))
        self.assertEqual(reply['link_points'], self.engine.scoring.chain('raffina', result['links']))

    def test_active_and_held_queues_and_observation_fields_required(self):
        req = request()
        req['self']['normal_confirmed'] = 100
        req['seed_options']['strategy'] = 'quick'
        reply = self.engine.answer(req)
        self.assertTrue(reply['seed_forecast']['solved'])
        for step in reply['seed_forecast']['path']:
            self.assertEqual(step['dropped'], 0)
        for key in ('stored_field', 'seed_id', 'mode_generation', 'clock_running'):
            invalid = copy.deepcopy(req)
            del invalid['self'][key]
            with self.assertRaises((ValueError, KeyError)):
                self.engine.answer(invalid)

    def test_all_characters_and_cycle_positions_in_fever_mode(self):
        for character in self.engine.patterns:
            queue = self.engine.native.ask(dict(op='queue', character=character, seed=1, count=16))['queue']
            for index, piece in enumerate(queue):
                own = side('fever', seed3(), [piece])
                own.update(character=character, piece_id=index, dropset_index=index)
                req = request(own)
                reply = self.engine.answer(req)
                self.assertEqual(reply['action'], 'place', (character, index))
                actual = self.engine.native.ask(dict(op='transition', field=own['field'], piece=piece,
                                                     x=reply['x'], r=reply['r']))
                self.assertEqual(actual['field'], reply['next_field'])
                self.assertTrue(authorize_mode_reply(req, reply, copy.deepcopy(req)))

    def test_normal_offset_forecasts_fever_entry(self):
        own = side()
        own['gauge'] = 6
        own['field'][-1] = 'RRR.BB'
        own['confirmed'] = own['normal_confirmed'] = 30
        reply = self.engine.answer(request(own))
        self.assertTrue(reply['entry_pending_after_chain'])
        self.assertEqual(reply['gauge_forecast']['gauge_after'], 7)

    def test_wait_preserves_colors_when_four_puyos_are_enough_to_enter(self):
        own=side('normal',list(EMPTY[:-1])+['RRRBBB'],['2:RB','2:RY','2:GY'])
        own.update(character='arle',gauge=6,unconfirmed=100,normal_unconfirmed=100)
        reply=self.engine.answer(request(own))
        self.assertEqual(reply['reason'],'fever_wait_conserve')
        self.assertEqual(reply['consumed_puyos'],4)
        self.assertTrue(reply['entry_pending_after_chain'])
        candidates=reply['wait_forecast']['candidates']
        self.assertTrue(any(c['popped']==8 and c['gauge_after']==7 for c in candidates))
        self.assertEqual(sum(sum(link['groups']) for link in self.engine.native.ask(dict(
            op='transition',field=own['field'],piece=own['queue'][0],x=reply['x'],r=reply['r']))['links']),4)

    def test_wait_uses_next_colors_to_choose_which_small_clear_to_prepare(self):
        answers=[]
        for nxt in ('RR','BB'):
            own=side('normal',list(EMPTY[:-2])+['RRRBBB','GGGYYY'],['2:RB','2:'+nxt,'2:GY'])
            own.update(character='arle',gauge=4,unconfirmed=200,normal_unconfirmed=200)
            reply=wait_move(self.engine.native,self.engine.scoring,own,120,1,budget_ms=1000)
            self.assertEqual(reply['searched_visible'],3)
            self.assertEqual(reply['wait_forecast']['choice']['projected_gauge'],7)
            self.assertEqual(reply['wait_forecast']['choice']['projected_popped'],12)
            self.assertEqual(reply['consumed_puyos'],0)
            answers.append((reply['x'],reply['r']))
        self.assertNotEqual(answers[0],answers[1])

    def test_wait_uses_only_observed_pending_and_stops_normal_forecast_at_entry(self):
        own=side('normal',list(EMPTY[:-1])+['RRRBBB'],['2:RB','2:RY','2:GY'])
        own.update(character='arle',gauge=6,confirmed=1000,normal_confirmed=1000)
        reply=wait_move(self.engine.native,self.engine.scoring,own,120,1,budget_ms=1000)
        self.assertTrue(reply['entry_pending_after_chain'])
        self.assertTrue(reply['wait_forecast']['choice']['survives'])
        self.assertEqual(reply['wait_forecast']['choice']['steps'],1)
        # A nonclear cannot survive the actual confirmed drop on this board.
        self.assertTrue(all(not c['survives'] for c in reply['wait_forecast']['candidates'] if c['popped']==0))
        own.update(confirmed=0,normal_confirmed=0,unconfirmed=0,normal_unconfirmed=0)
        self.assertIsNone(wait_move(self.engine.native,self.engine.scoring,own,120,1))
        own.update(unconfirmed=100,normal_unconfirmed=100)
        self.assertIsNone(wait_move(self.engine.native,self.engine.scoring,own,120,0))

    def test_wait_uses_next2_and_never_reads_a_fourth_piece(self):
        answers=[]
        for last in ('RR','BB'):
            own=side('normal',list(EMPTY[:-2])+['RRRBBB','GGGYYY'],['2:RB','2:GG','2:'+last])
            own.update(character='arle',gauge=4,unconfirmed=200,normal_unconfirmed=200)
            reply=wait_move(self.engine.native,self.engine.scoring,own,120,1,budget_ms=1000)
            self.assertEqual(reply['searched_visible'],3)
            answers.append((reply['x'],reply['r']))
        self.assertNotEqual(*answers)
        own['queue'].append('2:RY')
        with self.assertRaisesRegex(ValueError,'visible queue only'):
            wait_move(self.engine.native,self.engine.scoring,own,120,1)

    def test_wait_does_not_forecast_next_on_an_unknown_all_clear_seed(self):
        own=side('normal',list(EMPTY[:-1])+['RRRBBB'],['2:RB','2:RR','2:BB'])
        own.update(character='arle',gauge=3,unconfirmed=200,normal_unconfirmed=200)
        reply=wait_move(self.engine.native,self.engine.scoring,own,120,1,budget_ms=1000)
        # Clearing all eight colors supplies two offsets, then the normal
        # all-clear seed must be observed before forecasting another placement.
        direct=next(c for c in reply['wait_forecast']['candidates'] if (c['x'],c['r'])==(2,'U'))
        self.assertEqual(direct['projected_gauge'],direct['gauge_after'])
        self.assertEqual(direct['steps'],1)

    def test_wait_recovery_respects_reachable_whitelist(self):
        own=side('normal',list(EMPTY[:-1])+['RRRBBB'],['2:RB','2:RY','2:GY'])
        own.update(character='arle',gauge=6,unconfirmed=100,normal_unconfirmed=100)
        req=request(own);req.update(op='recover_placement',reachable_placements=[dict(x=5,r='U')])
        reply=self.engine.answer(req)
        self.assertEqual((reply['x'],reply['r']),(5,'U'))
        self.assertEqual(reply['reason'],'fever_wait_conserve')
        self.assertEqual(reply['consumed_puyos'],0)
        self.assertEqual(reply['wait_forecast']['choice']['projected_gauge'],7)

    def test_reference_metadata_and_decoder_do_not_guess_missing_entries(self):
        data = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['seeds']), 50)
        self.assertEqual([(p['kind'],p['seed_chain']) for p in data['missing']], [('kaidan',4),('zabuton',6)])
        self.assertFalse(data['color_mapping_verified_on_steam'])
        for seed in data['seeds']:
            self.assertEqual(decode(seed['encoding']), seed['field'])
            self.assertEqual(self.engine.native.ask(dict(op='resolve',field=seed['field']))['links'], [])
        for bad in ('a78x', 'a0b78', 'a999999999999', 'a77'):
            with self.assertRaises(ValueError):
                decode(bad)

    def test_shared_strategy_keeps_extension_under_small_pressure(self):
        own, enemy = side('fever'), side('fever')
        self.assertEqual(seed_strategy(own, enemy, 100)[0], 'extend')
        own['fever_confirmed'] = 1
        self.assertEqual(seed_strategy(own, enemy, 100)[0], 'extend')
        own['fever_confirmed'] = 0
        own['remaining_frames'] = 120
        self.assertEqual(seed_strategy(own, enemy, 100)[0], 'extend')

    def test_countdown_can_finish_active_chain_but_never_accept_stale_deadline(self):
        req = request()
        req['self']['remaining_frames'] = 50
        reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        self.assertTrue(reply['seed_forecast']['solved'])
        latest = copy.deepcopy(req)
        elapsed = 15
        latest['frame'] = elapsed
        latest['observation'].update(frame_before=elapsed, frame_after=elapsed)
        for who in ('self', 'enemy'):
            latest[who]['observed_frame'] = elapsed
        latest['self']['remaining_frames'] -= elapsed
        self.assertTrue(authorize_mode_reply(req, reply, latest))

    def test_json_lines_refuses_non_object_and_keeps_session_alive(self):
        with JsonProcess([sys.executable, '-m', 'fever_battle.mode_engine', '--native', NATIVE,
                          '--solo', SOLO, '--config', ROOT/'config.json'], cwd=ROOT) as engine:
            with self.assertRaises(ValueError):
                engine.ask(['not', 'an', 'observation'])
            self.assertEqual(engine.ask(request())['action'], 'place')


if __name__ == '__main__':
    unittest.main()
