"""Protocol-3 request-local tactics, validation, cache guards and old-version moves."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'test'))
from fever_fixtures import NATIVE, SOLO, request, side, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply, preview_prepared
from fever_battle import tactical_options as options


class TacticalOptionsTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        self.addCleanup(self.engine.close)

    def test_omitted_options_match_pre_change_moves(self):
        fixture = json.loads((ROOT/'data/fever/golden/normal-tactics-defaults.json').read_text(encoding='utf-8'))
        for index, case in enumerate(fixture['cases']):
            with self.subTest(case=index):
                # A fresh engine reproduces the pre-change capture's cache/history conditions.
                engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
                try:
                    reply = engine.answer(case['request'])
                    self.assertEqual({k: reply.get(k) for k in case['expected']}, case['expected'])
                finally:
                    engine.close()

    def test_all_weights_and_switches_reach_worker_after_fever_and_do_not_leak(self):
        own=side('normal',seed_with_small_green(),['2:GY']);own['mode_generation']=2
        req=request(own,side())
        weights={key: bounds[1] for key,bounds in options.WEIGHTS.items()}
        req['normal_tactics']=dict(invite_fever=True,avoid_own_fever=True,harass=True,
            harass_min_count=0,harass_max_count=85,harass_min_height=0,harass_columns=6,weights=weights)
        original=copy.deepcopy(self.engine.policy)
        ask=self.engine.native.ask
        seen=[]
        def capture(value, **kwargs):
            if value['op']=='tactics':seen.append(copy.deepcopy(value))
            return ask(value, **kwargs)
        with patch.object(self.engine.native,'ask',side_effect=capture):
            reply=self.engine.answer(req)
        self.assertEqual(len(seen),1)
        for name in ('invite_fever','avoid_own_fever','harass'):self.assertTrue(seen[0][name])
        self.assertEqual({k:seen[0]['weights'][k] for k in weights},weights)
        self.assertEqual(reply['normal_tactics']['evaluated_switches'],dict(invite_fever=True,avoid_own_fever=True,harass=True))
        self.assertEqual(self.engine.policy,original)
        del req['normal_tactics']
        reply=self.engine.answer(req)
        self.assertFalse(reply['normal_tactics']['effective']['invite_fever'])
        self.assertEqual(reply['normal_tactics']['effective']['weights'],
            {k:original['normal_tactics']['weights'][k] for k in options.WEIGHTS})
        self.assertIsNone(reply['normal_tactics']['evaluated_switches'])

    def test_switches_can_be_disabled_in_opening_and_set_against_fever(self):
        own=side('normal',seed_with_small_green(),['2:GY'])
        own.update(confirmed=18,normal_confirmed=18)
        for enemy in (side(),side('fever')):
            for enabled in (False,True):
                req=request(own,enemy)
                req['normal_tactics']=dict(invite_fever=enabled,avoid_own_fever=enabled,harass=False)
                reply=self.engine.answer(req)
                self.assertEqual(reply['normal_tactics']['evaluated_switches'],
                    dict(invite_fever=enabled,avoid_own_fever=enabled,harass=False))
                self.assertEqual(reply['normal_tactics']['selected'],reply['reason'])

    def test_empty_options_and_wait_reply(self):
        req=request(side('normal'))
        before=self.engine.answer(req)
        req['normal_tactics']={}
        after=self.engine.answer(req)
        self.assertEqual((before['x'],before['r'],before['reason']),
                         (after['x'],after['r'],after['reason']))
        req['self']['gauge']=7
        reply=self.engine.answer(req)
        self.assertEqual(reply['action'],'wait')
        self.assertIsNone(reply['normal_tactics']['evaluated_switches'])

    def test_harass_boundaries_and_disable(self):
        own=side('normal',['......']*10+['RGBYRG']*4)
        enemy=side()
        cfg=options.resolve(self.engine.policy['normal_tactics'],{},own,enemy)
        active=lambda:options.harass_enabled(cfg,own,enemy,True,False,False,None)
        self.assertTrue(active()) # 24 cells, left three columns at height 4
        cfg['harass_max_count']=24;self.assertFalse(active())
        cfg['harass_max_count']=25;self.assertTrue(active())
        cfg['harass_min_count']=25;self.assertFalse(active())
        cfg['harass_min_count']=24;cfg['harass_min_height']=5;self.assertFalse(active())
        cfg['harass_min_height']=4;cfg['harass']=False;self.assertFalse(active())
        self.assertFalse(options.harass_enabled(cfg,own,enemy,True,True,True,None))
        cfg['harass']=True
        self.assertFalse(options.harass_enabled(cfg,own,side('fever'),True,False,False,{}))

    def test_window_disable_and_partial_merge(self):
        req=request(side('normal'))
        req['normal_tactics']=dict(window_build=dict(enabled=False,hold=19,beam_width=1))
        cfg=options.resolve(self.engine.policy['normal_tactics'],req,req['self'],req['enemy'])['window_build']
        self.assertEqual(cfg,dict(enabled=False,hold=19,beam_width=1,min_pieces=3,fire_pieces=4))
        decision=type('Decision',(),dict(reply={'decision_kind':'stack'}))()
        with patch.object(self.engine,'_enemy_events',side_effect=AssertionError('disabled')):
            self.assertIsNone(self.engine._window_build(req,req['self'],req['enemy'],{},[],decision))
        req['normal_tactics']['window_build']['enabled']=True
        with patch.object(self.engine,'_enemy_events',return_value=[]) as events:
            self.engine._window_build(req,req['self'],req['enemy'],{},[],decision)
            events.assert_called_once()

    def test_invalid_requests_are_rejected_before_dispatch(self):
        invalid=[None,[],True,{'unknown':1},{'invite_fever':1},{'avoid_own_fever':None},{'harass':'true'},
                 {'harass_min_count':53},{'harass_max_count':23},{'window_build':False},
                 {'window_build':{'enabled':1}},{'weights':{'kill':1}}]
        for section,limits in ((None,options.LIMITS),('weights',options.WEIGHTS),('window_build',options.WINDOW)):
            for key,(low,high) in limits.items():
                for bad in (low-1,high+1,True,1.0,'1',None):
                    invalid.append({key:bad} if section is None else {section:{key:bad}})
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.engine.answer(dict(protocol_version=3,rule='fever_battle',op='ready',normal_tactics=value))

    def test_changed_controls_invalidate_preparation_and_authorization(self):
        req=request(side('normal'))
        self.engine.answer(req)
        before=self.engine._signature(req,req['self'])
        reply=self.engine.answer(req)
        newer=copy.deepcopy(req);newer['normal_tactics']=dict(harass=False)
        self.assertNotEqual(before,self.engine._signature(newer,newer['self']))
        with self.assertRaisesRegex(ValueError,'normal tactics changed'):
            authorize_mode_reply(req,reply,newer)
        state=dict(match_id=req['match_id'],execution_request=req,prepared=(None,0,reply))
        self.assertIsNone(preview_prepared(state,newer))


if __name__=='__main__':unittest.main()
