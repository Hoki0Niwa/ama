"""Actual visible capacity and observed cadence, independent of virtual colors."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, request
from fever_battle.mode_engine import ModeBattleEngine


class CapacityTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        cls.saved=json.loads((ROOT/'data/fever/baselines/2026-10-11-second-final.json').read_text(encoding='utf-8'))
        cls.defense=json.loads((ROOT/'data/fever/baselines/2026-10-11-normal-defense-investigation.json').read_text(encoding='utf-8'))
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def capacity(self,seed,move):
        run=next(r for r in self.saved['runs'] if r['character']=='raffina' and r['seed']==seed)
        item=next(r for r in run['trace'] if r['move']==move)
        queue=[r['piece'] for r in run['trace'] if move<=r['move']<move+3]
        return self.engine.native.ask(dict(op='normal_capacity',field=item['before'],queue=queue,character='raffina',margin=1))

    def test_row13_continuations_are_examined_before_panic(self):
        c=self.capacity(2,80)
        self.assertGreater(c['safe_moves'],1)
        self.assertEqual(c['current_chain'],10)
        self.assertLess(c['visible_extension_chain'],c['current_chain'])
        self.assertFalse(c['crowded'])
        self.assertFalse(c['release'])

    def test_high_count_continues_an_actual_visible_improvement(self):
        c=self.capacity(2,29)
        self.assertGreater(c['safe_moves'],0)
        self.assertEqual(c['current_chain'],1)
        self.assertEqual(c['visible_extension_chain'],13)
        self.assertGreater(c['improving_moves'],0)
        self.assertFalse(c['release'])

    def test_actual_space_loss_still_releases_the_chain_target(self):
        c=self.engine.native.ask(dict(op='normal_capacity',field=['......']*3+['..#...']*11,
            queue=['2:RG','2:GB'],character='raffina',margin=1))
        self.assertEqual(c['safe_moves'],0)
        self.assertTrue(c['release'])

    def test_a_small_extension_cannot_replace_a_larger_visible_main(self):
        trial=json.loads((ROOT/'data/fever/baselines/2026-10-11-capacity-fixed-second.json').read_text(encoding='utf-8'))
        run=next(r for r in trial['runs'] if r['character']=='rafisol' and r['seed']==1)
        item=run['trace'][53]
        c=self.engine.native.ask(dict(op='normal_capacity',field=item['before'],
            queue=[r['piece'] for r in run['trace'][53:56]],character='rafisol',margin=1))
        for move in c['extensions']:
            if move['retains']:
                self.assertGreaterEqual(move['chain'],c['available_chain'])
                self.assertGreaterEqual(move['score'],c['available_score'])
            if move['improves']: self.assertTrue(move['retains'])
        self.assertTrue(c['release'] == (c['safe_moves']==0 or
            (c['crowded'] and c['available_chain']>2 and c['improving_moves']==0)))

    def test_crowded_builder_selects_a_verified_growth_move(self):
        run=next(r for r in self.saved['runs'] if r['character']=='raffina' and r['seed']==2)
        item=run['trace'][29]
        own=side('normal',item['before'],[r['piece'] for r in run['trace'][29:32]])
        own.update(normal_chain_max=14,dropset_index=29,piece_id=29)
        req=request(own); req.update(second_target_chain=14,solo_options=dict(beam_width=50,beam_depth=8))
        self.engine.policy['normal_build']['capacity_extensions']=True
        try:
            options=self.engine._normal_options(req,own)
            self.assertEqual(options['trigger'],14)
            result=self.engine._solo_build(own,options)
            growth=self.engine.normal_capacity['extensions']
            self.assertIn((result['x'],result['r']),[(p['x'],p['r']) for p in growth if p['improves']])
        finally:
            self.engine.policy['normal_build']['capacity_extensions']=False

    def test_changed_cadence_invalidates_prepared_defense_identity(self):
        req=request(side('normal',queue=['2:RY','2:BG']))
        self.engine.pace=42
        before=self.engine._signature(req,req['self'])
        self.engine.pace=120
        self.assertNotEqual(before,self.engine._signature(req,req['self']))
        self.engine.pace=None

    def test_cadence_delays_real_preparation_not_only_piece_count_guess(self):
        base=next(p['request'] for p in self.defense['probes'] if p['name']=='packet' and not p['fever'] and p['pending']==90)
        replies=[]
        for pace in (42,120,240):
            req=deepcopy(base)
            req.update(queue=['2:GB','2:YR','2:GB'],confirmed=0,unconfirmed=0,pace_frames=pace,budget_ms=0,
                enemy_events=[dict(type='link',frame=350,points=10800),dict(type='end',frame=400)])
            replies.append(self.engine.native.ask(req))
        # Compare the same root, not changing choices. Every legal root locks
        # later at slow cadence; fixed spawn/split time is not charged twice.
        roots=[{(c['x'],c['r']):c for c in r['candidates']} for r in replies]
        shared=set(roots[0])&set(roots[1])&set(roots[2])
        self.assertTrue(shared)
        for key in shared:
            frames=[r[key]['frame'] for r in roots]
            self.assertLess(frames[0],frames[1])
            self.assertLess(frames[1],frames[2])


if __name__=='__main__': unittest.main()
