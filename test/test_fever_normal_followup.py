"""Buried-opponent followups: lethal reserve, elapsed-time gauge gates and reuse."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, request, seed3
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.timing import ChainTiming
from fever_battle import disruption

HIGH = ['......']*4 + ['######']*10
FIRE = ['......']*13 + ['RRR...']


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        self.cfg = self.engine.policy['normal_build']['followup']

    def tearDown(self):
        self.engine.close()

    def probe(self, gauge=0, duration=84, field=None):
        timing = ChainTiming().native()
        timing['placement_frames'] = duration - 70
        timing['split_extra_frames'] = [0]*14
        powers = self.engine.scoring.data['characters']['raffina']['normal']
        return dict(op='normal_followup', field=FIRE, queue=['2:RR'], remainder=0,
            target_point=1, powers=powers, bonuses=self.engine.scoring.data['bonuses'],
            enemy=dict(field=field or HIGH, gauge=gauge, remainder=0, powers=powers),
            gain=1, timing=timing, options={k:v for k,v in self.cfg.items() if k!='enabled'})

    def test_elapsed_time_gates_same_one_chain_at_all_boundaries(self):
        for duration, limit in ((120,3),(121,2),(240,2),(241,1),(360,1),(361,0)):
            with self.subTest(duration=duration):
                result = self.engine.native.ask(self.probe(limit,duration))
                self.assertTrue(result['found'],result)
                self.assertEqual(result['chain'],1)
                self.assertEqual(result['attack_end'],duration)
                self.assertEqual(result['gauge_limit'],limit)
                self.assertFalse(self.engine.native.ask(self.probe(limit+1,duration))['found'])

    def test_requires_enough_to_fill_the_lowest_column(self):
        result = self.engine.native.ask(self.probe())
        self.assertTrue(result['found'],result)
        self.assertEqual(result['need'],12)
        query = self.probe()
        query['target_point'] = 120
        self.assertFalse(self.engine.native.ask(query)['found'])

    def test_existing_lethal_pending_stops_even_a_qualifying_single(self):
        for pending in (12,100):
            query=self.probe(3)
            query['enemy']['pending']=pending
            result=self.engine.native.ask(query)
            self.assertFalse(result['found'])
            self.assertTrue(result['lethal_pending'])
            self.assertEqual(result['blocked'],'already_lethal_pending')
        query=self.probe(3)
        query['enemy']['pending']=11
        self.assertTrue(self.engine.native.ask(query)['found'])

    def test_lethal_pending_returns_to_construction_without_single_spam(self):
        own=side('normal',FIRE[:-1]+['RRR..G'],['2:RR'])
        enemy=side('normal',HIGH)
        enemy.update(confirmed=12,normal_confirmed=12)
        req=request(own,enemy)
        req['target_point']=1
        for piece_id in (0,1,2,3):
            req['self']['piece_id']=piece_id
            req['enemy']['gauge']=0 if piece_id < 2 else 4
            req['gauge_gain_on_offset']=0 if piece_id == 3 else 1
            reply=self.engine.answer(req)
            self.assertEqual(reply['reason'],'normal_build_or_fire')
            self.assertFalse(reply['fire'])
            self.assertTrue(reply['followup_forecast']['lethal_pending'])

    def test_observed_pace_counts_towards_gauge_time(self):
        query=self.probe(3)
        query['pace_frames']=100
        self.assertFalse(self.engine.native.ask(query)['found'])
        query['enemy']['gauge']=2
        result=self.engine.native.ask(query)
        self.assertTrue(result['found'])
        self.assertEqual(result['attack_end'],142)

    def test_normal_rate_uses_a_lethal_chain_instead_of_a_weak_single(self):
        query=self.probe()
        query.update(field=seed3(), queue=['2:RY'], target_point=120)
        query['enemy']['field']=['......']*3+['######']*11
        result=self.engine.native.ask(query)
        self.assertTrue(result['found'])
        self.assertEqual(result['chain'],3)
        self.assertGreaterEqual(result['sent'],result['need'])

    def test_counts_usable_colors_above_garbage_not_all_colors(self):
        buried = HIGH[:-2] + ['RGBYRG','BYRGBY']
        result = self.engine.native.ask(self.probe(field=buried))
        self.assertEqual(result['enemy_usable'],0)
        exposed = ['......']*2 + ['RGBYRG','BYRGBY'] + HIGH[4:]
        result = self.engine.native.ask(self.probe(field=exposed))
        self.assertGreater(result['enemy_usable'],6)
        self.assertFalse(result['found'])

    def test_fastest_qualifying_line_and_known_queue(self):
        query = self.probe()
        query['queue'] = ['2:RR','2:GB','2:RY']
        result = self.engine.native.ask(query)
        self.assertTrue(result['found'])
        self.assertEqual(result['fire_moves'],1)
        field = query['field']
        for piece, move in zip(query['queue'],result['path']):
            step = self.engine.native.ask(dict(op='transition',field=field,piece=piece,x=move['x'],r=move['r']))
            self.assertFalse(step['dead'])
            self.assertEqual(step['field'],move['field'])
            field = step['field']

    def test_protocol_selects_followup_and_guard_rejects_changed_opponent(self):
        req = request(side('normal',FIRE[:-1]+['RRR..G'],['2:RR']),side('normal',HIGH))
        req['target_point'] = 1
        reply = self.engine.answer(req)
        self.assertEqual(reply['reason'],'normal_lethal_followup',reply)
        self.assertTrue(disruption.valid(reply,req))
        for change in ('gauge','field','chain','fever','pending'):
            latest = copy.deepcopy(req)
            if change=='gauge': latest['enemy']['gauge']=4
            elif change=='field': latest['enemy']['field']=FIRE
            elif change=='chain': latest['enemy_chain']=dict(elapsed=0)
            elif change=='pending': latest['enemy']['confirmed']=12
            else: latest['enemy']['mode']='fever'
            self.assertFalse(disruption.valid(reply,latest),change)

    def test_defensive_and_unreachable_replies_are_preserved(self):
        req = request(side('normal',FIRE,['2:RR']),side('normal',HIGH))
        helper = self.engine.normal_followup
        for reason in ('tactics_offset','tactics_finish','observed_reachable_recovery'):
            with patch.object(self.engine.native,'ask') as native:
                self.assertIsNone(helper.choose(req,req['self'],req['enemy'],dict(reason=reason),self.cfg,{}))
            native.assert_not_called()
        req['self']['unconfirmed']=1
        with patch.object(self.engine.native,'ask') as native:
            self.assertIsNone(helper.choose(req,req['self'],req['enemy'],dict(reason='normal_build_or_fire'),self.cfg,{}))
        native.assert_not_called()

    def test_fever_immediate_followup_has_its_own_geometry_forecast(self):
        req=request(side('fever',FIRE,['2:RR']),side('normal',HIGH))
        req['target_point']=1
        reply=self.engine.answer(req)
        self.assertEqual(reply['reason'],'normal_lethal_followup',reply)
        first=reply['seed_forecast']['choice']
        self.assertEqual((first['x'],first['r']),(reply['x'],reply['r']))
        self.assertEqual(first['field'],reply['next_field'])
        self.assertEqual(first['link_points'],reply['link_points'])


if __name__=='__main__':
    unittest.main()
