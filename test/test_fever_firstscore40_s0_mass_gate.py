"""S0G resource proof, unchanged delegation, shared deadline and net-effect gate."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.first40_benchmark import Observation, EMPTY, LegacyBackend
from fever_battle.firstscore40_s0_mass_gate import mass_gate, MassGatePlanner, MassGatedScoreBackend, PATTERNS
from fever_battle.firstscore40_backend import ScoreBackend
from tools.bench_fever_firstscore40_s0_mass_gate import gate,lookup_runs,audit_trial,full_cost,ARMS
from tools.confirm_fever_firstscore40_s0 import probe_request


def observation(n=0,t=0,character='raffina',phase=None):
    grid=[list(r) for r in EMPTY]
    for i in range(n):grid[13-i//6][i%6]='RYGB'[i%4]
    phase=t if phase is None else phase
    values={'2':'2:RG','L':'L:RRG','J':'J:RGR','4':'4:RRGG','0':'0:R'}
    return Observation(tuple(''.join(r) for r in grid),tuple(values[PATTERNS[character][(phase+i)%16]] for i in range(3)),character,t,phase,t,0)


class FakePlanner:
    def __init__(self,reply=None):
        self.calls=[];self.process=object();self.closed=False
        self.reply=reply or dict(decision=None,score_probe_complete=True,stats={'wall_ms':2})
    def ask(self,request,timeout=10):self.calls.append((request,timeout));return self.reply
    def close(self):self.closed=True


def synthetic():
    runs=[];audits=[]
    for c in ('raffina','rafisol'):
        for s in range(1001,1065):
            for b in ARMS:
                ok=s<1021 if b=='b0' else 1002<=s<1031
                r=dict(character=c,seed=s,backend=b,outcome='success' if ok else 'first_below_score',
                    success={str(h):ok for h in (30,35,40)},success_move=30 if ok else None,
                    timings_ms=[10.,12.],failed_think_ms=None,total_cpu_seconds=.022)
                runs.append(r);audits.append(dict(character=c,seed=s,backend=b,issues=[]))
    return runs,audits


class MassTests(unittest.TestCase):
    def test_strict_39_40_boundary_and_public_keys(self):
        self.assertTrue(mass_gate(observation(32))['skip'])
        result=mass_gate(observation(33))
        self.assertEqual(result['mass_upper'],40);self.assertFalse(result['skip'])
        self.assertNotIn('seed',json.dumps(asdict(observation())))

    def test_all_character_shapes_and_big_counts_four(self):
        for c in ('raffina','rafisol'):
            for phase in range(16):
                obs=observation(character=c,phase=phase)
                g=mass_gate(obs)
                self.assertTrue(g['gate_checked'])
                expected=sum({'2':2,'L':3,'J':3,'4':4,'0':4}[p[0]] for p in obs.visible)
                self.assertEqual(g['visible_mass'],expected)
        phase=PATTERNS['rafisol'].index('0')
        g=mass_gate(observation(t=39,character='rafisol',phase=phase))
        self.assertEqual((g['gate_horizon'],g['visible_mass']),(1,4))

    def test_remaining_horizon_and_cleanup_absolute_time(self):
        a=mass_gate(observation(32,t=38));b=mass_gate(replace(observation(32,t=38),moves_since_chain=0,normal_chain_max=3))
        self.assertEqual(a['gate_horizon'],2);self.assertEqual(a['mass_upper'],b['mass_upper'])
        self.assertEqual(mass_gate(observation(32,t=39))['gate_horizon'],1)

    def test_nuisance_not_counted_and_discard_not_subtracted(self):
        obs=observation(33);field=list(obs.field);field[-1]=field[-1].replace('R','#')
        g=mass_gate(replace(obs,field=tuple(field)))
        self.assertEqual(g['board_colored'],31)
        # Cells at the top of a surviving outer column remain in the upper bound.
        field=['......']*14
        for i in range(1,14):field[i]='R.....'
        self.assertEqual(mass_gate(replace(observation(),field=tuple(field)))['board_colored'],13)

    def test_unknown_malformed_and_wrong_cycle_fail_open(self):
        samples=[];base=asdict(observation())
        for key,value in [('placed_total',True),('placed_total',40),('normal_chain_max',10),('character','arle'),('visible',['0:R']*3),('visible',['2:R#']*3),('field',['......']*13)]:
            samples.append(dict(base,**{key:value}))
        samples.append(dict(base,seed=99));samples.append(None)
        for o in samples:
            g=mass_gate(o);self.assertFalse(g['skip']);self.assertFalse(g['gate_checked'])

    def test_uniform_triple_cycle_normalization(self):
        phase=PATTERNS['raffina'].index('L');obs=observation(phase=phase)
        visible=list(obs.visible);visible[0]='J:RRR'
        self.assertTrue(mass_gate(replace(obs,visible=tuple(visible)))['gate_checked'])

    def test_proxy_skip_has_no_rpc_and_no_enumeration_claim(self):
        fake=FakePlanner();proxy=MassGatePlanner(fake);reply=proxy.ask(probe_request(observation()))
        self.assertEqual(fake.calls,[]);self.assertIsNone(reply['score_probe_complete'])
        self.assertEqual(reply['probe_status'],'not_run_mass_impossible')
        self.assertEqual(reply['stats']['transition_attempts'],0);self.assertIsNone(reply['stats']['wall_ms'])
        self.assertIs(proxy.process,fake.process);proxy.ask({'op':'reset'},timeout=.2);proxy.close()
        self.assertEqual(fake.calls,[({'op':'reset'},.2)]);self.assertTrue(fake.closed)

    def test_non_skip_request_timeout_and_reply_delegate_exactly(self):
        marker=dict(decision={'proof':[{'links':14}]},score_probe_complete=True)
        fake=FakePlanner(marker);proxy=MassGatePlanner(fake);request=probe_request(observation(56))
        reply=proxy.ask(request,timeout=.123)
        self.assertIs(fake.calls[0][0],request);self.assertEqual(fake.calls[0][1],.123)
        for k,v in marker.items():self.assertIs(reply[k],v)
        self.assertFalse(reply['mass_guard']['skip'])

    def test_invalid_rpc_limits_and_extra_seed_do_not_shortcut(self):
        for extra in ({'seed':7},{'work_budget_ms':float('nan')},{'transition_limit':-1},{'witness_limit':True}):
            fake=FakePlanner();proxy=MassGatePlanner(fake)
            proxy.ask(dict(probe_request(observation()),**extra))
            self.assertEqual(len(fake.calls),1)

    def test_same_fallback_observation_and_absolute_deadline(self):
        def init(self,*a,**kw):
            self.planner=FakePlanner();self.budget_ms=250;self.experiment_deadline=None
            self.planner_budget_ms=25;self.mode='s0';self.settings={'transition_limit':16000,'witness_limit':48000}
        clock=[20.];seen={}
        def fallback(self,obs):
            seen.update(observation=obs,deadline=self.deadline);clock[0]+=.251
            return {'x':0,'r':'U'}
        with patch.object(ScoreBackend,'__init__',init),patch.object(LegacyBackend,'choose',fallback),patch('time.perf_counter',lambda:clock[0]):
            actor=MassGatedScoreBackend(None,None,None);obs=observation()
            with self.assertRaises(TimeoutError):actor.choose(obs)
            self.assertIs(seen['observation'],obs);self.assertEqual(seen['deadline'],20.25)
            self.assertTrue(actor.last_planner['mass_guard']['skip']);self.assertIsNone(actor.deadline)

    def test_failed_planner_rpc_preserves_guard(self):
        def init(self,*a,**kw):
            self.planner=FakePlanner();self.budget_ms=250;self.experiment_deadline=None
            self.planner_budget_ms=25;self.mode='s0';self.settings={'transition_limit':16000,'witness_limit':48000}
        with patch.object(ScoreBackend,'__init__',init):
            actor=MassGatedScoreBackend(None,None,None)
            def fail(*a,**kw):raise TimeoutError('late')
            actor.planner.delegate.ask=fail
            with self.assertRaises(TimeoutError):actor.choose(observation(56))
            self.assertEqual(actor.last_planner['probe_status'],'failed_before_reply')
            self.assertFalse(actor.last_planner['mass_guard']['skip'])


class GateTests(unittest.TestCase):
    def test_net_positive_with_individual_losses_can_pass(self):
        runs,audits=synthetic();r=gate(runs,range(1001,1065),True,audits)
        self.assertTrue(r['eligible']);self.assertEqual(r['clustered']['s0g_vs_b0']['net_gain'],18)
        self.assertEqual(len(r['paired']['raffina']['loss_seeds']),1)

    def test_baseline_timeout_is_not_an_absolute_veto(self):
        runs,audits=synthetic()
        r=next(r for r in runs if r['backend']=='b0' and r['character']=='raffina' and r['seed']==1050)
        r.update(outcome='timeout',failed_think_ms=251.)
        self.assertTrue(gate(runs,range(1001,1065),True,audits)['eligible'])

    def test_timeout_excess_and_latency_included(self):
        runs,audits=synthetic()
        for r in runs:
            if r['backend']=='s0g' and r['character']=='raffina' and r['seed'] in (1050,1051,1052):r.update(outcome='timeout',failed_think_ms=253.)
        result=gate(runs,range(1001,1065),True,audits)
        self.assertFalse(result['safety']);self.assertFalse(result['eligible'])
        self.assertEqual(full_cost(runs)['raffina/s0g']['maximum_ms'],253.)

    def test_two_trial_retention_tolerance_not_three(self):
        runs,audits=synthetic()
        for r in runs:
            if r['backend']=='s0g' and r['character']=='raffina' and r['seed'] in (1028,1029):
                r.update(outcome='first_below_score',success={str(h):False for h in (30,35,40)},success_move=None)
        self.assertTrue(gate(runs,range(1001,1065),True,audits)['retention'])
        r=next(r for r in runs if r['backend']=='s0g' and r['character']=='raffina' and r['seed']==1030)
        r.update(outcome='first_below_score',success={str(h):False for h in (30,35,40)},success_move=None)
        self.assertFalse(gate(runs,range(1001,1065),True,audits)['retention'])

    def test_incomplete_duplicates_missing_audit_and_no_cost_hold(self):
        runs,audits=synthetic()
        for rr,aa in [(runs[:-1],audits),(runs+[runs[0]],audits),(runs,audits[:-1])]:
            self.assertEqual(gate(rr,range(1001,1065),True,aa)['disposition'],'hold_invalid_or_incomplete')
        runs[0]['total_cpu_seconds']=None
        self.assertFalse(gate(runs,range(1001,1065),True,audits)['eligible'])
        with self.assertRaises(ValueError):lookup_runs(runs[:-1],range(1001,1065))

    def test_proof_bug_is_hard_failure_even_with_net_gain(self):
        runs,audits=synthetic();audits[0]['issues']=[{'reason':'bad proof'}]
        self.assertFalse(gate(runs,range(1001,1065),True,audits)['eligible'])

    def test_saved_actual_F_valid_for_s0g_and_skip_contradiction_rejected(self):
        base=ROOT/'data/fever/baselines/2026-10-13-firstscore40-s0-confirm/confirmation'
        rr=json.loads((base/'runs.json').read_text(encoding='utf-8'))
        result=next(r for r in rr if r['backend']=='s0' and r['character']=='raffina' and r['seed']==61004)
        rows=[]
        for line in (base/'steps.jsonl').read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if (r['character'],r['seed'],r['backend'])==('raffina',61004,'s0'):
                r['research_planner']['mass_guard']=mass_gate(r['observation'])
                r['research_planner']['probe_invoked']=not r['research_planner']['mass_guard']['skip']
                if r['research_planner']['mass_guard']['skip']:
                    r['research_planner']['score_probe_complete']=None
                rows.append(r)
        self.assertEqual(audit_trial(rows,dict(result,backend='s0g'),None)['issues'],[])
        fire=next(r for r in rows if r['research_planner'].get('decision'))
        fire['research_planner']['mass_guard']['skip']=True
        self.assertTrue(audit_trial(rows,dict(result,backend='s0g'),None)['issues'])


if __name__=='__main__':unittest.main()
