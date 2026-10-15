"""Confirmation contracts: paired clusters, failures and proof deadlines."""
from dataclasses import asdict
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import EMPTY, Observation
from fever_battle.firstscore40_benchmark import TARGETS, SCORING
from tools.confirm_fever_firstscore40_s0 import (
    RecordingBackend, recorded_trial, public_rows, clustered, sign_flip, gate,
    audit_fire, probe_request, full_cost, lookup_runs, canonical_piece)


def synthetic(gains=(), losses=(), timeout=None):
    runs, audits = [], []
    for c in TARGETS:
        for seed in range(61001, 61065):
            for b in ('b0', 's0'):
                success = (c, seed) in (gains if b == 's0' else losses)
                outcome = 'success' if success else 'first_below_score'
                if (c, seed, b) == timeout: outcome = 'timeout'; success = False
                r = dict(character=c, seed=seed, backend=b, outcome=outcome,
                         success={str(h):success for h in (30,35,40)}, success_move=30 if success else None,
                         timings_ms=[10.,12.], failed_think_ms=251. if outcome=='timeout' else None,
                         total_cpu_seconds=.02)
                runs.append(r)
                audits.append(dict(character=c, seed=seed, backend=b, issues=[]))
    return runs, audits


class ConfirmationTests(unittest.TestCase):
    def test_seed_cluster_not_independent_character_rows(self):
        runs, _ = synthetic(gains=[(c,s) for c in TARGETS for s in range(61001,61005)])
        result = clustered(runs, range(61001,61065))
        self.assertEqual(result['net_gain'],8)
        self.assertEqual(result['sign_flip_one_sided'],1/16)
        self.assertEqual(result['q'][:4],[2]*4)
        self.assertEqual(result['seed_clusters'],64)

    def test_exact_sign_flip_with_zero_and_negative_clusters(self):
        self.assertEqual(sign_flip([0]*64),1)
        self.assertEqual(sign_flip([1]*5),1/32)
        self.assertEqual(sign_flip([2]*4),1/16)
        self.assertEqual(sign_flip([-1,-2]),1)
        self.assertEqual(sign_flip([1,-1]),.75)

    def test_two_arm_gate_pass_and_small_signal_hold(self):
        good=[('raffina',s) for s in range(61001,61005)]+[('rafisol',s) for s in range(61005,61008)]
        runs,audits=synthetic(gains=good)
        passed=gate(runs,range(61001,61065),True,audits)
        self.assertEqual(passed['disposition'],'eligible_for_next_research_baseline')
        self.assertEqual(passed['clustered']['net_gain'],7)
        runs,audits=synthetic(gains=[('raffina',61001),('rafisol',61002)])
        self.assertEqual(gate(runs,range(61001,61065),True,audits)['disposition'],'hold_insufficient_evidence')

    def test_losses_and_failed_delays_not_hidden(self):
        good=[('raffina',s) for s in range(61001,61009)]+[('rafisol',61010)]
        runs,audits=synthetic(gains=good,losses=[('rafisol',61011)])
        result=gate(runs,range(61001,61065),True,audits)
        self.assertEqual(result['disposition'],'not_adopted_current_s0_250')
        self.assertEqual(result['losses'],1)
        runs,audits=synthetic(gains=good,timeout=('rafisol',61012,'s0'))
        result=gate(runs,range(61001,61065),True,audits)
        self.assertFalse(result['safety'])
        self.assertEqual(full_cost(runs)['rafisol/s0']['maximum_ms'],251.)

    def test_invalid_incomplete_duplicate_and_missing_audit_hold(self):
        runs,audits=synthetic()
        self.assertFalse(gate(runs,range(61001,61065),False,audits)['eligible'])
        self.assertFalse(gate(runs,range(61001,61065),True,audits,False)['eligible'])
        with self.assertRaises(ValueError):lookup_runs(runs+[runs[0]],range(61001,61065))
        with self.assertRaises(ValueError):lookup_runs(runs[:-1],range(61001,61065))
        self.assertEqual(gate(runs,range(61001,61065),True,audits[:-1])['disposition'],'hold_invalid_or_incomplete')
        runs[0]['outcome']='engine_error'
        self.assertEqual(gate(runs,range(61001,61065),True,audits)['disposition'],'hold_invalid_or_incomplete')

    def test_cost_and_early_success_protected(self):
        good=[('raffina',s) for s in range(61001,61005)]+[('rafisol',s) for s in range(61005,61008)]
        runs,audits=synthetic(gains=good)
        for row in runs:
            if row['backend']=='s0':row['total_cpu_seconds']=.024
        self.assertFalse(gate(runs,range(61001,61065),True,audits)['cost'])
        runs,audits=synthetic(gains=good)
        for row in runs:
            if row['backend']=='s0':
                row['success']['30']=False
                if row['success']['40']:row['success_move']=35
            if row['character']=='rafisol' and row['seed']==61050:
                row['success']={'30':row['backend']=='b0','35':True,'40':True}
                row['success_move']=30 if row['backend']=='b0' else 35
        self.assertFalse(gate(runs,range(61001,61065),True,audits)['early'])

    def test_public_history_from_cleanup_and_no_seed_input(self):
        rows=[dict(character='raffina',seed=9,backend='s0',move=i,before=list(EMPTY),queue=['2:RR']*3,
                   links=[dict(colors=1,groups=[4])] if i==2 else []) for i in range(1,5)]
        obs=[o for _,o in public_rows(rows,'s0')]
        self.assertEqual([(o.placed_total,o.moves_since_chain,o.normal_chain_max) for o in obs],
                         [(0,0,0),(1,1,0),(2,0,1),(3,1,1)])
        request=probe_request(obs[-1])
        self.assertEqual(set(request['observation']),set(asdict(obs[-1])))
        self.assertNotIn('seed',json.dumps(request))
        self.assertEqual((request['work_budget_ms'],request['transition_limit']),(25,16000))

    def test_failure_keeps_public_input_and_incomplete_probe(self):
        class Fake:
            last_planner={}
            def choose(self,observation):
                self.last_planner={'score_probe_complete':False,'decision':None,'stats':{'stop_reason':'wall_budget'}}
                raise TimeoutError('total choose budget exceeded')
            def processes(self):return {}
            def close(self):pass
        class Env:
            def visible(self,t):return ('2:RR',)*3
            def processes(self):return {}
            def close(self):pass
        emitted=[]
        result,records=recorded_trial('raffina',1,'s0',Fake,lambda c,s:Env(),emitted.append)
        self.assertEqual(result['outcome'],'timeout')
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['observation']['placed_total'],0)
        self.assertNotIn('seed',records[0]['observation'])
        self.assertEqual(records[0]['research_planner']['stats']['stop_reason'],'wall_budget')
        self.assertIsNotNone(result['failed_think_ms'])

    def test_wrapper_delegates_exact_observation_and_response(self):
        marker=object();obs=Observation(tuple(EMPTY),('2:RR',)*3,'raffina',0,0,0,0)
        class Fake:
            last_planner={}
            def choose(self,x):self.seen=x;return marker
        fake=Fake();wrapped=RecordingBackend(fake)
        self.assertIs(wrapped.choose(obs),marker);self.assertIs(fake.seen,obs)

    def proof_row(self, move=30):
        links=[dict(groups=[4],colors=1)]*15
        proof=dict(before=list(EMPTY),after=list(EMPTY),piece='2:RR',move=move,
                   placement={'x':0,'r':'U'},links=links,score=TARGETS['raffina'],dead=False,discarded=0)
        return dict(move=move,before=list(EMPTY),after=list(EMPTY),queue=['2:RR']*3,x=0,r='U',links=links,dead=False,
                    research_planner={'score_probe_complete':True,'decision':{'proof':[proof]}})

    def test_proof_deadline_real_success_and_no_phantom_failed_proposal(self):
        result=dict(character='raffina',backend='s0',success={'40':True},success_move=30)
        audit=audit_fire([self.proof_row()],result)
        self.assertEqual(audit['first_proof_deadline'],30);self.assertEqual(audit['issues'],[])
        result.update(success={'40':False},success_move=None)
        self.assertTrue(audit_fire([self.proof_row()],result)['issues'])
        self.assertFalse(audit_fire([{'event':'failure','research_planner':{'decision':{'proof':[1]}}}],result)['adopted_proof'])

    def test_proof_future_piece_score_absorption_and_deadline_rejected(self):
        result=dict(character='raffina',backend='s0',success={'40':True},success_move=30)
        for key,value in [('piece','2:YY'),('score',123),('dead',True),('move',31)]:
            row=self.proof_row();row['research_planner']['decision']['proof'][0][key]=value
            with self.assertRaises(ValueError):audit_fire([row],result)
        row=self.proof_row(40);p=row['research_planner']['decision']['proof'];p.append(deepcopy(p[0]))
        with self.assertRaises(ValueError):audit_fire([row],result)
        row=self.proof_row(30);p=row['research_planner']['decision']['proof'];p.append(deepcopy(p[0]));p[1]['move']=31
        with self.assertRaises(ValueError):audit_fire([row],result)

    def test_only_uniform_triple_notation_can_normalize(self):
        self.assertEqual(canonical_piece('J:BBB'),'L:BBB')
        self.assertEqual(canonical_piece('J:BBR'),'J:BBR')
        self.assertEqual(canonical_piece('4:BBRR'),'4:BBRR')

    def test_remaining_proof_decreases_without_extending_first_deadline(self):
        first=self.proof_row(30)
        last=deepcopy(first['research_planner']['decision']['proof'][0]);last['move']=31
        first['research_planner']['decision']['proof'][0].update(links=[],score=0)
        first['research_planner']['decision']['proof'].append(last);first['links']=[]
        second=self.proof_row(31)
        result=dict(character='raffina',backend='s0',success={'40':True},success_move=31)
        self.assertEqual(audit_fire([first,second],result)['issues'],[])
        later=deepcopy(second['research_planner']['decision']['proof'][0]);later['move']=32
        second['research_planner']['decision']['proof'][0].update(links=[],score=0)
        second['research_planner']['decision']['proof'].append(later);second['links']=[]
        result['success_move']=32
        issues=audit_fire([first,second,self.proof_row(32)],result)['issues']
        self.assertIn('extended_fire_deadline',[v['reason'] for v in issues])


if __name__=='__main__':unittest.main()
