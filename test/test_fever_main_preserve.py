"""Keep growing the configured main while handling a Fever opponent."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE,SOLO,side,seed3,request
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import tactics


class MainPreserveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
    @classmethod
    def tearDownClass(cls):cls.engine.close()

    def test_unrewarded_harassment_does_not_override_the_builder(self):
        own=side('normal',seed3(),['2:RY'])
        choice=dict(x=1,r='U',chain=0,sent=0,cancelled=0,dropped=0,
            projected_sent=1,projected_disrupt=0,projected_kill=0,
            projected_all_clear=False,projected_harass=False,attack_kind='build')
        with patch.object(self.engine.native,'ask',return_value=dict(choice=choice)):
            reply=tactics.choose(self.engine.native,self.engine.scoring,own,120,1,
                self.engine.policy['normal_tactics'],quiet=True,harass=True,builder=(0,'U'))
        self.assertIsNone(reply)

    def test_live_behind_opponent_has_no_harassment_reward(self):
        field='....../....../....../.Y..../.YR.../.GR.../GBG.../GRG.../BGBG../RBYG../RBGB../GBGY../GGYG../RBBGYR'.split('/')
        own=side('normal',field,['J:RYR','0:G','2:RR']);own['character']='rafisol'
        reply=tactics.choose(self.engine.native,self.engine.scoring,own,120,1,
            self.engine.policy['normal_tactics'],quiet=False,harass=True,enemy_hold=230,
            enemy=side('normal',seed3()),defense=dict(hold=230,kill=40,links=8,need=7))
        forecast=reply['tactics_forecast']
        self.assertLess(forecast['own_hold'],forecast['enemy_hold'])
        self.assertFalse(forecast['choice']['projected_harass'])

    def test_projected_main_does_not_make_a_small_shot_harassment(self):
        field='....../....../....../G...../Y.G.../G.R.../YGGR../YRGR../GRBG../GGYGR./YYGYR./YGGYG./GBRRGR/GGYBBR'.split('/')
        own=side('normal',field,['2:BG','2:YY','2:BY']);own['character']='rafisol'
        captured=[];ask=self.engine.native.ask
        def observe(req):
            value=ask(req);captured.append(value);return value
        with patch.object(self.engine.native,'ask',side_effect=observe):
            tactics.choose(self.engine.native,self.engine.scoring,own,120,1,
                self.engine.policy['normal_tactics'],quiet=True,harass=True,
                enemy=side('normal'),defense=dict(hold=0,kill=90,links=0,need=7))
        self.assertFalse(captured[-1]['choice']['projected_harass'])

    def test_kill_profile_cannot_add_attack_value(self):
        own=side('normal',seed3(),['2:RY']);own['character']='arle'
        choices=[]
        for kill in (0,6,72):
            result=tactics.choose(self.engine.native,self.engine.scoring,own,120,1,
                self.engine.policy['normal_tactics'],enemy=side('normal'),
                allowed=[dict(x=0,r='U')],defense=dict(hold=0,kill=kill,links=0,need=7))
            choice=result['tactics_forecast']['choice'];choices.append(choice)
            self.assertEqual(choice['projected_kill'],0)
        self.assertEqual(choices[0],choices[1])
        self.assertEqual(choices[0],choices[2])

    def test_uncertain_kill_does_not_spend_a_quiet_main(self):
        own=side('normal',seed3(),['2:RY'])
        choice=dict(x=1,r='U',chain=5,sent=10,cancelled=0,dropped=0,
            projected_sent=10,projected_disrupt=0,projected_kill=0.5,
            projected_all_clear=False,projected_harass=False,attack_kind='main')
        for attack_kind in ('main','side'):
            for estimate in (0.5,1):
                choice.update(attack_kind=attack_kind,projected_kill=estimate)
                with patch.object(self.engine.native,'ask',return_value=dict(choice=choice)):
                    reply=tactics.choose(self.engine.native,self.engine.scoring,own,120,1,
                        self.engine.policy['normal_tactics'],quiet=True,invite_fever=True,builder=(0,'U'))
                self.assertIsNone(reply)

    def test_live_seven_chain_is_not_spent_before_fifteen_target(self):
        field='....../....../.....G/....YG/..R.RB/..GRBR/..RYBR/..BRRY/..BRYB/..YYBY/.BYRBR/.RGGRR/GBRBYG/RBBYYG'.split('/')
        own=side('normal',field,['0:B','2:GY','4:BBYY']);own.update(character='rafisol',dropset_index=11)
        enemy=side('fever',seed3());enemy['character']='rafisol'
        req=request(own,enemy)
        with patch.object(self.engine.solo,'ask',return_value=dict(x=0,r='D',fire=False,chain=9)), \
             patch.object(self.engine,'_enemy_fever',return_value=dict(enemy_fever=True,enemy_seed_level=5,enemy_reply_nuisance=44)):
            self.engine.normal_build_cache=None
            reply=self.engine.answer(req)
        self.assertEqual((reply['x'],reply['r'],reply['fire']),(0,'D',False))
        self.assertEqual(reply['normal_build_target_chain'],15)

    def test_future_main_does_not_pay_for_the_current_one_chain(self):
        field='....../....../....YG/....RG/...GGB/..GRBR/..RYBR/..BRRY/..BRYB/..YYBY/.BYRBR/.RGGRR/GBRBYG/RBBYYG'.split('/')
        own=side('normal',field,['L:GGR','0:B','2:GY']);own['character']='rafisol'
        result=tactics.choose(self.engine.native,self.engine.scoring,own,120,1,
            self.engine.policy['normal_tactics'],enemy=side('fever',seed3()),
            allowed=[dict(x=2,r='R')],fever=dict(enemy_fever=True,enemy_reply_nuisance=44),
            defense=dict(hold=239,kill=0,links=0,need=7))
        choice=result['tactics_forecast']['choice']
        self.assertEqual(choice['chain'],1)
        self.assertEqual(choice['projected_disrupt'],0)

    def test_completed_builder_fire_is_distinct_from_a_tactical_main(self):
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        field=next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7')
        own=side('normal',field,['2:RY']);own['character']='arle'
        moves=self.engine.native.ask(dict(op='placements',field=field,piece='2:RY'))['placements']
        fire=max(moves,key=lambda m:len(m['links']))
        for authorized in (False,True):
            reply=tactics.choose(self.engine.native,self.engine.scoring,own,120,1,self.engine.policy['normal_tactics'],
                enemy=side('fever',seed3()),allowed=[dict(x=fire['x'],r=fire['r'])],quiet=True,
                builder=(fire['x'],fire['r']),builder_fire=authorized,
                fever=dict(enemy_fever=True,enemy_reply_nuisance=6),defense=dict(hold=6,kill=0,links=0,need=7))
            if authorized:self.assertEqual(reply['reason'],'tactics_disrupt')
            else:self.assertIsNone(reply)

    def test_small_fever_packet_keeps_the_configured_second_builder(self):
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        field=list(next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7'))
        field[4:7]=['Y.....']*3
        own=side('normal',field,['2:YG'])
        own.update(character='arle',mode_generation=2,confirmed=1,normal_confirmed=1)
        enemy=side('fever',seed3());enemy['character']='arle'
        req=request(own,enemy);req['second_target_chain']=13
        with patch.object(self.engine.solo,'ask',return_value=dict(x=5,r='U',fire=False,chain=9)), \
             patch.object(self.engine,'_enemy_fever',return_value=dict(enemy_fever=True,enemy_seed_level=5,enemy_reply_nuisance=44)):
            self.engine.normal_build_cache=None
            reply=self.engine.answer(req)
        self.assertFalse(reply['fire'])
        self.assertEqual(reply['normal_build_target_chain'],13)

    def test_reaching_the_configured_target_still_allows_normal_fire(self):
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        field=next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7')
        own=side('normal',field,['2:RY']);own['character']='arle'
        enemy=side('fever',seed3());enemy['character']='arle'
        req=request(own,enemy);req['solo_options']['trigger']=7
        self.engine.normal_build_cache=None
        reply=self.engine.answer(req)
        self.assertTrue(reply['fire'])
        self.assertGreaterEqual(reply['next_chain'],7)


if __name__=='__main__':unittest.main()
