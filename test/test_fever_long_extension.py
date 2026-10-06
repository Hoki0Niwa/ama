"""Large held packets grow the next entry; repayable packets consume seeds."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'test'))
from test_fever_mode import NATIVE,SOLO,side,request,seed3
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.mode_tactics import seed_turnover_plan
from tools.verify_fever_extension import verify
from fever_battle.mode import next_seed


class LongExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
    @classmethod
    def tearDownClass(cls):cls.engine.close()

    def test_repayable_packet_consumes_but_large_held_packet_grows_next_entry(self):
        own=side('fever',seed3(),['2:RY']);own.update(normal_confirmed=10)
        consume=self.engine.answer(request(own))
        self.assertEqual(consume['seed_forecast']['strategy'],'quick')
        self.assertTrue(consume['seed_forecast']['prefer_seed_turnover'])
        self.assertTrue(consume['seed_strategy_plan']['packet_fits_estimate'])
        self.assertGreaterEqual(consume['chain'],3)
        own['normal_confirmed']=1000
        grow=self.engine.answer(request(own))
        self.assertEqual(grow['seed_forecast']['strategy'],'extend')
        self.assertFalse(grow['seed_forecast']['prefer_seed_turnover'])
        self.assertFalse(grow['seed_strategy_plan']['packet_fits_estimate'])
        self.assertEqual(grow['chain'],0)
        self.assertEqual(grow['seed_forecast']['desired_chain'],15)
        self.assertIn('next_entry',grow['seed_strategy_reason'])

    def test_template_counter_capacity_depends_on_clock_character_and_current_rate(self):
        own=side('fever');own.update(normal_confirmed=1000)
        a=seed_turnover_plan(own,self.engine.scoring,120)
        b=seed_turnover_plan(own,self.engine.scoring,60)
        self.assertGreater(a['estimated_seed_count'],1)
        self.assertGreater(b['estimated_counter_capacity'],a['estimated_counter_capacity'])
        own['remaining_frames']=300
        c=seed_turnover_plan(own,self.engine.scoring,120)
        self.assertLess(c['estimated_counter_capacity'],a['estimated_counter_capacity'])
        self.assertEqual(a['status'],'template_current_rate_unseen_seed_success_not_proven')

    def test_large_pressure_does_not_override_explicit_consumption_comparison(self):
        own=side('fever',seed3());own['normal_confirmed']=1000
        req=request(own);req['seed_options']['strategy']='quick'
        answer=self.engine.answer(req)
        self.assertEqual(answer['seed_strategy_reason'],'explicit_common_strategy')
        self.assertFalse(answer['seed_forecast']['prefer_seed_turnover'])

    def test_long_build_cached_above_unknown_color_reserve_is_rechecked_at_boundary(self):
        own=side('fever',seed3());own['normal_confirmed']=1000
        answer=self.engine.answer(request(own));result=answer['seed_forecast']
        self.assertEqual(answer['chain'],0)
        own['remaining_frames']=result['choice']['end_at']+result['unknown_build_reserve_frames']
        self.assertFalse(self.engine._failure_build_allows(own,answer))

    def test_observed_three_only_reaches_nine_links_with_sixteen_frames_to_ignite(self):
        queue=self.engine.native.ask(dict(op='queue',character='raffina',seed=2,count=32))['queue']
        ref=self.engine.seed_solver
        source=__import__('json').loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows=next(s['field'] for s in source['seeds'] if s['id']=='hirazumi-3')
        own=side('fever',rows);own.update(normal_confirmed=1000,remaining_frames=600,seed_id=123)
        steps=[]
        for i in range(20):
            own['queue']=queue[i:i+3];own['piece_id']=i
            result=ref.solve(own,120,True,dict(strategy='extend'),match_id='long-deadline-regression')
            verify(self.engine.native,self.engine.scoring,own,result);first=result['choice']
            steps.append((deepcopy(own),result))
            self.assertFalse(first['dead'])
            if first['chain']:break
            own.update(field=first['field'],remaining_frames=own['remaining_frames']-first['end_at']-12)
        final=steps[-1][1]['choice']
        self.assertGreaterEqual(final['chain'],9)
        self.assertGreater(len(steps),8)
        self.assertLessEqual(steps[-1][0]['remaining_frames']-final['fire_at'],40)
        self.assertGreater(steps[-1][0]['remaining_frames'],final['fire_at']+8)
        self.assertFalse(final['next_seed_input_fits'])

    def test_same_chain_extra_group_points_do_not_override_later_extension_fire(self):
        own=side('fever',seed3(),['2:RY']);own.update(normal_confirmed=1000,remaining_frames=100)
        allowed=[dict(x=2,r='L'),dict(x=3,r='L')]
        chosen=self.engine.seed_solver.solve(own,120,True,dict(strategy='extend'),allowed=allowed)
        higher_points=self.engine.seed_solver.solve(own,120,True,dict(strategy='quick'),allowed=allowed)
        self.assertEqual(chosen['choice']['chain'],higher_points['choice']['chain'])
        self.assertFalse(chosen['choice']['all_clear'])
        self.assertLess(chosen['choice']['total_points'],higher_points['choice']['total_points'])
        self.assertGreater(chosen['choice']['fire_at'],higher_points['choice']['fire_at'])
        self.assertEqual(next_seed(3,chosen['choice']['chain']),next_seed(3,higher_points['choice']['chain']))
        verify(self.engine.native,self.engine.scoring,own,chosen)

    def test_cached_strategy_rechecks_pressure_that_changes_turnover_capacity_class(self):
        own=side('fever',seed3(),['2:RY','2:BB','2:GY']);own.update(normal_confirmed=10)
        req=request(own);before=self.engine._signature(req,own)
        own['normal_confirmed']=1000
        self.assertNotEqual(before,self.engine._signature(req,own))
        own['normal_confirmed']=10;before=self.engine._signature(req,own)
        own.update(unconfirmed=1000,fever_unconfirmed=1000)
        self.assertNotEqual(before,self.engine._signature(req,own))


if __name__=='__main__':unittest.main()
