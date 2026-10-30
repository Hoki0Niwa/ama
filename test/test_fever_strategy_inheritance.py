"""Registering a new strategy must retain the complete common decision pipeline."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from fever_fixtures import ROOT,NATIVE,SOLO,side,request,seed3
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import strategy


class StrategyInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.profiles=patch.dict(strategy.PROFILES,{
            'inherited_test':{},'pressure_test':dict(pressure_style=True)})
        self.profiles.start()

    def tearDown(self):self.profiles.stop()

    def answer(self,req,name):
        engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        try:
            q=deepcopy(req);q['normal_tactics']=dict(strategy=name)
            return engine.answer(q)
        finally:engine.close()

    def test_new_profiles_inherit_shared_all_clear_without_a_new_name_branch(self):
        own=side('normal',['......']*13+['RRRBBB'],['2:RB']);own['character']='arle'
        for name in ('inherited_test','pressure_test'):
            reply=self.answer(request(own),name)
            self.assertEqual(reply['reason'],'tactics_all_clear')
            self.assertTrue(reply['next_all_clear'])
            self.assertEqual(reply['strategy']['name'],name)

    def test_new_profile_keeps_build_second_defense_and_seed_decisions(self):
        build=request(side('normal',queue=['2:RY','2:BB','L:RRY']))
        second=deepcopy(build);second['self']['normal_chain_max']=14
        seed=request(side('fever',seed3(),['2:RY','2:BG']))
        defense=json.loads((ROOT/'data/fever/golden/small-attack-main-preservation.json').read_text(encoding='utf-8'))['cases'][0]['request']
        for label,req in (('build',build),('second',second),('defense',defense),('seed',seed)):
            with self.subTest(decision=label):
                base=self.answer(req,'mainline');inherited=self.answer(req,'inherited_test')
                for key in ('action','x','r','next_chain','next_score','normal_fire_policy'):
                    self.assertEqual(inherited.get(key),base.get(key),key)
                self.assertEqual(inherited['strategy']['phase'],base['strategy']['phase'])
                if label=='defense':self.assertIn('tactics_forecast',inherited)
                if label=='second':self.assertEqual(inherited['normal_fire_policy'],'second_target_or_full')
                if label=='seed':self.assertIn('seed_forecast',inherited)

    def test_pressure_only_profile_still_uses_shared_defense_and_seed(self):
        req=json.loads((ROOT/'data/fever/golden/small-attack-main-preservation.json').read_text(encoding='utf-8'))['cases'][0]['request']
        defense=self.answer(req,'pressure_test')
        self.assertEqual(defense['action'],'place')
        self.assertIn('tactics_forecast',defense)
        self.assertTrue(defense['tactics_forecast']['choice']['current_survives'])
        seed=self.answer(request(side('fever',seed3(),['2:RY','2:BG'])),'pressure_test')
        self.assertEqual(seed['strategy']['phase'],'seed')
        self.assertIn('seed_forecast',seed)

    def test_profile_defaults_are_complete_independent_copies(self):
        req={'normal_tactics':{'strategy':'inherited_test'}}
        self.assertEqual(strategy.profile(req),strategy.profile({}))
        profile=strategy.profile(req);profile['pressure_style']=True
        self.assertFalse(strategy.profile(req)['pressure_style'])


if __name__=='__main__':unittest.main()
