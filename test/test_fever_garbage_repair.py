"""Small drops preserve a seed, including repairs behind a buried ignition."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'test'))
from fever_fixtures import NATIVE, SOLO, side, request
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.timing import ChainTiming
from fever_battle.uncertainty import outcomes
from tools.verify_fever_extension import verify


class GarbageRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        cls.capture=next(s for s in json.loads((ROOT/'data/fever/baselines/2026-10-06-fever-watch-failure-replay.json').read_text(encoding='utf-8'))['results'] if s['case']['epoch']==10)

    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def captured(self, count=1, held=16, remaining=779):
        req=deepcopy(self.capture['request']); own=req['self']
        own.update(confirmed=count,fever_confirmed=count,normal_confirmed=held,remaining_frames=remaining)
        key=(req['match_id'],own['mode_generation'],own['seed_id'],own['character'])
        self.engine.seed_solver.seed_origin=(key,self.capture['seed_origin'])
        return req

    def repair_side(self, phase=None, remaining=900):
        ref=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        seed=next(s for s in ref['seeds'] if s['id']=='hirazumi-5')
        own=side('fever',seed['field'],['2:YB','2:BR','2:BG'])
        own.update(character='arle',seed_chain=5,seed_base=5,confirmed=1,fever_confirmed=1,
                   normal_confirmed=20,garbage_phase=phase,garbage_phase_status='unknown' if phase is None else 'observed',remaining_frames=remaining)
        return own

    def test_recorded_early_three_chain_builds_after_small_drops_with_or_without_held_normal_packet(self):
        for count in (1,2,4,6,12):
            for held in (0,16):
                with self.subTest(count=count,held=held):
                    req=self.captured(count,held); reply=self.engine.answer(req)
                    result=reply['seed_forecast']; first=result['choice']
                    self.assertEqual(reply['chain'],0)
                    self.assertTrue(result['early_failure_deferred'])
                    self.assertFalse(result['intentional_seed_failure'])
                    self.assertEqual(first['dropped'],count)
                    self.assertFalse(first['dead'])
                    self.assertEqual(len(result['path']),1)
                    verify(self.engine.native,self.engine.scoring,req['self'],result)
                    for board,is_dead in outcomes(first['locked_field'],count):
                        self.assertFalse(is_dead)
                    if count%6:
                        self.assertTrue(first['all_drop_cases_keep_ignition'])
                        self.assertIsNone(reply['next_field'])

    def test_large_drop_can_still_force_a_counter_instead_of_a_dead_build(self):
        reply=self.engine.answer(self.captured(80))
        self.assertGreater(reply['chain'],0)
        self.assertTrue(reply['seed_forecast']['intentional_seed_failure'])
        self.assertFalse(reply['seed_forecast']['early_failure_deferred'])

    def test_short_clock_does_not_spend_last_piece_waiting_for_garbage_animation(self):
        reply=self.engine.answer(self.captured(1,16,80))
        self.assertGreater(reply['chain'],0)
        self.assertFalse(reply['seed_forecast']['early_failure_deferred'])
        first=reply['seed_forecast']['choice']
        cached=dict(fire=False,seed_forecast=dict(choice=dict(end_at=45,dropped=1)))
        self.assertFalse(self.engine._failure_build_allows(self.captured(remaining=80)['self'],cached))

    def test_buried_target_is_repaired_with_visible_next_two_pieces_in_every_drop_column(self):
        own=self.repair_side(); req=request(own); req['seed_options']['strategy']='extend'
        reply=self.engine.answer(req)
        result=reply['seed_forecast']; first=result['choice']
        self.assertEqual(reply['chain'],0)
        self.assertLess(first['extension_potential']['chain'],own['seed_chain'])
        self.assertFalse(first['target_ignition_preserved'])
        self.assertTrue(first['visible_target_repair_all_drop_cases'])
        self.assertIsNone(reply['next_field'])
        self.assertEqual(len(result['path']),1)
        boards=list(outcomes(first['locked_field'],1)); self.assertEqual(len(boards),6)
        for board,is_dead in boards:
            self.assertFalse(is_dead)
            future=dict(own,field=board,queue=own['queue'][1:],confirmed=0,fever_confirmed=0,
                        normal_confirmed=0,remaining_frames=own['remaining_frames']-first['end_at']-80)
            repaired=self.engine.seed_solver.solve(future,120,True,dict(strategy='quick',budget_ms=500))
            self.assertTrue(repaired['solved'])
            self.assertEqual(repaired['path'][0]['chain'],0)
            self.assertGreaterEqual(repaired['path'][-1]['chain'],5)
            verify(self.engine.native,self.engine.scoring,future,repaired)

    def test_known_drop_uses_same_repair_and_clock_cuts_off_the_visible_plan(self):
        own=self.repair_side(phase=2)
        req=request(own);req['seed_options']['strategy']='extend'
        repaired=self.engine.answer(req)['seed_forecast']
        self.assertTrue(repaired['choice']['visible_target_repair_all_drop_cases'])
        verify(self.engine.native,self.engine.scoring,own,repaired)
        own['remaining_frames']=130
        req=request(own);req['seed_options']['strategy']='extend'
        short=self.engine.answer(req)['seed_forecast']
        self.assertFalse(short['choice'].get('visible_target_repair_all_drop_cases',False))

    def test_animation_budget_is_separate_from_drop_check_and_has_fixed_observed_evidence(self):
        report=json.loads((ROOT/'data/fever/baselines/2026-10-06-fever-garbage-ready.json').read_text(encoding='utf-8'))
        exact=report['exact_measurements']
        self.assertEqual(sorted((s['count'],s['drop_to_operable_frames']) for s in exact),[(1,46),(4,50),(12,55),(30,71)])
        timing=ChainTiming.for_mode('fever')
        self.assertEqual(timing.nuisance_check_frames,14)
        self.assertEqual(timing.nuisance_ready_frames,80)
        self.assertGreater(timing.nuisance_ready_frames,max(s['drop_to_operable_frames'] for s in exact))

    def test_unknown_future_colors_are_reobserved_until_regular_ignition_is_visible_after_four_repairs(self):
        own=self.repair_side(phase=2,remaining=1500)
        own.update(normal_confirmed=0,mode_generation=1,seed_id=42,piece_id=100)
        sequence=['2:YR','2:YR','2:BR','2:GY','2:BY','2:YB','2:GY']
        chains=[]
        key=('long-repair',own['mode_generation'],own['seed_id'],own['character'])
        # This seed has already used more moves than ordinary extension patience.
        self.engine.seed_solver.seed_origin=(key,0)
        for i in range(5):
            own['queue']=sequence[i:i+3]
            result=self.engine.seed_solver.solve(own,120,True,dict(strategy='quick' if i==4 else 'extend'),match_id=key[0])
            first=result['choice']; chains.append(first['chain'])
            verify(self.engine.native,self.engine.scoring,own,result)
            self.assertGreater(result['extension_moves'],result['extension_patience'])
            if i==0:
                self.assertFalse(result['solved'])
                self.assertFalse(first['visible_target_repair_all_drop_cases'])
            if i<4:
                self.assertEqual(first['chain'],0)
                self.assertTrue(first['repair_workspace_available'])
                self.assertEqual(first['repair_status'],'reobserve_each_piece_unknown_colors_not_proven')
                own.update(field=first['field'],confirmed=0,fever_confirmed=0,piece_id=own['piece_id']+1,
                           remaining_frames=own['remaining_frames']-first['end_at']-(80 if first['dropped'] else 12))
        self.assertEqual(chains[:4],[0,0,0,0])
        self.assertTrue(result['solved'])
        self.assertGreaterEqual(result['path'][-1]['chain'],5)

    def test_repair_preparation_with_no_remaining_packet_still_checks_next_input_time(self):
        own=self.captured(0,0,80)['self']
        cached=dict(fire=False,seed_forecast=dict(choice=dict(end_at=45,dropped=0,repair_workspace_available=True)))
        self.assertFalse(self.engine._failure_build_allows(own,cached))
        own['remaining_frames']=100
        self.assertTrue(self.engine._failure_build_allows(own,cached))

    def test_existing_garbage_and_no_visible_solution_keep_repairing_without_a_pending_packet(self):
        from fever_battle.model import EMPTY
        rows=list(EMPTY); rows[-1]='RRR#BB'
        own=side('fever',rows,['2:RY']); own.update(seed_chain=5,seed_base=5)
        result=self.engine.seed_solver.solve(own,120,True,dict(strategy='quick'))
        self.assertFalse(result['solved'])
        self.assertEqual(result['choice']['chain'],0)
        self.assertTrue(result['early_failure_deferred'])
        self.assertTrue(result['choice']['repair_workspace_available'])
        self.assertTrue(any('#' in r for r in result['choice']['field']))
        self.assertFalse(result['requires_new_seed_after_clear'])
        verify(self.engine.native,self.engine.scoring,own,result)


if __name__=='__main__': unittest.main()
