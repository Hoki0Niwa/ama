"""Every available reference family and direct live-board counter geometry."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE,SOLO,side,request,seed3
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import tactics,disruption
from fever_battle.seed_defense import canonical


class SeedDefenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        cls.seeds=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))['seeds']
    @classmethod
    def tearDownClass(cls):cls.engine.close()

    def profile(self,seed,amounts=(12,),queue=None,**limits):
        return self.engine.native.ask(dict(op='seed_defense',field=seed['field'],seed_chain=seed['seed_chain'],
            queue=queue or ['2:RG','0:Y','0:B'],amounts=list(amounts),
            max_nodes=limits.get('max_nodes',1000000),budget_ms=limits.get('budget_ms',1000),
            unknown_garbage_phase=True,powers=self.engine.scoring.data['characters']['arle']['fever'],
            bonuses=self.engine.scoring.data['bonuses']))

    def test_all_fifty_reference_seeds_are_checked_without_family_exceptions(self):
        self.assertEqual({s['kind'] for s in self.seeds},{'hirazumi','hasamikomi','kaidan','zabuton'})
        for seed in self.seeds:
            with self.subTest(seed=seed['id']):
                result=self.profile(seed)
                self.assertFalse(result['cutoff'])
                self.assertTrue(result['profiles'][12]['checked'])
                self.assertIn((seed['id'],seed['kind']),self.engine.seed_defenses.templates[canonical(seed['field'])])

    def test_low_staircase_and_cushion_can_still_fire_after_two_rows(self):
        for seed in self.seeds:
            if seed['id'] in ('kaidan-3','zabuton-3'):
                result=self.profile(seed)['profiles'][12]
                self.assertTrue(result['regular_after_drop'])
                self.assertGreater(result['counter_points'],0)

    def test_low_seed_that_tolerates_actual_packet_is_not_given_extension_reward(self):
        rows=list(next(s['field'] for s in self.seeds if s['id']=='hirazumi-7'));rows[4:7]=['Y.....']*3
        own=side('normal',rows,['2:YG']);own['character']='arle'
        for seed in self.seeds:
            if seed['id'] not in ('kaidan-3','zabuton-3'):continue
            enemy=side('fever',seed['field'],['2:RG','0:Y','0:B']);enemy['character']='arle'
            profile=self.profile(seed,(13,))['profiles']
            self.assertTrue(profile[13]['regular_after_drop'])
            target=self.engine._enemy_fever(enemy,[],3)
            target['enemy_seed_defense']=profile
            reply=tactics.choose(self.engine.native,self.engine.scoring,own,3,1,self.engine.policy['normal_tactics'],
                allowed=[dict(x=0,r='U')],enemy=enemy,quiet=True,
                defense=dict(hold=target['enemy_reply_nuisance'],kill=0,links=0,need=7),fever=target)
            self.assertIsNone(reply)

    def test_colored_live_seed_is_evaluated_independently_of_template_label(self):
        seed=deepcopy(next(s for s in self.seeds if s['id']=='kaidan-3'))
        before=self.profile(seed)['profiles'][12]
        table=str.maketrans('RYGB','GBRY');seed['field']=[r.translate(table) for r in seed['field']]
        after=self.profile(seed,queue=[p.translate(table) for p in ['2:RG','0:Y','0:B']])['profiles'][12]
        self.assertEqual((before['regular_after_drop'],before['counter_points']),
                         (after['regular_after_drop'],after['counter_points']))

    def test_cutoff_is_unknown_and_not_proof_that_counter_is_impossible(self):
        result=self.profile(self.seeds[0],max_nodes=1)
        self.assertTrue(result['cutoff'])
        self.assertFalse(result['profiles'][12]['checked'])

    def test_defense_cache_skips_duplicate_same_frame_and_completed_board(self):
        enemy=side('fever',seed3(),['2:RG','0:Y','0:B'])
        cache=self.engine.seed_defenses;cache.cache.clear()
        with patch.object(cache.native,'ask',wraps=cache.native.ask) as worker:
            cache.observe(enemy,True,1)
            count=worker.call_count
            cache.observe(enemy,True,1)
            self.assertEqual(worker.call_count,count)

    def test_extension_pressure_requires_checked_blockage_and_expire_on_seed_fire(self):
        refs=self.seeds
        rows=list(next(s['field'] for s in refs if s['id']=='hirazumi-7'));rows[4:7]=['Y.....']*3
        own=side('normal',rows,['2:YG']);own['character']='arle'
        enemy=side('fever',seed3())
        for checked,safe,expected in ((True,False,'extension_pressure'),(True,True,'none'),(False,False,'none')):
            profiles=[dict(checked=checked,regular_after_drop=safe,counter_points=0) for _ in range(31)]
            result=tactics.choose(self.engine.native,self.engine.scoring,own,3,1,self.engine.policy['normal_tactics'],
                allowed=[dict(x=0,r='U')],enemy=enemy,defense=dict(hold=1000000,kill=0,links=0,need=7),
                fever=dict(enemy_fever=True,enemy_reply_nuisance=1000000,enemy_extending=True,enemy_seed_defense=profiles))
            self.assertEqual(result['tactics_forecast']['choice']['disruption_kind'],expected)
            if expected=='extension_pressure':
                req=request(own,enemy);reply=result
                reply['reason']='tactics_disrupt'
                guard=disruption.contract(req,reply,{})
                self.assertEqual(guard['kind'],'extension_pressure')
                reply['disruption_timing']=guard
                self.assertTrue(disruption.valid(reply,req))
                newer=deepcopy(req);newer['enemy']['phase']='chain'
                self.assertFalse(disruption.valid(reply,newer))


if __name__=='__main__':unittest.main()
