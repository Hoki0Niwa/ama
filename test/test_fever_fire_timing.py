"""Normal/Fever commitment, settlement and offensive delivery regressions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, request, seed3
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.worker import JsonProcess
from fever_battle import disruption


class FireTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = JsonProcess([NATIVE], cwd=ROOT)
        cls.cases = json.loads((ROOT/'data/fever/baselines/2026-10-11-normal-fire-timing-investigation.json').read_text(encoding='utf-8'))['cases']

    @classmethod
    def tearDownClass(cls):
        cls.native.close()

    def case(self, character, pending, at):
        return deepcopy(next(c['request'] for c in self.cases if
            (c['character'],c['pending'],c['event_at']) == (character,pending,at)))

    def test_unfinished_main_is_not_spent_for_a_gauge_that_stops_short(self):
        for character in ('arle','rafisol'):
            for pending,at in ((1,350),(20,700),(20,1000)):
                with self.subTest(character=character,pending=pending,at=at):
                    reply = self.native.ask(self.case(character,pending,at))
                    self.assertLess(reply['choice']['chain'],7)
                    mains = [c for c in reply['candidates'] if c['chain']>=7]
                    self.assertTrue(mains)
                    self.assertTrue(any(c['known_exchange_pending']>0 and c['main_links_lost']>0 for c in mains))

    def test_visible_follow_up_is_searched_after_main_clear(self):
        req=self.case('arle',20,700)
        reply=self.native.ask(req)
        self.assertGreater(reply['completed_depth'],1)
        self.assertTrue(any(c['chain']>=7 and c['known_exchange_pending']>0 for c in reply['candidates']))

    def test_current_packet_alone_does_not_make_a_weak_main_sufficient(self):
        req=self.case('arle',20,700)
        req['enemy_events']=[]
        reply=self.native.ask(req)
        self.assertLess(reply['choice']['chain'],7)
        mains=[c for c in reply['candidates'] if c['chain']>=7]
        self.assertTrue(any(c['known_exchange_pending']==0 and c['next_seed_exposure']>0
            and not c['defense_commitment'] for c in mains))

    def test_main_resource_weights_affect_a_losing_commitment(self):
        req=self.case('arle',1,350)
        req['allowed']=[dict(x=2,r='L')]
        values=[]
        for weight in (0,1000000):
            req['weights'].update(mainline=weight,uncountered=weight)
            values.append(self.native.ask(req)['choice']['value'])
        self.assertGreater(values[0],values[1])

    def test_mode_reply_uses_the_same_gauge_timeline_as_the_fire_decision(self):
        native_req=self.case('arle',20,350)
        own=side('normal',native_req['field'],native_req['queue'])
        own.update(character='arle',confirmed=20,normal_confirmed=20)
        engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        try:
            with patch.object(engine.solo,'ask',return_value=dict(x=5,r='U',fire=False)), \
                 patch.object(engine,'_enemy_events',return_value=native_req['enemy_events']), \
                 patch.object(engine,'_enemy_hold',return_value=550), \
                 patch.object(engine,'_enemy_fever',return_value=dict(enemy_fever=True,their_end=400,
                     enemy_seed_level=12,enemy_reply_nuisance=300)):
                reply=engine.answer(request(own,side('fever',seed3())))
            self.assertEqual(reply['gauge_forecast']['gauge_after'],7)
            self.assertEqual(reply['gauge_forecast']['offset_links'],7)
            self.assertEqual(reply['gauge_forecast']['model'],'causal_chain_timeline')
            self.assertTrue(reply['entry_pending_after_chain'])
        finally:
            engine.close()

    def test_sufficient_entry_and_only_executable_emergency_are_retained(self):
        req=self.case('arle',20,350)
        reply=self.native.ask(req)
        self.assertTrue(any(c['chain']>=7 and c['gauge_after']==7 and c['known_exchange_secured'] for c in reply['candidates']))
        req=self.case('arle',1,350)
        req['allowed']=[dict(x=2,r='L')]
        reply=self.native.ask(req)
        self.assertGreaterEqual(reply['choice']['chain'],7)
        self.assertFalse(reply['choice']['known_exchange_secured'])

    def test_late_current_attack_is_not_a_crushing_opportunity(self):
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows=list(next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7'))
        rows[4:7]=['Y.....']*3
        req=self.case('arle',0,350)
        req.update(field=rows,queue=['2:YG'],target_point=3,confirmed=0,
            allowed=[dict(x=0,r='U')],enemy_reply_nuisance=1000000,
            enemy_events=[dict(type='link',frame=10,points=3),dict(type='end',frame=40)],their_end=40)
        reply=self.native.ask(req)['choice']
        self.assertGreater(reply['attack_end'],66)
        self.assertEqual(reply['projected_disrupt'],0)
        req['their_end']=400
        req['enemy_events'][-1]['frame']=400
        reply=self.native.ask(req)['choice']
        self.assertGreater(reply['projected_disrupt'],1)
        self.assertTrue(reply['disruption_requires_timing'])

    def test_clear_reason_carries_a_transient_pressure_deadline(self):
        req=request(side('normal'),side('fever',seed3()))
        reply=dict(reason='tactics_clear',fire=True,tactics_forecast=dict(choice=dict(
            disruption_kind='overpower',disruption_requires_timing=True,attack_end=90)))
        guard=disruption.contract(req,reply,dict(their_end=100))
        self.assertEqual(guard['kind'],'current_attack')
        reply['disruption_timing']=guard
        self.assertTrue(disruption.valid(reply,req))
        later=deepcopy(req);later['frame']=37
        self.assertFalse(disruption.valid(reply,later))

    def test_a_future_shot_cannot_buy_an_ineffective_current_clear(self):
        req=self.case('arle',0,350)
        req.update(queue=['2:YG','2:GB','2:GB'],target_point=3,
            enemy_events=[dict(type='link',frame=10,points=3),dict(type='end',frame=150)],
            their_end=150,enemy_reply_nuisance=1000000)
        current=deepcopy(req);current['queue']=current['queue'][:1]
        one=self.native.ask(current)
        first={(c['x'],c['r']):c for c in one['candidates']}
        longer=self.native.ask(req)
        for c in longer['candidates']:
            if c['chain']:
                self.assertLessEqual(c['projected_disrupt'],first[c['x'],c['r']]['projected_disrupt'])
        # A nonclearing preparation is still allowed to lead to a useful shot.
        req.update(queue=['2:GB','2:YG'],allowed=[dict(x=0,r='U')])
        prep=self.native.ask(req)['choice']
        self.assertEqual(prep['chain'],0)
        self.assertGreater(prep['projected_disrupt'],0)

    def test_old_seed_geometry_does_not_prove_a_late_block(self):
        req=self.case('arle',0,350)
        req.update(queue=['2:YG'],target_point=3,allowed=[dict(x=0,r='U')],
            enemy_events=[],enemy_extending=True,enemy_reply_nuisance=1000000,
            enemy_seed_defense=[dict(checked=True,regular_after_drop=False,counter_points=0) for _ in range(31)])
        reply=self.native.ask(req)['choice']
        self.assertGreater(reply['attack_end'],26)
        self.assertEqual(reply['projected_disrupt'],0)


if __name__=='__main__':
    unittest.main()
