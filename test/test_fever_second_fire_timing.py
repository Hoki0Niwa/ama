"""Second-main preservation, actual first-shot cost and unknown nuisance columns."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import tactics


class SecondFireTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.probes = json.loads((ROOT/'data/fever/baselines/2026-10-11-second-fire-timing-investigation.json').read_text(encoding='utf-8'))['probes']

    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def sample(self, ai=1, pair=61):
        return deepcopy(next(p for p in self.probes if p['ai'] == ai and p['pair'] == pair))

    def dispatch(self, phase, chain=True, events=None, gain=1):
        sample = self.sample(); own, enemy = sample['own'], sample['enemy']
        own['garbage_phase'] = phase
        enemy.update(mode_generation=1, seed_id=1)
        req = dict(second_target_chain=14, enemy=enemy, gauge_gain_on_offset=gain,
            solo_options=dict(beam_width=150, beam_depth=8),
            enemy_chain=dict(mode_generation=1, seed_id=1) if chain else None)
        with patch.object(self.engine, '_enemy_events', return_value=events or [dict(type='end',frame=0)]), \
             patch.object(self.engine, '_enemy_fever', return_value=dict(enemy_fever=True,their_end=0,enemy_reply_nuisance=428)), \
             patch.object(self.engine, '_enemy_defense', return_value=dict(hold=428,kill=0,links=0,need=7)), \
             patch.object(self.engine, '_enemy_hold', return_value=486):
            return self.engine._normal(req, own, enemy, 120)

    def test_chain_end_metadata_does_not_fire_main_when_columns_unknown(self):
        for phase, chain in ((None,True),(0,True),(None,False)):
            reply = self.dispatch(phase, chain)
            self.assertEqual(reply['chain'],0)
            self.assertEqual(reply['normal_decision_status'],'build')
            self.assertGreater(sum(c!='.' for row in reply['next_field'] for c in row),46)

    def test_future_threat_keeps_the_same_policy_for_unknown_columns(self):
        events=[dict(type='link',frame=650,points=62400),dict(type='end',frame=672)]
        replies=[self.dispatch(phase,events=events) for phase in (None,0)]
        for reply in replies:
            self.assertEqual(reply['chain'],0)
            self.assertEqual(reply['normal_decision_status'],'unresolved')
            choice=reply['tactics_forecast']['choice']
            self.assertFalse(choice['defense_commitment'])
            self.assertTrue(choice['current_survives'])
        self.assertEqual([(r['x'],r['r']) for r in replies],[(replies[0]['x'],replies[0]['r'])]*2)

    def test_no_gauge_gain_does_not_make_end_metadata_a_threat(self):
        reply=self.dispatch(None,gain=0)
        self.assertEqual(reply['chain'],0)
        self.assertEqual(reply['normal_decision_status'],'build')

    def forecast(self, pair=61, ai=1, events=None, allowed=None, queue=None, uncountered=None):
        sample=self.sample(ai,pair); own=sample['own']
        if queue is not None: own['queue']=queue
        policy=deepcopy(self.engine.policy['normal_tactics']); policy['budget_ms']=0
        if uncountered is not None: policy['weights']['uncountered']=uncountered
        result=tactics.evaluate(self.engine.native,self.engine.scoring,own,120,1,policy,
            enemy=sample['enemy'],enemy_events=events or [dict(type='link',frame=0,points=62400),dict(type='end',frame=0)],
            allowed=allowed, builder=(sample['build']['x'],sample['build']['r']),builder_fire=False,
            fever=dict(enemy_fever=True,their_end=0,enemy_reply_nuisance=428),enemy_hold=486)
        return result

    def test_later_entry_cannot_erase_first_shot_resource_cost(self):
        events=[dict(type='link',frame=120,points=62400),dict(type='end',frame=700)]
        decision=self.forecast(events=events,allowed=[dict(x=2,r='L')])
        choice=decision.forecast['choice']
        self.assertEqual(choice['chain'],8)
        self.assertEqual(choice['gauge_after'],6)
        self.assertEqual(choice['projected_gauge'],7)
        self.assertFalse(choice['current_defense_commitment'])
        self.assertGreater(choice['current_main_cost'],0)
        one=self.forecast(events=events,allowed=[dict(x=2,r='L')],queue=[self.sample()['own']['queue'][0]])
        # The initial resource charge is the same with or without NEXT information.
        self.assertEqual(choice['current_main_cost'],one.forecast['choice']['current_main_cost'])
        free=self.forecast(events=events,allowed=[dict(x=2,r='L')],uncountered=0)
        self.assertEqual(free.forecast['choice']['projected_gauge'],7)
        # Both plans enter later, but that entry must not waive the first shot's risk.
        self.assertGreaterEqual(free.forecast['choice']['value']-choice['value'],
            choice['main_links_lost']*self.engine.policy['normal_tactics']['weights']['uncountered'])

    def test_actual_seven_link_entry_remains_available(self):
        decision=self.forecast(pair=58,ai=2)
        choice=decision.forecast['choice']
        self.assertEqual(choice['chain'],7)
        self.assertEqual(choice['gauge_after'],7)
        self.assertTrue(choice['current_defense_commitment'])
        self.assertEqual(decision.status,'defense')

    def test_unknown_drop_is_checked_on_every_column_and_not_searched_past(self):
        sample=self.sample(); own=sample['own']; own.update(confirmed=2,unconfirmed=0)
        result=tactics.evaluate(self.engine.native,self.engine.scoring,own,120,1,
            self.engine.policy['normal_tactics'],enemy=sample['enemy'])
        take=[c for c in result.forecast['candidates'] if c['dropped']==2]
        self.assertTrue(take)
        self.assertTrue(all(c['possible_drop_boards']==15 and not c['post_drop_field_known'] for c in take))

    def test_second_target_default_matches_construction_and_firing(self):
        own=self.sample()['own']
        for extra, expected in (({},14),({'second_target_chain':None},19),({'second_target_chain':14},14)):
            req=dict(enemy={'mode':'normal'},gauge_gain_on_offset=1,**extra)
            options=self.engine._normal_options(req,own)
            self.assertEqual((options['build_chain'],options['trigger']),(expected,expected))


if __name__=='__main__': unittest.main()
