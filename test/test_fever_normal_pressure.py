"""Normal pressure/finish: Fever counters, resource gates and opt-in compatibility."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, request, side, seed3, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.worker import JsonProcess
from fever_battle.model import Scoring
from fever_battle.timing import ChainTiming
from fever_battle.normal_pressure_options import resolve, BOUNDS
from fever_battle import tactics
from test_fever_clear_burial import BOARD as HELD_MAIN

EMPTY=['......']*14
# High garbage board, no ready color clear; normal drops kill both death columns.
HIGH=['......']*4+['######']*10
RESOURCE=['......']*10+['RGBYRG','BYRGBY']*2

class PressureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        cls.native=cls.engine.native
        cls.scoring=Scoring()
    @classmethod
    def tearDownClass(cls):cls.engine.close()

    def probe(self, rows=None, queue=None, **enemy_changes):
        cfg=resolve({})
        cfg['pressure'].update(enabled=True,min_remaining=0,min_heights=[0]*6,third_column_height=0)
        enemy=dict(available=True,field=rows or EMPTY,queue=queue or ['2:RY','2:GB','2:YB'],
            powers=self.scoring.data['characters']['raffina']['normal'],gauge=0,gain=1,
            remainder=0,pending=0,experienced=False,seed_chain=3,
            third_height=sum(r[2]!='.' for r in (rows or EMPTY)))
        enemy.update(enemy_changes)
        return dict(op='normal_pressure_probe',field=RESOURCE,normal_pressure=cfg,
            normal_pressure_enemy=enemy,target_point=120,bonuses=self.scoring.data['bonuses'],
            timing=ChainTiming().native(),chain=1,redundancy=0,sent=6,deadline=84,invite_fever=True)

    def test_scores_match_fever_character_powers_rate_and_remainder(self):
        rows=seed3()
        for character in ('raffina','arle'):
            req=self.probe(rows,['2:RY','2:GB','2:YB'])
            req['normal_pressure_enemy']['powers']=self.scoring.data['characters'][character]['normal']
            req['normal_pressure']['counter_read']['depth']=1
            req['normal_pressure_enemy']['remainder']=39
            req['deadline']=10000
            # Independent first-piece scoring through the protocol's public placement results.
            moves=self.native.ask(dict(op='placements',field=rows,piece='2:RY'))['placements']
            for rate in (70,120,240):
                req['target_point']=rate
                expected=0
                for move in moves:
                    if move['dead']:continue
                    rest=39;total=0;pending=6
                    for point in self.scoring.chain(character,move['links'],'normal'):
                        amount,rest=divmod(rest+point,rate)
                        if pending and amount==0:amount=1
                        pending-=min(pending,amount);total+=amount
                    expected=max(expected,total)
                self.assertEqual(self.native.ask(req)['counter']['defence_1'],expected,(character,rate))

    def test_special_shape_counters_use_actual_fever_placements(self):
        for piece in ('L:RRG','J:RGR','4:RRGG','0:R'):
            req=self.probe(seed3(),[piece]);req['deadline']=10000
            req['normal_pressure']['counter_read']['depth']=1
            expected=0
            moves=self.native.ask(dict(op='placements',field=seed3(),piece=piece))['placements']
            for move in moves:
                if move['dead']:continue
                pending=6;rest=0;total=0
                for point in self.scoring.chain('raffina',move['links'],'normal'):
                    amount,rest=divmod(rest+point,120)
                    if pending and amount==0:amount=1
                    pending-=min(pending,amount);total+=amount
                expected=max(expected,total)
            self.assertEqual(self.native.ask(req)['counter']['defence_1'],expected,piece)

    def test_forcing_a_counter_consumes_normal_resources_and_large_seed_guard_is_tunable(self):
        req=self.probe(seed3());req['deadline']=10000
        req['normal_pressure']['counter_read']['depth']=1
        result=self.native.ask(req)
        self.assertTrue(result['pressure'])
        self.assertEqual(result['kind'],'force_counter')
        self.assertGreater(result['counter']['counter_cost_cells'],0)
        req['normal_pressure_enemy'].update(experienced=True,seed_chain=8)
        self.assertEqual(self.native.ask(req).get('blocked'),'large_seed_gauge_only')
        req['normal_pressure']['pressure']['block_seed_chain']=9
        self.assertTrue(self.native.ask(req)['pressure'])

    def test_link_scoring_deadline_and_enemy_rate_schedule(self):
        req=self.probe(['......']*13+['RRR...'],['2:RY'])
        req['deadline']=28
        before=self.native.ask(req)['counter']
        req['deadline']=29
        after=self.native.ask(req)['counter']
        self.assertEqual(before['defence_1'],0)
        self.assertGreater(after['defence_1'],0)
        req['enemy_rate_events']=[dict(frame=29,target_point=1)]
        self.assertGreater(self.native.ask(req)['counter']['defence_1'],after['defence_1'])

    def test_large_seed_gauge_only_is_blocked_but_real_landing_is_allowed(self):
        req=self.probe(['......']*13+['RRR...'],gauge=6,experienced=True,seed_chain=8)
        req['normal_pressure']['counter_read']['depth']=2
        req['deadline']=0;req['sent']=1
        req['normal_pressure']['pressure']['min_send']=1
        result=self.native.ask(req)
        self.assertEqual(result.get('blocked'),'large_seed_gauge_only')
        req=self.probe(HIGH,experienced=True,seed_chain=8)
        req['deadline']=0;req['sent']=6
        result=self.native.ask(req)
        self.assertTrue(result['counter']['complete'])
        self.assertTrue(result['pressure'])
        self.assertEqual(result['kind'],'bury')

    def test_resource_count_heights_redundancy_chain_and_send_bounds(self):
        req=self.probe(HIGH);req['deadline']=0
        self.assertTrue(self.native.ask(req)['pressure'])
        for key,value in (('min_remaining',25),('min_heights',[5,0,0,0,0,0]),
                          ('min_send',7),('max_send',5),('max_chain',1),('max_redundancy',0)):
            changed=copy.deepcopy(req);changed['normal_pressure']['pressure'][key]=value
            if key=='max_chain':changed['chain']=2
            if key=='max_redundancy':changed['redundancy']=1
            self.assertFalse(self.native.ask(changed)['pressure'],key)

    def test_finish_only_without_gauge_escape_and_all_drop_columns_dead(self):
        req=self.probe(HIGH);req['deadline']=0;req['sent']=18
        req['normal_pressure']['pressure']['enabled']=False
        req['normal_pressure']['finish']['enabled']=True
        self.assertTrue(self.native.ask(req)['finish'])
        req['normal_pressure_enemy']['gauge']=7
        self.assertFalse(self.native.ask(req)['finish'])
        req['normal_pressure_enemy']['gauge']=6
        # No legal counter exists: gauge 6 by itself is not an escape.
        self.assertTrue(self.native.ask(req)['finish'])
        req['normal_pressure_enemy'].update(field=EMPTY,third_height=0)
        self.assertFalse(self.native.ask(req)['finish'])

    def test_counter_after_arrival_can_fill_gauge_and_prevents_finish(self):
        rows=list(HIGH);rows[4]='RRR###'
        req=self.probe(rows,['2:RY','2:GB','2:YB'],gauge=6)
        req['normal_pressure']['finish']['enabled']=True
        req['deadline']=0;req['sent']=18
        result=self.native.ask(req)
        self.assertTrue(result['counter']['entry_possible'])
        self.assertFalse(result['finish'])
        req['normal_pressure_enemy']['gain']=0
        self.assertFalse(self.native.ask(req)['counter']['entry_possible'])

    def test_cutoff_and_unseen_future_never_prove_finish(self):
        req=self.probe(HIGH);req['normal_pressure']['finish']['enabled']=True
        req['deadline']=0;req['sent']=18
        req['normal_pressure']['counter_read']['max_nodes']=1
        result=self.native.ask(req)
        self.assertFalse(result['counter']['complete']);self.assertFalse(result['finish'])
        req=self.probe(queue=['2:RY'])
        req['normal_pressure']['finish']['enabled']=True;req['deadline']=200
        self.assertFalse(self.native.ask(req)['counter']['complete'])
        req['normal_pressure_enemy']['available']=False
        self.assertEqual(self.native.ask(req)['blocked'],'enemy_unavailable')

    def test_tactics_and_protocol_select_pressure_and_finish(self):
        own=side('normal',EMPTY[:-1]+['RRR...'],['2:RR'])
        enemy=side('normal',HIGH,['2:RY','2:GB','2:YB']);enemy['character']='arle'
        req=request(own,enemy);req['target_point']=1
        req['normal_tactics']=dict(harass=False,pressure=dict(enabled=True,min_remaining=0,
            min_heights=[0]*6,third_column_height=0,min_send=1,max_send=1000000,weight=1000000),
            counter_read=dict(depth=3,max_nodes=20000))
        reply=self.engine.answer(req)
        self.assertEqual(reply['reason'],'tactics_pressure')
        self.assertTrue(reply['normal_tactics']['normal_attack']['pressure'])
        req['normal_tactics']['pressure']['enabled']=False
        req['normal_tactics']['finish']=dict(enabled=True,min_send=1,weight=1000000)
        reply=self.engine.answer(req)
        self.assertEqual(reply['reason'],'tactics_finish')
        req['gauge_gain_on_offset']=0
        self.assertEqual(self.engine.answer(req)['reason'],'tactics_finish')
        req['enemy']['gauge']=7
        reply=self.engine.answer(req)
        self.assertNotEqual(reply['reason'],'tactics_finish')

    def test_omitted_options_match_previous_version(self):
        for name in ('normal-pressure-defaults.json','normal-pressure-flex-defaults.json'):
            data=json.loads((ROOT/'data/fever/golden'/name).read_text(encoding='utf-8'))
            for case in data['cases']:
                engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
                try:
                    reply=engine.answer(case['request'])
                    self.assertEqual({k:reply.get(k) for k in case['expected']},case['expected'])
                finally:engine.close()

    def test_conservative_and_forceful_main_budget_pending_and_repetition(self):
        req=self.probe(HIGH);req.update(deadline=0,main_loss=3,attacks=2,consumed=16,quiet=False)
        cfg=req['normal_pressure']['pressure']
        cfg.update(max_main_loss=0,max_attacks=1)
        result=self.native.ask(req)
        self.assertEqual(result['blocked_conditions'],['pending','max_main_loss','max_attacks'])
        cfg.update(allow_pending=True,max_main_loss=3,max_attacks=3,attacks_used=1)
        result=self.native.ask(req)
        self.assertTrue(result['pressure'])
        self.assertEqual((result['main_loss_links'],result['consumed_cells'],result['attacks']),(3,16,2))
        cfg['attacks_used']=2
        self.assertEqual(self.native.ask(req)['blocked'],'max_attacks')
        cfg['max_attacks']=0
        self.assertTrue(self.native.ask(req)['pressure'])

    def test_each_resource_failure_is_reported(self):
        req=self.probe(HIGH);req.update(deadline=0,chain=3,redundancy=5,sent=6)
        req['normal_pressure']['pressure'].update(min_remaining=25,min_heights=[5]*6,
            max_chain=2,max_redundancy=4,min_send=7)
        self.assertEqual(self.native.ask(req)['blocked_conditions'],
            ['min_remaining','min_heights','max_redundancy','max_chain','min_send'])
        req['normal_pressure']['pressure'].update(min_send=1,max_send=5)
        self.assertIn('max_send',self.native.ask(req)['blocked_conditions'])

    def test_preempt_uses_witnessed_points_and_time_and_never_late_fire(self):
        req=self.probe(seed3());req.update(deadline=0,own_points=0,own_frame=10000)
        cfg=req['normal_pressure']['pressure']
        cfg.update(preempt=True,preempt_bonus=10,min_enemy_points=1,counter_cost_weight=0,gauge_weight=0)
        result=self.native.ask(req)
        self.assertEqual(result['kind'],'preempt')
        race=result['race']
        self.assertGreater(race['enemy_points'],0)
        self.assertGreater(race['enemy_frame'],0)
        req['deadline']=race['enemy_frame']+1
        self.assertFalse(self.native.ask(req)['pressure'])
        req['deadline']=0;req['own_frame']=race['enemy_frame']
        self.assertFalse(self.native.ask(req)['pressure'])
        cfg['race_margin_frames']=1
        self.assertTrue(self.native.ask(req)['pressure'])
        cfg['min_enemy_points']=race['enemy_points']+1
        self.assertFalse(self.native.ask(req)['pressure'])

    def test_protocol_preempts_a_visible_main_with_own_growth_estimate(self):
        own=side('normal',EMPTY[:-1]+['RRR...'],['2:RR'])
        enemy=side('normal',seed3(),['2:RY','2:GB','2:YB'])
        own['character']=enemy['character']='arle'
        req=request(own,enemy);req['target_point']=1
        req['normal_tactics']=dict(pressure=dict(enabled=True,preempt=True,min_enemy_points=1,
            preempt_bonus=1000000,counter_cost_weight=0,gauge_weight=0,
            min_remaining=0,min_heights=[0]*6,min_send=1,max_send=1000000),
            counter_read=dict(depth=1,max_nodes=4000))
        reply=self.engine.answer(req)
        self.assertEqual(reply['reason'],'tactics_pressure')
        attack=reply['normal_tactics']['normal_attack']
        self.assertEqual(attack['kind'],'preempt')
        self.assertGreater(attack['race']['enemy_points'],attack['race']['own_points'])
        self.assertGreater(attack['race']['own_frame'],attack['race']['enemy_frame'])

    def test_independent_resource_gauge_and_surplus_objectives(self):
        req=self.probe(seed3());req['deadline']=10000
        cfg=req['normal_pressure']['pressure']
        cfg.update(counter_cost_weight=0,gauge_weight=0)
        self.assertFalse(self.native.ask(req)['pressure'])
        cfg['counter_cost_weight']=2
        self.assertTrue(self.native.ask(req)['pressure'])
        cfg.update(counter_cost_weight=0,gauge_gain_weight=10)
        result=self.native.ask(req)
        self.assertGreater(result['counter']['gauge_gain'],0)
        self.assertTrue(result['pressure'])
        req['invite_fever']=False
        self.assertFalse(self.native.ask(req)['pressure'])
        req=self.probe(HIGH);req['deadline']=0
        cfg=req['normal_pressure']['pressure']
        cfg.update(third_column_height=13,counter_cost_weight=0,gauge_weight=0,surplus_weight=2)
        self.assertEqual(self.native.ask(req)['kind'],'surplus')

    def test_forceful_objectives_cannot_bypass_large_seed_guard(self):
        req=self.probe(seed3(),experienced=True,seed_chain=8)
        req.update(deadline=0,own_frame=10000)
        req['normal_pressure']['pressure'].update(allow_pending=True,preempt=True,
            min_enemy_points=1,preempt_bonus=100,gauge_gain_weight=100,surplus_weight=100,
            max_main_loss=84,max_attacks=0)
        self.assertEqual(self.native.ask(req)['blocked'],'large_seed_gauge_only')

    def test_native_tactics_reports_actual_budget_and_pending_switch(self):
        own=side('normal',EMPTY[:-1]+['RRR...'],['2:RR','2:RY','2:GB'])
        own['character']='arle'
        own.update(confirmed=1,normal_confirmed=1)
        enemy=side('normal',HIGH,['2:RY','2:GB','2:YB'])
        enemy['character']='arle'
        req=request(own,enemy);req['target_point']=1
        req['normal_tactics']=dict(pressure=dict(enabled=True,min_remaining=0,min_heights=[0]*6,
            min_send=1,max_send=1000000,third_column_height=0,weight=1000000),
            counter_read=dict(max_nodes=20000))
        result=self.engine.answer(req)
        shots=[c for c in result['tactics_forecast']['candidates'] if c['sent']]
        self.assertTrue(shots)
        self.assertTrue(all('pending' in c['normal_attack']['blocked_conditions'] for c in shots))
        req['normal_tactics']['pressure'].update(allow_pending=True,max_main_loss=84,max_attacks=3,preempt=True)
        result=self.engine.answer(req)
        self.assertEqual(result['reason'],'tactics_pressure')
        attack=result['normal_tactics']['normal_attack']
        self.assertTrue(attack['pressure'])
        self.assertGreater(attack['consumed_cells'],0)
        self.assertGreater(attack['attacks'],0)
        self.assertIn('enemy',result['decision_dependencies'])

    def test_actual_held_main_loss_is_gated_before_offset_discounts(self):
        own=side('normal',HELD_MAIN.split('/'),['2:BG'])
        own['character']='ally'
        enemy=side('normal',HIGH,['2:RY','2:GB','2:YB'])
        policy={**self.engine.policy['normal_tactics'],**resolve({})}
        policy['pressure'].update(enabled=True,min_remaining=0,min_heights=[0]*6,
            min_send=1,max_send=1000000,max_chain=19,max_redundancy=84,
            max_main_loss=0,third_column_height=0)
        result=tactics.evaluate(self.native,self.scoring,own,1,1,policy,enemy=enemy,quiet=True).forecast
        losses=[c for c in result['candidates'] if c['sent'] and c['normal_attack']['main_loss_links']>0]
        self.assertTrue(losses)
        for c in losses:
            self.assertIn('max_main_loss',c['normal_attack']['blocked_conditions'])
        policy['pressure']['max_main_loss']=84
        strong=tactics.evaluate(self.native,self.scoring,own,1,1,policy,enemy=enemy,quiet=True).forecast
        allowed=[c for c in strong['candidates'] if c['sent'] and c['normal_attack']['main_loss_links']>0]
        self.assertTrue(allowed)
        self.assertTrue(all('max_main_loss' not in c['normal_attack'].get('blocked_conditions',[]) for c in allowed))

    def test_later_attack_does_not_fund_a_current_uncredited_clear(self):
        own=side('normal',EMPTY[:-1]+['RRR...'],['2:RR','2:RY','2:GB']);own['character']='arle'
        enemy=side('normal',HIGH,['2:RY','2:GB','2:YB']);enemy['character']='arle'
        req=request(own,enemy);req['target_point']=1
        req['normal_tactics']=dict(pressure=dict(enabled=True,min_remaining=0,min_heights=[0]*6,
            third_column_height=0,min_send=1,max_send=1000000,weight=1000000),
            counter_read=dict(depth=3,max_nodes=20000))
        reply=self.engine.answer(req)
        choices=reply['tactics_forecast']['candidates']
        self.assertTrue(any(c['chain'] for c in choices))
        for choice in choices:
            if choice['chain']:
                self.assertLessEqual(choice['projected_normal_attack'].get('score',0),
                                     choice['normal_attack'].get('score',0))

    def test_large_seed_entry_blocks_pressure_even_when_some_nuisance_would_remain(self):
        rows=list(HIGH);rows[4]='RRR###'
        req=self.probe(rows,['2:RY','2:GB','2:YB'],gauge=6,experienced=True,seed_chain=8)
        req['normal_pressure']['counter_read']['max_nodes']=100000
        req['sent']=18;req['deadline']=0
        result=self.native.ask(req)
        self.assertTrue(result['counter']['complete'])
        self.assertGreater(result['counter']['remaining'],0)
        self.assertTrue(result['counter']['entry_possible'])
        self.assertEqual(result.get('blocked'),'large_seed_gauge_only')
        self.assertFalse(result['pressure'])
        req['normal_pressure_enemy']['experienced']=False
        req['invite_fever']=False
        self.assertNotEqual(self.native.ask(req)['kind'],'bury')

    def test_new_input_validation(self):
        bad=[dict(pressure=True),dict(finish={'enabled':1}),dict(counter_read=None),
             dict(pressure={'min_heights':[0]*5}),dict(pressure={'min_heights':[False]*6}),
             dict(pressure={'min_send':31}),dict(pressure={'unknown':0})]
        for key in ('allow_pending','preempt'):
            bad += [dict(pressure={key:v}) for v in (0,1,None,'true',[])]
        for section,limits in BOUNDS.items():
            for key,(low,high) in limits.items():
                bad += [{section:{key:v}} for v in (low-1,high+1,True,1.5,None)]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.engine.answer(dict(protocol_version=3,rule='fever_battle',op='ready',normal_tactics=value))

if __name__=='__main__':unittest.main()
