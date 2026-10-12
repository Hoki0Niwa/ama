"""R1 intermediate termination, held-out selection, native guards and isolation."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import EMPTY, Observation
from fever_battle.first40_root_evaluation import (CapturedB0, WorldEnvironment,
    aggregate_roots, continue_world, generate_world, guard_accepts, observation_hash,
    propose, read_observation, sample_seed, select_arm, stable_reply)
from fever_battle.worker import JsonProcess
from tools.evaluate_fever_first40_roots import analyze, success_bounds


def board(count):
    cells = '.' * (84 - count) + 'R' * count
    return [cells[i:i + 6] for i in range(0, 84, 6)]


class FakeEnvironment:
    def __init__(self, chains, dead=False):
        self.chains = iter(chains); self.dead = dead
    def visible(self, t):
        return ("2:RR",) * 3
    def processes(self):
        return {}
    def transition(self, field, piece, decision):
        count = next(self.chains)
        mass = sum(row.count('R') for row in field) + 2 - 4 * count
        return dict(field=board(mass), links=[dict(groups=[4]) for _ in range(count)],
                    discarded=0, dead=self.dead)


class FakeBackend:
    def __init__(self, seen):
        self.seen = seen
    def processes(self):
        return {}
    def close(self):
        pass
    def choose(self, obs):
        self.seen.append(obs)
        return dict(x=0, r='U', next_field=board(10), next_chain=15)


class ContractTests(unittest.TestCase):
    def test_intermediate_cleanup_advances_clock_and_history(self):
        obs = Observation(tuple(board(70)), ('2:RR',) * 3, 'raffina', 38, 5, 9, 0)
        records, seen = [], []
        r = continue_world(obs, dict(x=0, r='U'), FakeEnvironment([1,15]),
            lambda: FakeBackend(seen), records.append)
        self.assertEqual(r['success_move'],40)
        self.assertEqual(r['continuation_placements'],2)
        self.assertEqual(r['cleanup_1_3'],1)
        self.assertEqual((seen[0].placed_total,seen[0].dropset_index,seen[0].moves_since_chain,seen[0].normal_chain_max),(39,6,0,1))
        self.assertEqual([r['move'] for r in records],[39,40])

    def test_short_first_mainline_absorbs_and_same_transition_death_fails(self):
        obs = Observation(tuple(board(70)), ('2:RR',) * 3, 'raffina', 29,29,0,0)
        for chain,dead,outcome in ((14,False,'first_below_target'),(15,True,'dead')):
            r = continue_world(obs,dict(x=0,r='U'),FakeEnvironment([chain,15],dead),
                lambda: FakeBackend([]),lambda _:None)
            self.assertEqual(r['outcome'],outcome)
            self.assertEqual(r['continuation_placements'],1)
            self.assertFalse(any(r['success'].values()))

    def test_budget_censoring_and_factory_failure_are_retained(self):
        obs = Observation(tuple(board(70)), ('2:RR',)*3,'raffina',39,39,0,0)
        r = continue_world(obs,dict(x=0,r='U'),FakeEnvironment([15]),
            lambda: FakeBackend([]),lambda _:None,time.perf_counter()-1)
        self.assertEqual(r['outcome'],'unfinished'); self.assertFalse(r['complete'])
        def broken():
            raise RuntimeError('cannot start backend')
        fail = continue_world(obs,dict(x=0,r='U'),FakeEnvironment([15]),broken,lambda _:None)
        self.assertEqual(fail['outcome'],'engine_error')
        b = success_bounds([r,fail])
        self.assertEqual((b['planned'],b['completed'],b['unfinished']),(2,1,1))
        self.assertEqual(b['rate_bounds'],[0,.5])

    def test_first_move_40_inclusive_41_has_no_input(self):
        obs = Observation(tuple(board(70)), ('2:RR',)*3,'raffina',39,39,0,0)
        r = continue_world(obs,dict(x=0,r='U'),FakeEnvironment([15]),
            lambda: FakeBackend([]),lambda _:None)
        self.assertEqual(r['success'],{'30':False,'35':False,'40':True})
        with self.assertRaises(ValueError): read_observation(asdict(replace(obs,placed_total=40)))

    def test_public_input_and_rng_splits(self):
        obs=Observation(tuple(EMPTY),('2:RR',)*3,'raffina',0,0,0,0)
        with self.assertRaises(ValueError): read_observation(dict(asdict(obs),seed=1))
        digest=observation_hash(obs)
        expected=int.from_bytes(hashlib.sha256(f'ama.first40.root-eval.v1|{digest}|select|0'.encode()).digest()[:8],'big')
        self.assertEqual(sample_seed(digest,'select',0),expected)
        seeds={sample_seed(digest,s,i) for s in ('select','validate') for i in range(4)}
        self.assertEqual(len(seeds),8)
        for args in (('actual',0),('validate',4),('select',True)):
            with self.assertRaises(ValueError): sample_seed(digest,*args)

    def test_selector_tie_safety_and_unfinished(self):
        def row(arm,success=False,outcome='no_mainline',complete=True):
            return dict(arm=arm,success={'40':success},outcome=outcome,complete=complete)
        rows=[row(a) for a in ('a0','a1') for _ in range(4)]
        self.assertEqual(select_arm(rows,True),'a0')
        rows[4]=row('a1',True,'success')
        self.assertEqual(select_arm(rows,True),'a1')
        rows[5]=row('a1',False,'nomove')
        self.assertEqual(select_arm(rows,True),'a0')
        rows[5]=row('a1',False,'unfinished',False)
        self.assertEqual(select_arm(rows,True),'a0')

    def test_validation_does_not_reselect_from_posthoc_winner(self):
        cases=[]; rows=[]; selected={}
        for i in range(16):
            cid=str(i); ch='raffina' if i<8 else 'rafisol'
            cases.append(dict(case_id=cid,character=ch,source_seed=i,move=24,a1={'x':1,'r':'U'}))
            selected[cid]='a0'
            for arm in ('a0','a1'):
                for j in range(4):
                    rows.append(dict(case_id=cid,scope='main',split='validate',arm=arm,world_index=j,
                        complete=True,outcome='success' if arm=='a1' else 'no_mainline',
                        success={str(h):arm=='a1' for h in (30,35,40)},first_main_chain=15 if arm=='a1' else None))
        result=analyze(cases,rows,selected)
        self.assertEqual((result['gains'],result['losses'],result['switch_cases']),(0,0,0))
        self.assertEqual(result['cases'][0]['posthoc_best_success_count'],4)
        self.assertFalse(result['gate']['pass_to_lightweight_design'])

    def test_b0_comparator_stretch_trigger_room_and_stability(self):
        candidates=[dict(x=x,r='U',score=score,aim=0,chain=chain,next_room=room)
            for x,score,chain,room in ((0,100,15,2),(1,200,15,2),(2,900,16,0),(3,100,15,2))]
        search=dict(virtual_searches=[dict(final_candidates=candidates) for _ in range(6)])
        self.assertEqual([r['x'] for r in aggregate_roots(search,dict(stretch=True,trigger=15))],[1,0,3,2])
        self.assertEqual([r['x'] for r in aggregate_roots(search,dict(stretch=False,trigger=15))],[0,3,1,2])


@unittest.skipUnless(os.environ.get('AMA_TEST_F40_REFERENCE') and os.environ.get('AMA_TEST_F40_DIAGNOSTIC'), 'requires frozen research binaries')
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.native=Path(os.environ['AMA_TEST_F40_REFERENCE'])
        self.diag=Path(os.environ['AMA_TEST_F40_DIAGNOSTIC'])
        self.plan=json.loads((ROOT/'data/fever/baselines/2026-10-12-f40-root-plan/selection.json').read_text(encoding='utf8'))
        self.backend=CapturedB0(self.native,ROOT/'config.json');self.addCleanup(self.backend.close)
        self.worker=JsonProcess([self.native],cwd=ROOT);self.addCleanup(self.worker.close)
        self.diagnostic=JsonProcess([self.diag],cwd=ROOT);self.addCleanup(self.diagnostic.close)

    def test_real_proposal_and_fire_lock_preserve_b0(self):
        for index in (0,4,10):
            c=self.plan['selected_observations'][index];obs=read_observation(c['observation'])
            report=propose(self.backend,self.diagnostic,self.worker,obs)
            self.assertEqual(report['a0'],c['source_b0_placement'])
            self.assertEqual(stable_reply(report['native_reply']),stable_reply(report['diagnostic']))
            if index==4:self.assertEqual(report['fixed_reason'],'fire_or_adoption_guard')
            if report['a1']:
                self.assertNotEqual(report['a0'],report['a1'])
                self.assertFalse(report['alternate_transition']['dead'])
                self.assertEqual(report['alternate_transition']['discarded'],0)
            self.assertTrue(all('seed' not in call['request'] for call in self.backend.calls))

    def test_real_phase_all_shapes_and_hidden_suffix_isolation(self):
        q=self.worker.ask(dict(op='queue',character='raffina',seed=1,count=55))['queue']
        replies=[]
        for phase in (0,2,5,9,15):
            obs=Observation(tuple(EMPTY),tuple(q[phase:phase+3]),'raffina',23,phase,0,0)
            queue,offset=generate_world(self.worker,obs,1)
            self.assertEqual(queue[offset+23:offset+26],list(obs.visible))
            self.assertEqual([p[0] for p in queue[offset+26:offset+30]],
                             [p[0] for p in q[phase+3:phase+7]])
        obs=read_observation(self.plan['selected_observations'][0]['observation'])
        worlds=[]
        for split in ('select','validate'):
            queue,offset=generate_world(self.worker,obs,sample_seed(observation_hash(obs),split,0))
            worlds.append(queue)
            self.backend.engine.normal_build_cache=None
            replies.append(stable_reply(self.backend.choose(obs)))
            env=WorldEnvironment(self.native,queue,offset)
            try:
                self.assertEqual(env.visible(obs.placed_total),obs.visible)
            finally:
                env.close()
        self.assertNotEqual(worlds[0][obs.placed_total+3:],worlds[1][obs.placed_total+3:])
        self.assertEqual(replies[0],replies[1])

    def test_existing_python_retention_guard_rejects_alternate(self):
        q=self.worker.ask(dict(op='queue',character='raffina',seed=1,count=3))['queue']
        obs=Observation(tuple(EMPTY),tuple(q),'raffina',0,0,0,0)
        reply=self.backend.choose(obs)
        placements=self.worker.ask(dict(op='placements',field=list(EMPTY),piece=q[0]))['placements']
        first,other=placements[0],next(p for p in placements if p['field']!=placements[0]['field'])
        self.backend.engine.normal_capacity=dict(available_chain=15,available_score=100,
            extensions=[dict(x=first['x'],r=first['r'],retains=True,chain=15,score=100)])
        root=dict(x=other['x'],r=other['r'],chain=15,score_sum=600)
        saved_cache=self.backend.engine.normal_build_cache
        accepted,guarded=guard_accepts(self.backend,obs,reply,root,other)
        self.assertFalse(accepted);self.assertTrue(guarded['normal_main_retained'])
        self.assertIs(self.backend.engine.normal_build_cache,saved_cache)


if __name__=='__main__':
    unittest.main()
