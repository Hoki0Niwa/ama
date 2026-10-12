"""Score-based first-mainline research judge, preserving the legacy chain judge."""
from collections import Counter
from copy import deepcopy
import math
import statistics

from . import first40_benchmark as legacy
from .model import Scoring

SCHEMA='ama.firstscore40.v1'
TARGETS={'raffina':160520,'rafisol':166840}
SCORING=Scoring()


def score_step(row,character):
    row=deepcopy(row)
    row['link_points']=SCORING.chain(character,row['links'],'normal')
    row['actual_score']=sum(row['link_points'])
    row['target_score']=TARGETS[character]
    return row


def terminal(row,character):
    if row.get('dead'): return 'dead'
    if len(row['links'])>=10:
        return 'success' if sum(SCORING.chain(character,row['links'],'normal'))>=TARGETS[character] else 'first_below_score'
    if row['move']==40: return 'no_mainline'
    return None


def rescore_result(old,records):
    """Both judges stop at the first >=10/death/40; the executed prefix is identical."""
    row=deepcopy(old);character=row['character']
    prefix=[]
    for record in records:
        if record['move']!=len(prefix)+1:raise ValueError('non-contiguous trial')
        if record['move']>40:break
        prefix.append(record)
        if terminal(record,character):break
    first=next((r for r in prefix if len(r['links'])>=10),None)
    stop=terminal(prefix[-1],character) if prefix else None
    outcome=stop or old['outcome']
    if old.get('failure') and old['failure'].get('type')=='ExperimentExpired':
        outcome='unfinished'
    if outcome=='first_below_target':raise ValueError('missing first-main executed links')
    success=outcome=='success'
    move=first['move'] if success else None
    row.update(schema=SCHEMA,chain15_success=deepcopy(old['success']),outcome=outcome,
        success={str(h):bool(success and move<=h) for h in (30,35,40)},success_move=move,
        target_score=TARGETS[character],first_main_score=sum(SCORING.chain(character,first['links'],'normal')) if first else None,
        first_main_link_points=SCORING.chain(character,first['links'],'normal') if first else None,
        nonmain_score=sum(sum(SCORING.chain(character,r['links'],'normal')) for r in prefix if 0<len(r['links'])<10),
        sub10_at_target=[dict(move=r['move'],chain=len(r['links']),score=sum(SCORING.chain(character,r['links'],'normal')))
                        for r in prefix if 0<len(r['links'])<10 and sum(SCORING.chain(character,r['links'],'normal'))>=TARGETS[character]],
        goal_actions=sum(r.get('research_planner',{}).get('decision',{}).get('action_source','').startswith('goal_')
                         for r in prefix if r.get('research_planner',{}).get('decision')),
        goal_execution_counts=dict(Counter(r['research_planner']['goal']['id'] for r in prefix
                                         if r.get('research_planner',{}).get('goal'))))
    row['multistep_goal']=any(count>=2 for count in row['goal_execution_counts'].values())
    return row


def run_trial(character,seed,label,backend_factory,environment_factory,emit):
    records=[];holder={}
    def factory():
        backend=backend_factory();holder['backend']=backend;return backend
    def environment(c,s):
        instance=environment_factory(c,s);holder['environment']=instance;return instance
    def capture(record):
        if 'links' in record:
            record.update(score_step(record,character))
            backend=holder.get('backend')
            if backend is not None:
                record['research_planner']=deepcopy(getattr(backend,'last_planner',{}))
                record['memory_after_transition']=memory_sample({**backend.processes(),**holder['environment'].processes()})
            records.append(record)
        emit(record)
    old=legacy.run_trial(character,seed,label,factory,environment,capture)
    return rescore_result(old,records)


