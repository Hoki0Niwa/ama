"""The engine's one measure under held packets; the explicit strategies kept for comparison."""
from copy import deepcopy
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
            own=side('fever',seed3(),['2:RY']);own.update(normal_confirmed=held)
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


if __name__=='__main__':unittest.main()
