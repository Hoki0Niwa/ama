"""Spawn hints, deferred tactics, known nuisance landings and cold search width."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, request, seed3
from fever_battle.mode_engine import ModeBattleEngine, preview_prepared


class SpawnLatencyTests(unittest.TestCase):
    def setUp(self):
        self.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        self.addCleanup(self.engine.close)

    def own(self, pieces=3):
        own=side('normal',queue=['2:RG','2:BY','2:YY'][:pieces])
        own['character']='arle'
        return own

    def hint(self):
        req=request(self.own(2));req['op']='prepare_observed'
        answer=self.engine.answer(req)
        self.assertTrue(answer['prepared'])
        state=json.loads(json.dumps(answer['prepared_state']))
        live=request(self.own());live['frame']=10
        live['observation'].update(frame_before=10,frame_after=10)
        for p in ('self','enemy'):live[p]['observed_frame']=10
        return state,live

    def test_preview_has_no_search_or_native_ipc_and_accepts_late_bookkeeping(self):
        state,live=self.hint()
        live['self'].update(gauge=1,moves_since_chain=2,normal_unconfirmed=20,unconfirmed=20)
        with patch.object(self.engine.native,'ask',side_effect=AssertionError('no IPC')):
            reply=preview_prepared(state,live)
        self.assertIsNotNone(reply)
        self.assertTrue(reply['execution_prefetched'])
        self.assertEqual(reply['search_ms'],0)

    def test_preview_rejects_board_fixed_delivery_options_new_seed_and_imminent_end(self):
        state,live=self.hint()
        for change in ('board','fixed','options','seed','end'):
            model,req=deepcopy(state),deepcopy(live)
            if change=='board':req['self']['field'][-1]='R.....'
            elif change=='fixed':req['self'].update(confirmed=1,normal_confirmed=1)
            elif change=='options':req['solo_options']['beam_width']=11
            elif change=='seed':req['enemy']['seed_id']+=1
            else:model['delivery_frame']=req['frame']+model['delivery_check_frames']
            self.assertIsNone(preview_prepared(model,req),change)

    def test_fever_preview_checks_actual_clock_and_saved_placement_deadline(self):
        req=request(side('fever',seed3(),['2:RY','2:GG']))
        req['op']='prepare_observed'
        answer=self.engine.answer(req)
        self.assertTrue(answer['prepared'])
        state=answer['prepared_state']
        live=deepcopy(req);live['op']='think';live['frame']=10
        live['observation'].update(frame_before=10,frame_after=10)
        for p in ('self','enemy'):live[p]['observed_frame']=10
        live['self']['remaining_frames']=890
        live['self']['queue'].append('L:RRY')
        reply=preview_prepared(state,live)
        self.assertIsNotNone(reply)
        self.assertTrue(reply['seed_search_reused'])
        live['self']['remaining_frames']=state['minimum_clock_frames']
        self.assertIsNone(preview_prepared(state,live))

    def test_refinement_uses_build_cache_but_runs_tactics(self):
        state,live=self.hint();live.update(op='refine_placement',prepared_state=state)
        with patch.object(self.engine,'_tactical_decision',wraps=self.engine._tactical_decision) as tactics, \
             patch.object(self.engine.solo,'ask',side_effect=AssertionError('build already prepared')):
            reply=self.engine.answer(live)
        tactics.assert_called_once()
        self.assertEqual(reply['action'],'place')

    def test_confirmed_delivery_predicts_next_board_and_partial_cursor(self):
        own=self.own();own.update(confirmed=7,normal_confirmed=7,garbage_phase=2)
        req=request(own);req['placement']=dict(x=3,r='U')
        future=self.engine._after_placement(req,own)
        self.assertIsInstance(future,dict)
        self.assertEqual(future['confirmed'],0)
        self.assertEqual(future['normal_confirmed'],0)
        self.assertEqual(future['garbage_phase'],3)
        self.assertEqual(sum(row.count('#') for row in future['field']),7)
        # One full row and an extra nuisance in GARBAGE_ORDER[2] (column 2).
        self.assertEqual(sum(row[2]=='#' for row in future['field']),2)
        own['garbage_phase']=None
        self.assertEqual(self.engine._after_placement(req,own),'confirmed_nuisance_falls_on_unknown_columns')

    def test_observed_pending_delivery_predicts_before_fall_and_preserves_residual_tray(self):
        own=self.own(2);own.update(confirmed=31,normal_confirmed=31,pending_drop=True)
        req=request(own);req['op']='prepare_observed'
        answer=self.engine.answer(req)
        self.assertTrue(answer['prepared'])
        future=answer['prepared_state']['execution_request']['self']
        self.assertNotIn('pending_drop',future)
        self.assertEqual(future['confirmed'],1)
        self.assertEqual(sum(row.count('#') for row in future['field']),30)

    def test_unknown_cursor_can_predict_full_rows_but_rejects_dead_spawn(self):
        own=self.own();own.update(confirmed=30,normal_confirmed=30,garbage_phase=None)
        future=self.engine._after_confirmed_drop(own)
        self.assertIsInstance(future,dict)
        own['field']=['......']*3+['RRRRRR']*11
        self.assertEqual(self.engine._after_confirmed_drop(own),'predicted_delivery_blocks_spawn')

    def test_only_cold_build_miss_caps_width_and_does_not_poison_full_width_cache(self):
        own=self.own();options=dict(self.engine.policy['solo_options'],beam_width=250,beam_depth=3)
        self.engine.build_match='cold-test';self.engine.cold_spawn=True
        with patch.object(self.engine.solo,'ask',return_value={'x':2,'r':'U'}) as build:
            self.engine._solo_build(own,options)
        self.assertEqual(build.call_args.args[0]['beam_width'],50)
        self.engine.cold_spawn=False
        with patch.object(self.engine.solo,'ask',return_value={'x':2,'r':'U'}) as build:
            self.engine._solo_build(own,options)
        self.assertEqual(build.call_args.args[0]['beam_width'],250)


if __name__=='__main__':unittest.main()
