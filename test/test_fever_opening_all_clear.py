"""Shared opening all-clears, strategy preference and preparation reuse."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from fever_fixtures import ROOT,NATIVE,SOLO,side,request
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import strategy,tactical_options


class OpeningAllClearTests(unittest.TestCase):
    def setUp(self):
        self.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')

    def tearDown(self):self.engine.close()

    def req(self,name,row='RRRBBB',queue=None):
        own=side('normal',['......']*13+[row],queue or ['2:RB','2:RY','2:GY'])
        own['character']='arle'
        q=request(own);q['normal_tactics']=dict(strategy=name)
        return q

    def test_immediate_all_clear_is_shared_and_needs_no_construction_beam(self):
        values={}
        for name in strategy.NAMES:
            with self.subTest(strategy=name),patch.object(self.engine.solo,'ask',side_effect=AssertionError('no beam')), \
                    patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as ask:
                reply=self.engine.answer(self.req(name))
            self.assertEqual(reply['reason'],'tactics_all_clear')
            self.assertTrue(reply['next_all_clear'])
            forecast=reply['tactics_forecast']
            self.assertEqual(forecast['completed_depth'],1)
            self.assertLessEqual(forecast['expanded'],24)
            calls=[c.args[0] for c in ask.call_args_list if c.args[0].get('op')=='tactics']
            self.assertEqual(len(calls),1)
            self.assertEqual(len(calls[0]['queue']),1)
            values[name]=forecast['choice']['value']
        self.assertGreater(values['brawl'],values['hybrid'])
        self.assertGreater(values['hybrid'],values['mainline'])

    def test_next2_setup_and_actual_clear_are_shared_and_cached_at_spawn(self):
        for name in strategy.NAMES:
            req=self.req(name,'RRBBYY',['2:RR','2:BB','2:YY'])
            cleared=False
            for step in range(3):
                self.assertTrue(self.engine.answer(dict(req,op='prepare_observed'))['prepared'])
                with patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as ask:
                    reply=self.engine.answer(req)
                self.assertTrue(reply['search_reused'])
                self.assertFalse(any(c.args[0].get('op') in ('solo','tactics') for c in ask.call_args_list))
                self.assertEqual(reply['reason'],'tactics_all_clear')
                actual=self.engine.native.ask(dict(op='transition',field=req['self']['field'],
                    piece=req['self']['queue'][0],x=reply['x'],r=reply['r']))
                if actual['all_clear']:
                    cleared=True;break
                req['self'].update(field=actual['field'],queue=req['self']['queue'][1:],
                    piece_id=step+1,dropset_index=step+1,normal_chain_max=len(actual['links']))
            self.assertTrue(cleared,name)

    def test_color_screen_keeps_flexible_big_puyos_and_late_visible_completion(self):
        own=self.req('brawl')['self']
        own.update(field=['......']*13+['RRR...'],queue=['0:B'])
        self.assertTrue(strategy.opening_all_clear_possible(own))
        own.update(field=['......']*13+['RRRBBB'],queue=['0:Y'])
        self.assertFalse(strategy.opening_all_clear_possible(own))
        own.update(field=['......']*13+['RRBBYY'],queue=['2:RR','2:BB','2:YY'])
        self.assertTrue(strategy.opening_all_clear_possible(own))
        own['piece_id']=6
        self.assertFalse(strategy.opening_all_clear_possible(own))

    def test_common_search_does_not_run_when_the_visible_colors_cannot_clear(self):
        for name in ('brawl','hybrid'):
            req=self.req(name,'......',['2:RY','2:BB','L:RRY'])
            req['self']['character']='raffina'
            with patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as ask:
                self.engine.answer(req)
            self.assertFalse(any(c.args[0].get('op')=='tactics' for c in ask.call_args_list))

    def test_opening_limits_and_explicit_all_clear_weight_are_respected(self):
        for changes in (dict(piece_id=8),dict(mode_generation=1),dict(normal_chain_max=4)):
            own=deepcopy(self.req('brawl')['self']);own.update(changes)
            self.assertFalse(strategy.opening_all_clear_possible(own))
        req=self.req('brawl');req['normal_tactics']['weights']=dict(all_clear=0)
        cfg=tactical_options.resolve(self.engine.policy['normal_tactics'],req,req['self'],req['enemy'])
        self.assertFalse(cfg['opening_all_clear'])
        self.assertEqual(cfg['weights']['all_clear'],0)

if __name__=='__main__':unittest.main()
