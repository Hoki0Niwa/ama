"""Opponent analysis changes only at entry, seed arrival, and firing."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, request, side, seed3
from fever_battle.mode_engine import ModeBattleEngine


class EventAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        self.addCleanup(self.engine.close)

    def observe(self, req):
        events = self.engine._enemy_events(req, req['enemy'])
        target = self.engine._enemy_fever(req['enemy'], events, req['target_point'], True)
        return events, target

    def test_seed_geometry_and_strategy_ignore_intermediate_moves_and_trays(self):
        req = request(side('normal'), side('fever', seed3(), ['2:RY','2:GG']))
        with patch.object(self.engine.seed_defenses, 'observe', return_value=([], {'expanded':42})) as analyze:
            _, first = self.observe(req)
            frozen = deepcopy(self.engine.enemy_analysis)
            for frame in range(1, 8):
                req['frame'] = req['enemy']['observed_frame'] = frame
                req['enemy']['queue'] = ['2:BY','2:YR']
                req['enemy']['field'][-1] = 'BBYRR.'
                req['enemy']['normal_unconfirmed'] = frame*10
                req['enemy']['remaining_frames'] -= 1
                _, now = self.observe(req)
                self.assertEqual(now['enemy_seed_geometry'], first['enemy_seed_geometry'])
                self.assertEqual(self.engine.enemy_analysis, frozen)
            self.assertEqual(analyze.call_count, 1)
            req['enemy']['seed_id'] += 1
            self.observe(req)
            self.assertEqual(analyze.call_count, 2)

    def test_chain_end_is_absolute_and_never_reanchored_by_later_links(self):
        enemy = side('fever', seed3(), ['2:RY','2:GG']); enemy['observed_frame'] = 100
        req = request(side('normal'), enemy); req['frame'] = 100
        req['enemy_chain'] = dict(mode_generation=1, seed_id=1, start_frame=90,
            trigger_field=seed3(), elapsed=10, scored_links=1,
            observed_link=1, observed_link_frame=95)
        prediction = dict(points=[40,160],field=['......']*14,
            links=[dict(score_at=0,points=40),dict(score_at=60,points=160)], end_frame=120)
        with patch.object(self.engine, '_prediction', return_value=prediction) as resolve:
            first, target = self.observe(req)
            end = self.engine.enemy_analysis['chain_end_frame']
            self.assertEqual(end,215)
            req['frame'] = req['enemy']['observed_frame'] = 160
            req['enemy_chain'].update(elapsed=70,observed_link_frame=155,observed_link=2,scored_links=2)
            remaining, updated = self.observe(req)
            self.assertEqual(resolve.call_count,1)
            self.assertEqual(remaining,[dict(type='end',frame=55)])
            self.assertEqual(updated['chain_end_frame'],end)
            self.assertEqual(updated['packet_confirm_frame'],end)
            self.assertEqual(updated['analysis_frame'],100)
            self.assertEqual(updated['their_end'],55)
            self.assertEqual(target['enemy_seed_level'],updated['enemy_seed_level'])
            req.pop('enemy_chain'); req['frame'] = req['enemy']['observed_frame'] = 180
            self.observe(req)
            self.assertEqual(self.engine.enemy_analysis['event'],'fire')
            self.assertEqual(self.engine.enemy_analysis['chain_end_frame'],end)
            req['enemy']['seed_id']=2
            self.observe(req)
            self.assertEqual(self.engine.enemy_analysis['event'],'seed')
            self.assertEqual(self.engine.enemy_analysis['events'],[])

    def test_entry_and_seed_are_separate_analysis_events(self):
        enemy=side('normal'); enemy.update(gauge=7,awaiting_seed=True)
        req=request(side('normal'),enemy)
        self.observe(req)
        self.assertEqual(self.engine.enemy_analysis['event'],'entry')
        enemy.update(mode='fever',mode_generation=1,seed_id=2,awaiting_seed=False,
            queue=['2:RY','2:GG'],field=seed3(),remaining_frames=900)
        self.observe(req)
        self.assertEqual(self.engine.enemy_analysis['event'],'seed')

    def test_independent_preparation_survives_json_transfer(self):
        own=side('normal',queue=['2:RG','2:BY','2:YY'])
        own['character']='arle'
        req=request(own); req.update(op='prepare',placement=dict(x=2,r='U'))
        spare=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json'); self.addCleanup(spare.close)
        prepared=json.loads(json.dumps(spare.answer(req)))
        self.assertTrue(prepared['prepared'])
        plan=prepared['plan']
        latest=request(deepcopy(own)); latest['self'].update(field=plan['field'],queue=plan['queue'],
            piece_id=plan['piece_id'],dropset_index=plan['dropset_index'],moves_since_chain=1)
        latest['prepared_state']=prepared['prepared_state']
        with patch.object(self.engine.solo,'ask',side_effect=AssertionError('must reuse the independent build')):
            reply=self.engine.answer(latest)
        self.assertTrue(reply['normal_search_reused'])
        self.assertEqual(reply['search_ms'],0.)

    def test_new_match_discards_previous_attack(self):
        req=request(side('normal'),side('fever',seed3(),['2:RY','2:GG']))
        self.observe(req)
        req['match_id']='new-match';req['frame']=0
        self.observe(req)
        self.assertEqual(self.engine.enemy_analysis['seed'][0],'new-match')


if __name__ == '__main__':
    unittest.main()