def memory_sample(processes):
    """Simultaneous all-native+driver sample after the actual transition."""
    import ctypes
    import os
    if os.name!='nt':return {'available':False}
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
            ('peak','working','qpeakpage','qpage','qpeaknonpage','qnonpage','pagefile','peakpagefile')]
    call=ctypes.WinDLL('psapi').GetProcessMemoryInfo
    call.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD];call.restype=wintypes.BOOL
    handles={name:wintypes.HANDLE(int(process._handle)) for name,process in processes.items()}
    handles['python_driver']=wintypes.HANDLE(-1)
    result={}
    for name,handle in handles.items():
        counter=Counters();counter.cb=ctypes.sizeof(counter)
        result[name]=dict(working_set_bytes=counter.working,lifetime_peak_bytes=counter.peak) if call(handle,ctypes.byref(counter),counter.cb) else None
    return dict(available=all(v is not None for v in result.values()),processes=result,
                sample_sum_bytes=sum(v['working_set_bytes'] for v in result.values() if v),
                scope='simultaneous sample after actual transition; not a true global peak')


def trial_result(character,seed,label,records,outcome=None,failure=None,**extra):
    old=legacy.trial_result(character,seed,label,records,outcome,failure,**extra)
    return rescore_result(old,records)


def summarize(runs):
    result=legacy.summarize(runs)
    for key,value in result.items():
        label,character=key.split('/');rows=[r for r in runs if r['backend']==label and r['character']==character]
        value['metrics']={f'Pscore_first@{h}':dict(successes=sum(r['success'][str(h)] for r in rows),
            trials=len(rows),rate=sum(r['success'][str(h)] for r in rows)/len(rows),
            wilson95=legacy.wilson(sum(r['success'][str(h)] for r in rows),len(rows))) for h in (30,35,40)}
        value['chain15_counts']={str(h):sum(r['chain15_success'][str(h)] for r in rows) for h in (30,35,40)}
        scores=sorted(r['first_main_score'] for r in rows if r['first_main_score'] is not None)
        value.update(target_score=TARGETS[character],first_main_scores=scores,
            first_main_score_ratios=[s/TARGETS[character] for s in scores],
            below_score_distribution=[s for s in scores if s<TARGETS[character]],
            successful_below15=sum(r['success']['40'] and r['first_main_chain']<15 for r in rows),
            multistep_goal_trials=sum(r.get('multistep_goal',False) for r in rows))
        unfinished=sum(r['outcome']=='unfinished' for r in rows)
        value['unfinished']=unfinished
        value['success_rate_bounds_40']=[sum(r['success']['40'] for r in rows)/len(rows),
                                        (sum(r['success']['40'] for r in rows)+unfinished)/len(rows)]
    return result


def paired(runs,baseline,candidate,bootstrap=10000):
    import random
    result={}
    for character in TARGETS:
        a={r['seed']:r for r in runs if r['backend']==baseline and r['character']==character}
        b={r['seed']:r for r in runs if r['backend']==candidate and r['character']==character}
        if a.keys()!=b.keys():raise ValueError('paired seed sets differ')
        if not a:continue
        differences=[int(b[s]['success']['40'])-int(a[s]['success']['40']) for s in sorted(a)]
        gains=[s for s in sorted(a) if b[s]['success']['40'] and not a[s]['success']['40']]
        losses=[s for s in sorted(a) if a[s]['success']['40'] and not b[s]['success']['40']]
        rng=random.Random(0x540);n=len(a)
        samples=sorted(sum(rng.choices(differences,k=n))/n for _ in range(bootstrap))
        discord=len(gains)+len(losses)
        exact=min(1.0,2*sum(math.comb(discord,k) for k in range(min(len(gains),len(losses))+1))/2**discord) if discord else 1.0
        result[character]=dict(n=n,gain_seeds=gains,loss_seeds=losses,difference=sum(differences)/n,
            bootstrap95=[samples[int(.025*bootstrap)],samples[min(bootstrap-1,int(.975*bootstrap))]],mcnemar_exact_two_sided=exact,
            secondary_differences={str(h):sum(int(b[s]['success'][str(h)])-int(a[s]['success'][str(h)]) for s in a) for h in (30,35)},
            warning='development comparison; zero bootstrap interval does not prove equivalence')
    return result
