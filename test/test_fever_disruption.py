"""Fever jab quantity, firepower pressure and absolute delivery deadlines."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE,SOLO,side,request,seed3,seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine,authorize_mode_reply,identity
from fever_battle import tactics,disruption


class DisruptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        seeds=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        cls.rows=list(next(s['field'] for s in seeds['seeds'] if s['id']=='hirazumi-7'))
        cls.rows[4:7]=['Y.....']*3
    @classmethod
    def tearDownClass(cls):cls.engine.close()

    def setUp(self):
        self.engine.enemy_analysis = None

    def shot(self,rate=30,reply=1000,known=True,small=False,skip=False,quiet=False,baseline=0):
        own=side('normal',seed_with_small_green() if small else self.rows,['2:GY' if small else '2:YG'])
        own['character']='arle'
        enemy=side('fever',seed3());enemy['fever_confirmed']=enemy['confirmed']=baseline
        target=dict(enemy_fever=True,enemy_reply_nuisance=reply,enemy_skip_jab=skip)
        if known:target['their_end']=105
        return tactics.choose(self.engine.native,self.engine.scoring,own,rate,1,self.engine.policy['normal_tactics'],
            enemy=enemy,allowed=[dict(x=0,r='U')],defense=dict(hold=reply,kill=0,links=0,need=7),
            fever=target,quiet=quiet)

    def test_one_nuisance_is_weaker_than_two_rows(self):
        one=self.shot()['tactics_forecast']['choice']
        thirteen=self.shot(rate=3)['tactics_forecast']['choice']
        self.assertEqual((one['sent'],thirteen['sent']),(1,13))
        self.assertLess(one['projected_disrupt'],thirteen['projected_disrupt'])
        self.assertLess(one['value'],thirteen['value'])
        self.assertIsNone(self.shot(quiet=True))
        self.assertEqual(self.shot(rate=3,quiet=True)['reason'],'tactics_disrupt')

    def test_small_board_main_can_jab_without_discarding_a_large_build(self):
        choice=self.shot(rate=3,small=True)['tactics_forecast']['choice']
        self.assertEqual(choice['attack_kind'],'main')
        self.assertEqual(choice['disruption_kind'],'jab')
        self.assertEqual(self.shot(rate=3,small=True,quiet=True)['reason'],'tactics_disrupt')

    def test_overpower_does_not_need_a_turnover_target(self):
        choice=self.shot(rate=1,reply=6,known=False)['tactics_forecast']['choice']
        self.assertEqual(choice['disruption_kind'],'overpower')
        self.assertGreater(choice['projected_disrupt'],1)
        self.assertIsNotNone(self.shot(rate=1,reply=6,known=False,quiet=True))
        self.assertIsNone(self.shot(rate=3,known=False,quiet=True))

    def test_side_can_beat_current_attack_without_beating_next_seed(self):
        own=side('normal',self.rows,['2:YG']);own['character']='arle'
        result=tactics.choose(self.engine.native,self.engine.scoring,own,3,1,self.engine.policy['normal_tactics'],
            enemy=side('fever',seed3()),allowed=[dict(x=0,r='U')],
            enemy_events=[dict(type='link',frame=10,points=3),dict(type='end',frame=400)],
            defense=dict(hold=1000000,kill=0,links=0,need=7),
            fever=dict(enemy_fever=True,their_end=400,enemy_reply_nuisance=1000000))
        choice=result['tactics_forecast']['choice']
        self.assertLess(choice['attack_end'],400)
        self.assertEqual((choice['disruption_kind'],choice['sent']),('overpower',12))
        self.assertGreater(choice['projected_disrupt'],1)

    def test_final_big_piece_suppresses_only_jab(self):
        self.assertEqual(self.shot(rate=3,skip=True)['tactics_forecast']['choice']['projected_disrupt'],0)
        self.assertEqual(self.shot(rate=1,reply=6,known=False,skip=True)['tactics_forecast']['choice']['disruption_kind'],'overpower')

    def test_existing_persistent_pressure_does_not_buy_another_jab(self):
        choice=self.shot(rate=3,reply=10,baseline=100)['tactics_forecast']['choice']
        self.assertEqual(choice['projected_disrupt'],0)

    def test_seed_level_changes_reply_capacity_and_final_big_piece_exception(self):
        enemy=side('fever',seed3(),['0:Y','2:RY']);enemy.update(remaining_frames=1,fever_chain_end_frame=10,observed_frame=15)
        low=self.engine._calculate_enemy_fever(enemy,[],30)
        self.assertEqual((low['their_end'],low['disrupt_window']),(0,21))
        self.assertTrue(low['enemy_skip_jab'])
        enemy['seed_chain']=15
        high=self.engine._calculate_enemy_fever(enemy,[],30)
        self.assertGreater(high['enemy_reply_nuisance'],low['enemy_reply_nuisance'])
        enemy['queue'][0]='2:RY'
        self.assertFalse(self.engine._calculate_enemy_fever(enemy,[],30)['enemy_skip_jab'])

    def guard_reply(self,req,seed=False):
        choice=dict(disruption_kind='jab',projected_disrupt=1,attack_end=105,end_at=105)
        reply=dict(action='place',decision_identity=identity(req),fire=True,chain=1,reason='tactics_disrupt',
            **({'seed_forecast':dict(choice=choice)} if seed else {'tactics_forecast':dict(choice=choice)}))
        reply['disruption_timing']=disruption.contract(req,reply,dict(their_end=0,disrupt_window=122))
        return reply

    def test_prepared_deadline_does_not_slide_with_request_frame(self):
        req=request(side('normal'),side('fever',seed3()))
        reply=self.guard_reply(req)
        now=deepcopy(req);now['frame']=80
        self.assertFalse(self.engine._prepared_delivery_stable(now,now['self'],now['enemy'],reply))
        self.assertTrue(disruption.valid(reply,req))

    def test_early_and_seed_fire_use_the_same_deadline(self):
        req=request(side('normal'),side('fever',seed3()))
        now=deepcopy(req);now.update(frame=80,observation=dict(frame_before=80,frame_after=80,match_status='running'))
        now['self']['observed_frame']=now['enemy']['observed_frame']=80
        for seed in (False,True):
            with self.assertRaisesRegex(ValueError,'jab deadline'):
                authorize_mode_reply(req,self.guard_reply(req,seed),now)

    def test_changed_seed_rejects_jab_but_ordinary_steering_is_kept(self):
        req=request(side('normal'),side('fever',seed3()));now=deepcopy(req)
        now['enemy']['seed_id']+=1
        reply=self.guard_reply(req)
        self.assertFalse(disruption.valid(reply,now))
        reply.pop('disruption_timing')
        self.assertTrue(authorize_mode_reply(req,reply,now))

    def test_incidental_jab_does_not_expire_a_needed_offset_or_all_clear(self):
        req=request(side('normal'),side('fever',seed3()))
        for reason in ('tactics_offset','tactics_all_clear'):
            reply=self.guard_reply(req);reply.pop('disruption_timing');reply['reason']=reason
            self.assertIsNone(disruption.contract(req,reply,dict(their_end=0,disrupt_window=26)))
            latest=deepcopy(req);latest['enemy']['seed_id']+=1
            self.assertTrue(authorize_mode_reply(req,reply,latest))

    def test_real_prepare_reuses_valid_jab_and_rejects_expired_one_without_rebuilding(self):
        for elapsed,reuse in ((10,True),(80,False)):
            engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
            try:
                own=side('normal',self.rows,['2:YG','2:GB','2:GB']);own['character']='arle'
                enemy=side('fever',seed3());enemy.update(seed_chain=15,awaiting_seed=True,fever_entry_frame=0)
                req=request(own,enemy);req['target_point']=3
                with patch.object(engine.solo,'ask',return_value=dict(x=5,r='U')) as build:
                    prepared=engine.answer(dict(req,op='prepare_observed'))
                    self.assertTrue(prepared['prepared'])
                    deadline=engine.prepared[2]['disruption_timing']['deadline_frame']
                    now=deepcopy(req);now.update(frame=elapsed,observation=dict(frame_before=elapsed,frame_after=elapsed,match_status='running'))
                    now['self']['observed_frame']=now['enemy']['observed_frame']=elapsed
                    now['enemy']['remaining_frames']-=elapsed
                    reply=engine.answer(now)
                    self.assertEqual(reply.get('search_reused',False),reuse)
                    if reuse:
                        self.assertEqual(reply['disruption_timing']['deadline_frame'],deadline)
                    else:self.assertFalse(reply['fire'])
                    self.assertEqual(build.call_count,1)
            finally:engine.close()

    def test_builder_authorized_main_is_sent_but_weak_main_is_held_against_grown_seed(self):
        own=side('normal',self.rows,['2:YG']);own['character']='arle'
        moves=self.engine.native.ask(dict(op='placements',field=own['field'],piece=own['queue'][0]))['placements']
        fire=max(moves,key=lambda m:len(m['links']))
        self.assertGreaterEqual(len(fire['links']),7)
        for level in (3,15):
            enemy=side('fever',seed3());enemy.update(seed_chain=level,seed_id=level)
            with patch.object(self.engine.solo,'ask',return_value=dict(x=fire['x'],r=fire['r'],fire=True)):
                self.engine.normal_build_cache=None
                reply=self.engine.answer(request(own,enemy))
            if level==3:
                self.assertTrue(reply['fire'])
                self.assertEqual(reply['tactics_forecast']['choice']['disruption_kind'],'main_pressure')
            else:
                self.assertFalse(reply['fire'])
                self.assertEqual(reply['reason'],'tactics_hold_for_fever_counter')

    def test_predicted_extension_and_all_clear_change_next_seed_level(self):
        enemy=side('fever',seed3());own=side('normal')
        req=request(own,enemy)
        req['enemy_chain']=dict(mode_generation=enemy['mode_generation'],seed_id=enemy['seed_id'],
            trigger_field=seed3(),elapsed=0,scored_links=0)
        # A captured full prediction is kept once; progressing score links do
        # not require solving the board again to remember its next seed.
        prediction=dict(points=[40]*7,field=['......']*14,links=[dict(score_at=0)]*7)
        with patch.object(self.engine,'_prediction',return_value=prediction), \
             patch('fever_battle.mode_engine.enemy_events',return_value=[dict(type='end',frame=400)]):
            events=self.engine._enemy_events(req,enemy)
        self.assertEqual(self.engine._enemy_fever(enemy,events)['enemy_seed_level'],10)

    def test_seed_solver_uses_quantity_for_jab_reward_too(self):
        own=side('fever',seed3());enemy=side('fever',seed3())
        moves=self.engine.native.ask(dict(op='placements',field=own['field'],piece=own['queue'][0]))['placements']
        fire=max(moves,key=lambda m:len(m['links']))
        values=[]
        for rate in (120,30):
            result=self.engine.seed_solver.solve(own,rate,True,allowed=[dict(x=fire['x'],r=fire['r'])],enemy=enemy,
                fever=dict(enemy_fever=True,enemy_reply_nuisance=1000000,their_end=0,disrupt_window=10000))
            self.assertEqual(result['choice']['disruption_kind'],'jab')
            values.append(result['choice']['projected_disrupt'])
        self.assertLess(values[0],values[1])

    def test_fever_recovery_fire_also_carries_deadline(self):
        own=side('fever',seed3());enemy=side('fever',seed3())
        moves=self.engine.native.ask(dict(op='placements',field=own['field'],piece=own['queue'][0]))['placements']
        fire=max(moves,key=lambda m:len(m['links']))
        allowed=[dict(x=fire['x'],r=fire['r'])]
        result=self.engine.seed_solver.solve(own,30,True,allowed=allowed,enemy=enemy)
        req=request(own,enemy);req.update(op='recover_placement',reachable_placements=allowed,target_point=30)
        with patch.object(self.engine,'_enemy_events',return_value=[dict(type='end',frame=result['choice']['end_at'])]):
            reply=self.engine.answer(req)
        self.assertEqual(reply['disruption_timing']['kind'],'jab')
        latest=deepcopy(req);latest['frame']+=27
        self.assertFalse(disruption.valid(reply,latest))


if __name__=='__main__':unittest.main()
