"""Midgame follow-ups, unchanged main construction, and execution-time offset clocks."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from fever_fixtures import ROOT, NATIVE, SOLO, request, side
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.gauge_wait import GaugeWait, retime_cached


class LivePolicyTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    def tearDown(self):
        self.engine.close()

    def test_mainline_enables_single_pressure_at_the_actual_one_row_threshold(self):
        from fever_battle.strategy import margin_pressure, controls
        req=request(side())
        req['target_point']=7
        self.assertFalse(margin_pressure(req))
        req['target_point']=6
        self.assertTrue(margin_pressure(req))
        req['_preparing_strategy']=True
        policy=controls(req,req['self'],req['enemy'])
        self.assertTrue(policy['pressure']['enabled'])
        self.assertEqual(policy['pressure']['max_chain'],1)
        req['target_point']=7
        req['self']['remainder']=2
        self.assertTrue(margin_pressure(req))
        req['self']['remainder']=0
        req['self']['powers']={'normal':[2]*19}
        self.assertTrue(margin_pressure(req))

    def test_main_and_second_keep_identical_full_construction_options(self):
        for generation in (0,1):
            own = side(queue=['2:GY','2:RY','L:BBG'])
            own.update(mode_generation=generation, normal_chain_max=14 if generation else 0)
            req = request(own)
            req['solo_options'] = dict(beam_width=250,beam_depth=16)
            req['second_target_chain'] = 14
            expected = self.engine._normal_options(req,own)
            for selected in ('brawl','hybrid'):
                req['normal_tactics'] = dict(strategy=selected)
                self.assertEqual(self.engine._normal_options(req,own),expected)

    def test_ready_winning_main_is_not_replaced_by_resource_saving_entry(self):
        from fever_battle import tactics
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows=list(next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7'))
        rows[4:7]=['Y.....']*3
        own=side(rows=rows,queue=['2:YG'])
        own.update(character='arle',gauge=6,confirmed=1,normal_confirmed=1)
        for selected in ('brawl','hybrid'):
            policy=dict(self.engine.policy['normal_tactics'],strategy=selected)
            reply=tactics.choose(self.engine.native,self.engine.scoring,own,30,1,policy,
                enemy=side(),builder=(2,'U'),builder_fire=True)
            chosen=reply['tactics_forecast']['choice']
            self.assertEqual(chosen['chain'],7)
            self.assertTrue(chosen['projected_sufficient_return'])
            self.assertEqual(chosen['current_exchange_pending'],0)
            chosen['current_exchange_pending']=1
            self.assertIsNone(tactics.ready_main({'candidates':[chosen]},(2,'U'),True))

    def test_weak_midgame_does_not_spend_its_last_main(self):
        rows=['......']*10+['RGBYRG','BYRGBY']*2
        for y in (7,8,9):rows[y]='G....R'
        for selected in ('brawl','hybrid'):
            req=request(side(rows=rows,queue=['2:GY','2:RY','L:BBG']),side())
            req.update(target_point=6,normal_tactics=dict(strategy=selected))
            self.engine.answer(dict(req,op='prepare_observed'))
            reply=self.engine.answer(req)
            self.assertNotEqual(reply['reason'],'tactics_pressure')

    def test_continuous_volleys_keep_five_chain_and_reuse_prepared_search(self):
        fixture=json.loads((ROOT/'data/fever/golden/pressure-five-volley.json').read_text(encoding='utf-8'))
        for selected in ('brawl','hybrid'):
            own=side(rows=fixture['field'],queue=fixture['queue'])
            own.update(character='arle',pattern='2'*16)
            req=request(own,side())
            req.update(target_point=6,normal_tactics=dict(strategy=selected))
            shots=0
            for arrow in range(4):
                self.assertTrue(self.engine.answer(dict(req,op='prepare_observed'))['prepared'])
                with patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as native:
                    reply=self.engine.answer(req)
                self.assertFalse(any(c.args[0].get('op') in ('tactics','solo') for c in native.call_args_list))
                self.assertEqual(reply['reason'],'tactics_pressure')
                attack=reply['normal_tactics']['normal_attack']
                self.assertGreaterEqual(attack['remaining_main_chain'],5)
                if reply['chain']:
                    shots+=1
                    self.assertLessEqual(reply['chain'],attack['allowed_chain'])
                    self.assertGreaterEqual(reply['next_score']//6,6)
                own.update(field=reply['next_field'],queue=own['queue'][1:],piece_id=arrow+1,
                           dropset_index=arrow+1,moves_since_chain=0)
            self.assertGreaterEqual(shots,3)

    def test_recorded_overlarge_receives_use_available_counters(self):
        fixture=ROOT/'data/fever/golden/continuous-pressure-defense.json'
        for case in json.loads(fixture.read_text(encoding='utf-8'))['cases']:
            reply=self.engine.answer(case['request'])
            choice=reply['tactics_forecast']['choice']
            self.assertEqual(reply['chain'],case['expected_chain'],case['line'])
            self.assertEqual(choice['dropped'],case['expected_dropped'],case['line'])
            if case['expected_chain']:
                self.assertFalse(reply['tactics_forecast']['can_receive_attack'])
                self.assertTrue(choice['projected_sufficient_return'])

    def test_recorded_resource_exhausting_four_chain_is_no_longer_played(self):
        fixture=ROOT/'data/fever/golden/midgame-pressure-issued.json'
        req=json.loads(fixture.read_text(encoding='utf-8'))['request']
        for strategy in ('brawl','hybrid'):
            req['normal_tactics']=dict(strategy=strategy)
            self.engine.answer(dict(req,op='prepare_observed'))
            reply=self.engine.answer(req)
            self.assertNotEqual(reply['reason'],'tactics_pressure')
            self.assertFalse(reply['fire'])

    def test_recorded_late_entry_jab_does_not_hold_2p(self):
        cases=json.loads((ROOT/'data/fever/golden/live-strategy-regressions.json').read_text(encoding='utf-8'))['cases']
        req=next(c['request'] for c in cases if c['line']==564)
        self.engine.answer(dict(req,op='prepare_observed'))
        reply=self.engine.answer(req)
        self.assertIsNone(reply.get('hold_down_until_frame'))
        self.assertNotEqual(reply['reason'],'normal_entry_jab')

    def test_later_links_can_align_when_first_link_wait_exceeds_room(self):
        own=side(queue=['2:RY'])
        req=request(own)
        req.update(frame=1000,target_point=5,margin_policy=dict(start_frame=1000,initial_target_point=7))
        points=[40,450,680,920,1400,2840]
        placement=dict(x=2,r='U',dead=False,contact_height=4,links=[{}]*6,fall_distances=[1]*6)
        reply=dict(x=2,r='U',fire=True,link_points=points)
        cfg=self.engine.policy['normal_build']['gauge_wait']
        flights=[(372,844),(428,2016),(484,2216)]
        chosen=self.engine.gauge_wait.choose(req,own,req['enemy'],reply,cfg,5,flights,placements=[placement])
        self.assertIsNotNone(chosen)
        self.assertGreaterEqual(chosen['gauge_wait']['gauge_then']-chosen['gauge_wait']['gauge_now'],2)
        self.assertLessEqual(chosen['hold_frames'],chosen['gauge_wait']['room'])

    def test_pressure_suspends_for_notices_flights_and_opponent_main(self):
        from fever_battle.strategy import controls, pressure_context
        req=request(side(),side())
        req['normal_tactics']=dict(strategy='hybrid')
        for arrow in range(5):
            req['self']['moves_since_chain']=arrow
            cfg=controls(req,req['self'],req['enemy'])
            self.assertTrue(cfg['pressure']['enabled'])
            self.assertEqual(cfg['pressure']['max_attacks'],0)
        for who in ('self','enemy'):
            for key in ('confirmed','unconfirmed','normal_confirmed','normal_unconfirmed','fever_confirmed','fever_unconfirmed'):
                changed=deepcopy(req)
                changed[who][key]=1
                self.assertFalse(pressure_context(changed),(who,key))
        for change in ({'enemy_chain':{'chain':5}},
                       {'observation':{'in_flight':{'enemy':{'incoming_in_flight':1}}}}):
            changed=dict(req,**change)
            self.assertFalse(pressure_context(changed))
        for mode,phase,gauge in (('fever','controllable',7),('normal','chain',0),('normal','controllable',7)):
            changed=deepcopy(req)
            changed['enemy'].update(mode=mode,phase=phase,gauge=gauge)
            cfg=controls(changed,changed['self'],changed['enemy'])
            self.assertFalse(cfg['pressure']['enabled'])
            self.assertFalse(cfg['pressure']['fever_pressure'])
            self.assertEqual(cfg['weights']['disrupt'],0)
        self.assertTrue(pressure_context(req))

    def test_stronger_pressure_keeps_larger_reserves(self):
        from fever_battle.strategy import controls
        for strategy,reserve in (('brawl',12),('hybrid',16)):
            req=request(side(),side())
            req['normal_tactics']=dict(strategy=strategy)
            cfg=controls(req,req['self'],req['enemy'])
            self.assertEqual(cfg['pressure']['min_remaining'],reserve)
            self.assertEqual(cfg['pressure']['min_send'],12)
            self.assertEqual(cfg['pressure']['min_remaining_chain'],5)
            self.assertEqual(cfg['pressure']['chain_reserve_step'],8)
            req['target_point']=6
            self.assertEqual(controls(req,req['self'],req['enemy'])['pressure']['min_send'],6)

    def test_chain_identity_accepts_an_explicit_start_without_elapsed(self):
        from fever_battle.gauge_wait import chain_identity
        req=request(side())
        req.update(frame=100,enemy_chain=dict(start_frame=20))
        self.assertEqual(chain_identity(req)[-1],20)
        req['enemy_chain']=dict(elapsed=80)
        self.assertEqual(chain_identity(req)[-1],20)
        req['enemy_chain']=dict(mode_generation=0,seed_id=1)
        identity=chain_identity(req)
        req['frame']+=1
        self.assertNotEqual(chain_identity(req),identity)

    def test_cached_fire_retimes_without_any_native_request(self):
        own=side(queue=['2:RY'])
        req=request(own)
        req.update(frame=1000,target_point=5,margin_policy=dict(start_frame=1000,initial_target_point=7))
        points=[10]*4
        placement=dict(x=2,r='U',dead=False,contact_height=4,links=[{}]*4,fall_distances=[1]*4)
        reply=dict(x=2,r='U',fire=True,link_points=points)
        wait=self.engine.gauge_wait
        cfg=self.engine.policy['normal_build']['gauge_wait']
        wait.choose(req,own,req['enemy'],reply,cfg,5,[(160,8)],placements=[placement])
        with patch.object(self.engine.native,'ask',side_effect=AssertionError('must not use IPC')):
            updated=retime_cached(reply,req)
        self.assertEqual((updated['x'],updated['r']),(2,'U'))
        self.assertEqual(updated['gauge_wait_status']['why'],'wait')
        self.assertGreaterEqual(updated['gauge_wait_status']['gauge_then']-updated['gauge_wait_status']['gauge_now'],2)
        expired=deepcopy(req)
        expired['frame']+=1000
        without_attack=retime_cached(updated,expired)
        self.assertNotIn('hold_down_until_frame',without_attack)
        self.assertEqual(without_attack['gauge_forecast']['gauge_after'],0)

    def test_later_link_alignment_can_preserve_five_gauge_steps(self):
        own=side(queue=['2:RY'])
        req=request(own)
        req.update(frame=1000,target_point=5,margin_policy=dict(start_frame=1000,initial_target_point=7))
        placement=dict(x=2,r='U',dead=False,contact_height=0,links=[{}]*8,fall_distances=[1]*8)
        reply=dict(x=2,r='U',fire=True,link_points=[10]*8)
        chosen=self.engine.gauge_wait.choose(req,own,req['enemy'],reply,
            self.engine.policy['normal_build']['gauge_wait'],5,[(400,14)],placements=[placement])
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen['gauge_wait']['gauge_now'],2)
        self.assertEqual(chosen['gauge_wait']['gauge_then'],7)
        self.assertTrue(chosen['entry_pending_after_chain'])
        self.assertEqual(chosen['gauge_forecast']['gauge_after'],7)

    def test_observed_counters_are_refreshed_and_equal_flights_are_not_deduplicated(self):
        own=side(queue=['2:RY'])
        req=request(own)
        req.update(frame=1000,target_point=5,margin_policy=dict(start_frame=1000,initial_target_point=7))
        placement=dict(x=2,r='U',dead=False,contact_height=4,links=[{}]*4,fall_distances=[1]*4)
        reply=dict(x=2,r='U',fire=True,link_points=[10]*4)
        flight=dict(counter=True,amount=20,arrive_frame=1160)
        req['observation']['in_flight']=dict(enemy=dict(attacks_in_flight=[flight]))
        self.engine.gauge_wait.choose(req,own,req['enemy'],reply,
            self.engine.policy['normal_build']['gauge_wait'],5,[(160,20)],placements=[placement])
        # The same observed object now has less left; never add its old amount too.
        flight['amount']=10
        updated=retime_cached(reply,req)
        self.assertEqual(updated['gauge_wait_status']['remaining'],2)
        # Two distinct objects with equal times and amounts still contain eight puyos.
        flight['amount']=4
        req['observation']['in_flight']['enemy']['attacks_in_flight'].append(dict(flight))
        updated=retime_cached(reply,req)
        self.assertEqual(updated['gauge_wait_status']['gauge_then'],4)
        self.assertEqual(updated['gauge_wait_status']['remaining'],0)


if __name__=='__main__': unittest.main()
