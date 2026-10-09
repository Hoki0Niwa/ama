"""Gauge-aware attack roles retain main's resource classification."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, seed3, request
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import tactics

class AttackGaugeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
    @classmethod
    def tearDownClass(cls): cls.engine.close()
    def own(self,gauge=0):
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows=list(next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7'))
        rows[4:7]=['Y.....']*3
        own=side('normal',rows,['2:YG'])
        own.update(character='arle',gauge=gauge)
        return own
    def test_sufficient_entry_side_return_preserves_main_in_fever_battle(self):
        choices=[]
        for gauge in (0,6):
            own=self.own(gauge);own.update(confirmed=1,normal_confirmed=1)
            policy={**self.engine.policy['normal_tactics'],'main_trigger_points':2100}
            result=tactics.choose(self.engine.native,self.engine.scoring,own,30,1,policy,
                enemy=side('fever',seed3()),fever=dict(enemy_fever=True))
            choices.append(result['tactics_forecast']['choice'])
        self.assertEqual(choices[0]['attack_kind'],'main')
        self.assertEqual(choices[1]['attack_kind'],'side')
        self.assertTrue(choices[1]['enters_fever'])
        self.assertEqual(choices[1]['chain'],1)
    def response(self,gauge,pending,gain=1):
        # An observed first-piece 3-chain; a tiny packet runs out on its first link.
        enemy=side('normal',seed3(),['2:RY']);enemy.update(character='arle',gauge=gauge)
        defense={**self.engine._enemy_defense(enemy,[],120),'offset_gain':gain}
        enemy.update(confirmed=pending,normal_confirmed=pending)
        result=tactics.choose(self.engine.native,self.engine.scoring,side('normal'),120,1,
            self.engine.policy['normal_tactics'],enemy=enemy,defense=defense,allowed=[dict(x=0,r='U')])
        return result['tactics_forecast']['choice']['opponent_entry_possible']
    def test_enemy_entry_counts_actual_offsets_not_all_links(self):
        self.assertTrue(self.response(6,1))
        self.assertFalse(self.response(5,1))
        self.assertTrue(self.response(5,20))
        self.assertFalse(self.response(6,20,0))
    def test_enemy_counter_geometry_is_reused_when_only_gauge_changes(self):
        enemy=side('normal',seed3(),['2:RY']);enemy['character']='arle'
        self.engine.enemy_counter_profiles={}
        self.engine._enemy_defense(enemy,[],120)
        with patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as native:
            enemy['gauge']=6
            self.engine._enemy_defense(enemy,[],120)
        self.assertFalse(any(c.args[0]['op']=='placements' for c in native.call_args_list))
    def test_invitation_keeps_main_and_does_not_apply_after_first_fever(self):
        for own_gen,enemy_gen in ((0,0),(0,2),(2,0),(2,2)):
            own=self.own();enemy=side('normal')
            own['mode_generation']=own_gen;enemy['mode_generation']=enemy_gen
            with patch.object(tactics,'choose',return_value=None) as choose:
                self.engine._tactics(request(own,enemy),own,enemy,120)
            self.assertEqual(choose.call_args.kwargs['invite_fever'],own_gen==enemy_gen==0)
            self.assertEqual(choose.call_args.kwargs['avoid_own_fever'],own_gen==enemy_gen==0)
    def test_first_battle_avoids_own_entry_even_while_enemy_prepares_entry(self):
        own=self.own(6);own.update(confirmed=1,normal_confirmed=1)
        replies=[]
        for avoid in (False,True):
            result=tactics.choose(self.engine.native,self.engine.scoring,own,30,1,
                self.engine.policy['normal_tactics'],enemy=side('normal'),
                fever=dict(enemy_fever=True,enemy_fever_at=1000),avoid_own_fever=avoid,
                allowed=[dict(x=0,r='U')])
            replies.append(result['tactics_forecast']['choice'])
        self.assertTrue(replies[1]['enters_fever']) # forced legal move remains available
        self.assertLess(replies[1]['value'],replies[0]['value'])
        result=tactics.choose(self.engine.native,self.engine.scoring,own,30,1,
            self.engine.policy['normal_tactics'],enemy=side('normal'),
            fever=dict(enemy_fever=True,enemy_fever_at=1000),avoid_own_fever=True)
        self.assertFalse(result['tactics_forecast']['choice']['enters_fever'])
        self.assertEqual(result['chain'],0)
    def shot(self,gauge,invite=False):
        defense=dict(hold=0,kill=0,links=1,need=7-gauge,gauge=gauge,offset_gain=1,
                     rate=120,remainder=0,counter_points=[[40]])
        from unittest.mock import patch
        captured=[]
        ask=self.engine.native.ask
        def observe(request):
            reply=ask(request);captured.append(reply);return reply
        with patch.object(self.engine.native,'ask',side_effect=observe):
            result=tactics.choose(self.engine.native,self.engine.scoring,self.own(),1,1,
                self.engine.policy['normal_tactics'],enemy=side('normal'),defense=defense,
                allowed=[dict(x=0,r='U')],quiet=True,harass=True,invite_fever=invite)
        if invite and gauge==6:self.assertIsNotNone(result)
        else:self.assertIsNone(result)
        return captured[-1]['choice']
    def test_entry_invitation_is_credited_only_with_main_preserved(self):
        suppressed=self.shot(6)
        invited=self.shot(6,True)
        self.assertTrue(invited['opponent_entry_possible'])
        self.assertTrue(invited['invites_opponent_fever'])
        self.assertEqual(invited['attack_kind'],'side')
        self.assertGreater(invited['value'],suppressed['value'])
        self.assertFalse(self.shot(0,True)['invites_opponent_fever'])

if __name__=='__main__':unittest.main()
