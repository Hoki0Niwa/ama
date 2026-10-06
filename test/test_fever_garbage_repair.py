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
from fever_battle.seed_solver import verify


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

    def test_recorded_position_under_the_value_measure_is_legal_and_survives(self):
        req=self.captured(1,16); reply=self.engine.answer(req)
        result=reply['seed_forecast']; first=result['choice']
        self.assertEqual(result['strategy'],'value')
        self.assertFalse(first['dead'])
        self.assertIn('expected_points',first)
        verify(self.engine.native,self.engine.scoring,req['self'],result)

    def test_large_drop_can_still_force_a_counter_instead_of_a_dead_build(self):
        reply=self.engine.answer(self.captured(80))
        self.assertGreater(reply['chain'],0)
        self.assertTrue(reply['seed_forecast']['intentional_seed_failure'])

    def test_short_clock_does_not_spend_last_piece_waiting_for_garbage_animation(self):
        reply=self.engine.answer(self.captured(1,16,80))
        self.assertGreater(reply['chain'],0)
        first=reply['seed_forecast']['choice']
        cached=dict(fire=False,seed_forecast=dict(choice=dict(end_at=45,dropped=1)))
        self.assertFalse(self.engine._stacking_still_fits(self.captured(remaining=80)['self'],cached))

    def test_animation_budget_is_separate_from_drop_check_and_has_fixed_observed_evidence(self):
        report=json.loads((ROOT/'data/fever/baselines/2026-10-06-fever-garbage-ready.json').read_text(encoding='utf-8'))
        exact=report['exact_measurements']
        self.assertEqual(sorted((s['count'],s['drop_to_operable_frames']) for s in exact),[(1,46),(4,50),(12,55),(30,71)])
        timing=ChainTiming.for_mode('fever')
        self.assertEqual(timing.nuisance_check_frames,14)
        self.assertEqual(timing.nuisance_ready_frames,80)
        self.assertGreater(timing.nuisance_ready_frames,max(s['drop_to_operable_frames'] for s in exact))

if __name__=='__main__': unittest.main()
