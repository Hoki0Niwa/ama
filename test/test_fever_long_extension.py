"""The engine's one measure under held packets; the explicit strategies kept for comparison."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'test'))
from fever_fixtures import NATIVE,SOLO,side,request,seed3
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.seed_solver import verify
from fever_battle.mode import next_seed


class LongExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
    @classmethod
    def tearDownClass(cls):cls.engine.close()

    def test_engine_uses_the_value_measure_whatever_the_held_packet(self):
        for held in (10,1000):
            own=side('fever',seed3(),['2:RY','2:GG']);own.update(normal_confirmed=held)
            reply=self.engine.answer(request(own))
            self.assertEqual(reply['seed_forecast']['strategy'],'value')
            self.assertEqual(reply['seed_strategy_reason'],'expected_points_by_the_end_of_this_fever')
            self.assertNotIn('seed_strategy_plan',reply)
            self.assertIn('expected_points',reply['seed_forecast']['choice'])
            # A seed the visible piece fires at its level is fired, held packet or not.
            self.assertGreaterEqual(reply['chain'],3)

    def test_prepared_decision_is_rechecked_when_held_or_flying_nuisance_changes(self):
        own=side('fever',seed3(),['2:RY','2:BB','2:GY']);own.update(normal_confirmed=10)
        req=request(own);before=self.engine._signature(req,own)
        own['normal_confirmed']=1000
        self.assertNotEqual(before,self.engine._signature(req,own))
        own['normal_confirmed']=10;before=self.engine._signature(req,own)
        own.update(unconfirmed=1000,fever_unconfirmed=1000)
        self.assertNotEqual(before,self.engine._signature(req,own))

    def test_large_seed_fires_early_to_keep_time_for_the_third_seed(self):
        seeds = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text())['seeds']
        boards = {seed['id']: seed['field'] for seed in seeds}
        for level, clock in ((14, 1750), (15, 1860)):
            with self.subTest(level=level):
                own = side('fever', boards[f'hirazumi-{level}'], ['2:RB', '2:BY'])
                own.update(seed_chain=level, seed_base=level, remaining_frames=clock)
                result = self.engine.seed_solver.solve(own, 120, True)
                self.assertEqual([step['chain'] for step in result['path']], [level])
                self.assertTrue(result['choice']['completed_before_timeout'])
                verify(self.engine.native, self.engine.scoring, own, result)

    def test_large_seed_can_still_extend_when_the_third_seed_reserve_does_not_apply(self):
        seeds = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text())['seeds']
        seed = next(seed for seed in seeds if seed['id'] == 'hirazumi-15')
        own = side('fever', seed['field'], ['2:RB', '2:BY'])
        own.update(seed_chain=15, seed_base=15, remaining_frames=1860)
        paused = self.engine.seed_solver.solve(own, 120, False)
        self.assertEqual([step['chain'] for step in paused['path']], [0, 15])
        short = self.engine.seed_solver.solve(dict(own, remaining_frames=900), 120, True)
        self.assertEqual([step['chain'] for step in short['path']], [0, 15])
        self.assertFalse(short['path'][-1]['completed_before_timeout'])


if __name__=='__main__':unittest.main()
