"""Score boundary, first-fire absorption, real legal planning and public-input isolation."""
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.first40_benchmark import EMPTY,Observation,geometry
from fever_battle.firstscore40_benchmark import TARGETS,SCORING,terminal,trial_result,run_trial,summarize
from fever_battle.firstscore40_backend import ScoreBackend
from fever_battle.worker import JsonProcess
from tools.bench_fever_firstscore40 import gate


def links(n,tail=4):
    return [dict(groups=[4],colors=1)]*(n-1)+[dict(groups=[tail],colors=1)] if n else []


def rows(events,limit=40,dead_at=None):
    return [dict(move=m,chain=len(events.get(m,[])),links=events.get(m,[]),dead=m==dead_at,
                 popped_colored=sum(sum(l['groups']) for l in events.get(m,[])),discarded=0,
                 elapsed_ms=1.,after_geometry=geometry(EMPTY)) for m in range(1,limit+1)]


class ContractTests(unittest.TestCase):
    def test_character_scoring_and_tail14(self):
        for c,target in TARGETS.items():
            self.assertEqual(sum(SCORING.chain(c,links(15))),target)
            self.assertEqual(sum(SCORING.chain(c,links(14,8))),target+320)
            self.assertEqual(terminal(dict(move=30,links=links(14,8)),c),'success')

    def test_exact_score_inclusive_chain_not_a_shortcut(self):
        row=dict(move=40,links=links(15))
        self.assertEqual(terminal(row,'raffina'),'success')
        with patch.dict(TARGETS,raffina=160521):self.assertEqual(terminal(row,'raffina'),'first_below_score')
        with patch.dict(TARGETS,raffina=160519):self.assertEqual(terminal(row,'raffina'),'success')

    def test_first_under_score_absorbs_later_target(self):
        r=trial_result('raffina',1,'b0',rows({29:links(14),35:links(15)}))
        self.assertEqual((r['outcome'],r['placed_moves']),('first_below_score',29))
        self.assertFalse(r['success']['40'])

    def test_30_35_40_and_41(self):
        for move,expected in ((30,[True,True,True]),(35,[False,True,True]),(40,[False,False,True]),(41,[False,False,False])):
            r=trial_result('rafisol',1,'b0',rows({move:links(14,8)},41))
            self.assertEqual(list(r['success'].values()),expected)

    def test_cleanup_not_summed_and_death_precedes_points(self):
        r=trial_result('raffina',1,'b0',rows({18:links(3,20),30:links(14)}))
        self.assertEqual(r['outcome'],'first_below_score');self.assertGreater(r['nonmain_score'],0)
        self.assertEqual(r['first_main_score'],132560)
        r=trial_result('raffina',1,'b0',rows({30:links(15)},dead_at=30))
        self.assertEqual(r['outcome'],'dead');self.assertFalse(r['success']['40'])

    def test_failures_remain_denominator(self):
        for error,expected in ((ValueError('no placement survives'),'nomove'),(TimeoutError('budget'),'timeout'),(RuntimeError('closed'),'engine_error')):
            def broken(c,s):raise error
            r=run_trial('raffina',1,'b0',lambda:None,broken,lambda row:None)
            self.assertEqual(r['outcome'],expected)
            metric=summarize([r])['b0/raffina']['metrics']['Pscore_first@40']
            self.assertEqual((metric['successes'],metric['trials']),(0,1))

    def test_goal_actions_are_not_success_and_incomplete_gate(self):
        self.assertFalse(gate([],False)['pass_to_practical'])
        r=trial_result('raffina',1,'h1',rows({}))
        self.assertFalse(r['success']['40']);self.assertEqual(r['goal_actions'],0)

    def test_global_censoring_distinct_from_real_timeout(self):
        from fever_battle.firstscore40_backend import ExperimentExpired
        def broken(c,s):raise ExperimentExpired('research cap')
        r=run_trial('raffina',1,'b0',lambda:None,broken,lambda row:None)
        self.assertEqual(r['outcome'],'unfinished')
        self.assertEqual(summarize([r])['b0/raffina']['success_rate_bounds_40'],[0,1])

    def test_scoring_header_canonical(self):
        from tools.generate_fever_normal_scoring import render,TARGET
        self.assertEqual(TARGET.read_text(encoding='utf-8'),render())


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=Path(os.environ.get('AMA_TEST_F40_REFERENCE',ROOT/'bin/f40-diagnostics/reference/bin/commit-build/fever_battle.exe'))
        cls.planner=Path(os.environ.get('AMA_TEST_FIRSTSCORE_PLANNER',ROOT/'bin/firstscore40/build-v4/firstscore40.exe'))
        if not cls.native.exists() or not cls.planner.exists():raise RuntimeError('native test binaries required; do not silently skip')
        cls.steps=[]
        for line in (ROOT/'data/fever/baselines/2026-10-12-f40-deadline/development24/steps.jsonl').read_text().splitlines():
            r=json.loads(line)
            if r['backend']=='b0' and 'links' in r:cls.steps.append(r)

    def observation(self,row):
        before=[r for r in self.steps if r['character']==row['character'] and r['seed']==row['seed'] and r['move']<row['move']]
        return Observation(tuple(row['before']),tuple(row['queue']),row['character'],row['move']-1,row['move']-1,
                           row['options']['moves'],max([0]+[len(r['links']) for r in before]))

    def request(self,obs,goals=False,**limits):
        return dict(op='goal-choose' if goals else 'score-probe',observation=asdict(obs),
                    work_budget_ms=700,transition_limit=16000,witness_limit=48000,**limits)

    def test_real_visible_fire_proof_and_python_cpp_scores(self):
        with JsonProcess([self.planner],cwd=ROOT) as worker,JsonProcess([self.native],cwd=ROOT) as native:
            for c,seed,move in (('raffina',31001,28),('rafisol',31017,38)):
                row=next(r for r in self.steps if r['character']==c and r['seed']==seed and r['move']==move)
                obs=self.observation(row);reply=worker.ask(self.request(obs))
                self.assertTrue(reply['score_probe_complete']);self.assertIsNotNone(reply['decision'])
                field=list(obs.field);first_main=None
                for evidence in reply['decision']['proof']:
                    tr=native.ask(dict(op='transition',field=field,piece=evidence['piece'],**evidence['placement']))
                    self.assertEqual(tr['field'],evidence['after']);self.assertEqual(tr['links'],evidence['links'])
                    self.assertEqual(sum(SCORING.chain(c,tr['links'])),evidence['score']);self.assertFalse(tr['dead'])
                    if len(tr['links'])>=10:first_main=evidence;break
                    field=tr['field']
                self.assertIsNotNone(first_main);self.assertGreaterEqual(first_main['score'],TARGETS[c])
                self.assertLessEqual(first_main['move'],40)

    def test_real_multistep_goal_and_observation_invalidation(self):
        row=next(r for r in self.steps if r['character']=='raffina' and r['seed']==31001 and r['move']==16)
        obs=self.observation(row)
        with JsonProcess([self.planner],cwd=ROOT) as worker,JsonProcess([self.native],cwd=ROOT) as native:
            reply=worker.ask(self.request(obs,True));self.assertEqual(reply['decision']['action_source'],'goal_new')
            goal=reply['goal'];self.assertGreaterEqual(len(goal['actions']),2);self.assertGreater(goal['planned_witness']['points'],goal['base_witness']['points'])
            self.assertIn(goal['base_witness']['color'],'RYGB')
            ident=goal['id'];field=list(obs.field)
            for i,action in enumerate(goal['actions']):
                if i:
                    actualrow=next(r for r in self.steps if r['character']=='raffina' and r['seed']==31001 and r['move']==16+i)
                    now=replace(obs,field=tuple(field),visible=tuple(actualrow['queue']),placed_total=obs.placed_total+i,
                                dropset_index=obs.dropset_index+i,moves_since_chain=obs.moves_since_chain+i)
                    reply=worker.ask(self.request(now,True));self.assertEqual(reply['decision']['action_source'],'goal_continue')
                    self.assertEqual(reply['goal']['id'],ident)
                tr=native.ask(dict(op='transition',field=field,piece=obs.visible[i],**action))
                self.assertEqual(tr['links'],[]);self.assertEqual(tr['discarded'],0);self.assertFalse(tr['dead'])
                self.assertEqual(tr['field'],goal['expected_fields_after_each_action'][i]);field=tr['field']
            worker.ask({'op':'reset'});initial=worker.ask(self.request(obs,True));self.assertEqual(initial['goal']['executed_steps'],1)
            changed=replace(obs,placed_total=obs.placed_total+1,dropset_index=obs.dropset_index+1,visible=tuple(next(r['queue'] for r in self.steps if r['character']=='raffina' and r['seed']==31001 and r['move']==17)))
            invalid=worker.ask(self.request(changed,True));self.assertIn('invalidated_goal',invalid)

    def test_hidden_input_rejected_budget_incomplete_and_no_repeat_state(self):
        row=next(r for r in self.steps if r['character']=='raffina' and r['seed']==31001 and r['move']==16);obs=self.observation(row)
        with JsonProcess([self.planner],cwd=ROOT) as worker:
            request=self.request(obs,True);request['seed']=123
            with self.assertRaisesRegex(ValueError,'public request'):worker.ask(request)
            request=self.request(obs,True);request['observation']['future']=['2:RR']
            with self.assertRaisesRegex(ValueError,'public request'):worker.ask(request)
            request=self.request(obs,True);request['transition_limit']=0
            reply=worker.ask(request);self.assertIsNone(reply['decision']);self.assertFalse(reply['score_probe_complete'])
            self.assertEqual(reply['stats']['stop_reason'],'transition_limit')
            a=worker.ask(self.request(obs,True));worker.ask({'op':'reset'});b=worker.ask(self.request(obs,True))
            self.assertEqual(a['decision'],b['decision']);self.assertEqual(a['goal'],b['goal'])

    def test_shapes_cycle_and_final_move_deadline(self):
        with JsonProcess([self.planner],cwd=ROOT) as worker:
            seen=set()
            for row in [r for r in self.steps if r['character']=='rafisol' and r['seed']==31001][:17]:
                obs=self.observation(row);request=self.request(obs);request['transition_limit']=0
                self.assertFalse(worker.ask(request)['score_probe_complete']);seen.add(obs.visible[0][0])
            self.assertEqual(seen,{'2','L','J','4','0'})
            row=next(r for r in self.steps if r['character']=='rafisol' and r['seed']==31017 and r['move']==40)
            reply=worker.ask(self.request(self.observation(row)))
            self.assertTrue(reply['score_probe_complete']);self.assertEqual(len(reply['decision']['proof']),1)
            self.assertEqual(reply['decision']['proof'][0]['move'],40)

    def test_b0_wrapper_identical_and_actual_deadline_failure(self):
        from fever_battle.first40_benchmark import LegacyBackend
        row=next(r for r in self.steps if r['character']=='raffina' and r['seed']==31001 and r['move']==16);obs=self.observation(row)
        old=LegacyBackend(self.native,ROOT/'config.json');new=ScoreBackend(self.native,self.planner,ROOT/'config.json','b0',1000)
        try:
            a=old.choose(obs);b=new.choose(obs)
            for k in ('x','r','next_field','next_chain','next_score'):self.assertEqual(a[k],b[k])
            new.budget_ms=.001
            with self.assertRaises(TimeoutError):new.choose(replace(obs,placed_total=obs.placed_total+1))
        finally:old.close();new.close()


if __name__=='__main__':unittest.main()
