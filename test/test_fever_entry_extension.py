"""Recorded window crash and extending a weak main until the last safe lock."""
from copy import deepcopy
import json
import sys
import unittest
from unittest.mock import patch
from fever_fixtures import ROOT, NATIVE, SOLO
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.worker import JsonProcess
from fever_battle.tactics import Decision
from fever_battle.gauge_wait import chain_identity, retime_cached
from fever_battle.chain_to_us import flights_to_us


class EntryExtensionTests(unittest.TestCase):
    def setUp(self):
        self.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')

    def tearDown(self):
        self.engine.close()

    def request(self):
        return json.loads((ROOT/'data/fever/golden/weak-entry-extension.json').read_text(encoding='utf-8'))['request']

    def test_recorded_early_window_fire_does_not_kill_the_protocol_process(self):
        req=json.loads((ROOT/'data/fever/golden/window-fire-crash.json').read_text(encoding='utf-8'))['request']
        with JsonProcess([sys.executable,'-m','fever_battle.mode_engine','--native',NATIVE,
                          '--solo',SOLO,'--config',ROOT/'config.json'],cwd=ROOT) as worker:
            for _ in range(2):
                reply=worker.ask(req)
                self.assertTrue(reply['prepared'])
                self.assertEqual(reply['plan']['reason'],'normal_fire_in_window')
            self.assertTrue(worker.ask(dict(protocol_version=3,rule='fever_battle',op='ready'))['ready'])

    def test_recorded_weak_main_builds_instead_of_waiting_for_entry(self):
        req=self.request()
        reply=self.engine.answer(req)
        self.assertEqual(reply['reason'],'normal_extend_before_entry')
        self.assertFalse(reply['fire'])
        self.assertNotIn('hold_down_until_frame',reply)
        self.assertLess(reply['entry_extension']['check_in'],reply['entry_extension']['chain_end_in'])

    def test_extension_uses_the_completed_beam_until_the_last_safe_check(self):
        req=self.request();reply=self.engine.answer(req)
        check=reply['entry_extension']['check_in']
        decision=Decision('defense',dict(decision_kind='offset',fire=True,chain=7,link_points=[120]*7))
        for end,extends in ((check+1,True),(check,False),(0,False)):
            events=[dict(type='link',frame=0,nuisance=1000,points=120000),dict(type='end',frame=end)]
            with patch.object(self.engine,'_enemy_events',return_value=events), \
                 patch.object(self.engine.solo,'ask',side_effect=AssertionError('reuse the full beam')):
                selected=self.engine._window_build(req,req['self'],req['enemy'],self.engine.last_normal_options,
                                                    self.engine.normal_placements,decision)
            self.assertEqual(selected is not None,extends,end)

    def test_sufficient_return_or_margin_does_not_force_extension(self):
        req=self.request();self.engine.answer(req)
        for margin in (False,True):
            q=deepcopy(req)
            if margin:q['margin_policy']=dict(start_frame=q['frame'],initial_target_point=160)
            points=[120]*7 if margin else [120000]
            decision=Decision('defense',dict(decision_kind='offset',fire=True,chain=len(points),link_points=points))
            selected=self.engine._window_build(q,q['self'],q['enemy'],self.engine.last_normal_options,
                                               self.engine.normal_placements,decision)
            self.assertIsNone(selected)

    def test_cached_weak_wait_is_removed_without_ipc_or_retargeting(self):
        req=self.request()
        self.engine.answer(req)
        placed=next(p for p in self.engine.normal_placements if (p['x'],p['r'])==(0,'D'))
        points=self.engine.scoring.chain(req['self']['character'],placed['links'])
        events=self.engine._enemy_events(req,req['enemy'])
        flights=flights_to_us(events,req['enemy'],req['target_point'])
        reply=dict(x=0,r='D',fire=True,link_points=points,hold_frames=90,
            hold_down_until_frame=req['frame']+90,gauge_wait=dict(kind='gauge_wait'),
            offset_timing=dict(placement=placed,config=self.engine.policy['normal_build']['gauge_wait'],
                pace=None,rate=req['target_point'],chain=chain_identity(req),
                flights=[[req['frame']+f,a] for f,a in flights]))
        with patch.object(self.engine.native,'ask',side_effect=AssertionError('no IPC')):
            updated=retime_cached(reply,req)
        self.assertEqual((updated['x'],updated['r']),(0,'D'))
        self.assertNotIn('hold_down_until_frame',updated)
        self.assertEqual(updated['gauge_wait_status']['why'],'extend_before_entry')


if __name__=='__main__':unittest.main()
