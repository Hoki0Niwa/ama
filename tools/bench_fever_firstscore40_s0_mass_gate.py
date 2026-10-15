"""Frozen three-arm S0G experiment: preflight, replay, fixed, smoke, run."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import itertools
import json
from pathlib import Path
import random
import shutil
import statistics
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import NativeEnvironment, Observation
from fever_battle.first40_provenance import fingerprints, process_sample, sha
from fever_battle.firstscore40_backend import ScoreBackend, SETTINGS as ACTOR_SETTINGS
from fever_battle.firstscore40_s0_mass_gate import MassGatePlanner, MassGatedScoreBackend, mass_gate
from fever_battle.firstscore40_benchmark import TARGETS, paired, summarize
from fever_battle.worker import JsonProcess
from tools import confirm_fever_firstscore40_s0 as old
from tools.bench_fever_first40_deadline import prepare as prepare_reference
from tools.bench_fever_firstscore40 import contract

SETTINGS = ROOT/'data/fever/research/firstscore40_s0_mass_gate_v1.json'
PLAN = ROOT/'doc/contracts/FIRSTSCORE40_S0_MASS_GATE.md'
START = ROOT/'bin/s0-mass-gate/20261013/start/preflight.json'
S0C = ROOT/'data/fever/baselines/2026-10-13-firstscore40-s0-confirm'
ARMS = ('b0', 's0', 's0g')
ORDERS = tuple(itertools.permutations(ARMS))
write, load, fresh, read_rows = old.write, old.load, old.fresh, old.read_rows


def settings():
    s = load(SETTINGS)
    if (s['targets'] != TARGETS or s['backends'] != list(ARMS) or
            (s['choose_budget_ms'], s['planner_budget_ms'], s['mass_threshold']) != (250,25,40) or
            (s['confirmation_seed_start'],s['confirmation_seed_count'],s['expected_trials']) != (62001,64,384)):
        raise ValueError('S0G contract changed')
    return s


def seeds(s):
    return list(range(s['confirmation_seed_start'],s['confirmation_seed_start']+s['confirmation_seed_count']))


def preflight(args):
    s = settings()
    old.check_frozen()
    args.baseline = S0C/'confirmation/steps.jsonl'
    args.mode = 'practical'
    out, m = prepare_reference(args)
    built = load(args.planner_build)
    archive = args.planner_build.parent/'source-snapshot.zip'
    if sha(archive) != built['source_snapshot_sha256']: raise ValueError('planner archive mismatch')
    if str(args.planner.resolve()) not in built['binaries']: raise ValueError('planner/build mismatch')
    for p,h in built['binaries'].items():
        if sha(p) != h: raise ValueError('planner binary mismatch')
    with zipfile.ZipFile(archive) as z:
        for name,h in built['source_sha256'].items():
            if Path(name).suffix not in ('.cpp','.h','.cc'): continue
            raw = z.read(name)
            if hashlib.sha256(raw).hexdigest() != h: raise ValueError('planner build source archive mismatch')
            if (ROOT/name).read_bytes().replace(b'\r\n',b'\n') != raw.replace(b'\r\n',b'\n'):
                raise ValueError('frozen planner source changed: '+name)
    if sha(ACTOR_SETTINGS) != built['research_settings_sha256']: raise ValueError('actor settings changed')
    for source,dest in ((PLAN,'experiment-spec.md'),(SETTINGS,'research-settings.json'),
                        (ACTOR_SETTINGS,'actor-settings.json'),(START,'start-preflight.json'),
                        (args.planner_build,'planner-build.json'),(archive,'planner-source-snapshot.zip')):
        shutil.copyfile(source,out/dest)
    with zipfile.ZipFile(out/'source-snapshot.zip','a',zipfile.ZIP_DEFLATED) as z:
        for p in (PLAN,SETTINGS,ACTOR_SETTINGS): z.write(p,p.relative_to(ROOT).as_posix())
    scan = old.inventory_seeds(seeds(s),out)
    write(out/'seed-inventory.json',scan)
    if scan['matches']: raise ValueError('new seed already recorded')
    input_paths = [S0C/'confirmation/steps.jsonl',S0C/'confirmation/runs.json',
                   old.OLD/'research-v1/steps.jsonl',ROOT/'data/fever/baselines/2026-10-13-firstscore40-s0-next-plan/evidence.json']
    m.update(schema='ama.firstscore40.s0_mass_gate.manifest.v1', experiment='S0G public mass gate at 250ms',
             contract=contract(), settings=s, settings_sha256=sha(SETTINGS), actor_settings_sha256=sha(ACTOR_SETTINGS),
             specification_sha256=sha(PLAN), source_snapshot_sha256=sha(out/'source-snapshot.zip'),
             seeds=seeds(s), characters=s['characters'],backends=list(ARMS),expected_trials=384,
             seed_role=s['seed_role'],planner_build_manifest=built,planner_build_manifest_sha256=sha(args.planner_build),
             planner_source_archive_sha256=sha(archive),
             input_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in input_paths},
             ordering='ascending seed; alternating character order; six arm permutations cycling per seed; sequential',
             solver_input='seven public Observation fields only; no seed, trial ID or hidden colors',
             start_research_head=load(START)['research']['head'])
    m['binaries'].update(built['binaries'])
    write(out/'manifest.json',m)
    print(json.dumps(dict(preflight='ok',seed_scan_files=scan['scanned'],expected_trials=384)),flush=True)


def verify(out):
    m = load(out/'manifest.json')
    if m['experiment'] != 'S0G public mass gate at 250ms': raise ValueError('wrong experiment')
    if m['source_sha256'] != fingerprints(): raise ValueError('experiment sources changed')
    for path,key in ((SETTINGS,'settings_sha256'),(ACTOR_SETTINGS,'actor_settings_sha256'),(PLAN,'specification_sha256')):
        if sha(path) != m[key]: raise ValueError('experiment specification/settings changed')
    for p,h in m['binaries'].items():
        if sha(p) != h: raise ValueError('experiment binary changed')
    for p,h in m['input_sha256'].items():
        if sha(ROOT/p) != h: raise ValueError('saved input changed')
    return m


def backend(args,label,end=None):
    if label == 's0g':
        return MassGatedScoreBackend(args.native,args.planner,args.config,250,25,end)
    return ScoreBackend(args.native,args.planner,args.config,label,250,25,end)


def replay_populations():
    for row in read_rows(S0C/'confirmation/steps.jsonl'):
        if row['backend'] == 's0':
            yield 's0c',row,Observation(**dict(row['observation'],field=tuple(row['observation']['field']),visible=tuple(row['observation']['visible'])))
    for row,obs in old.public_rows(read_rows(old.OLD/'research-v1/steps.jsonl'),'s0'):
        yield 's40',row,obs


def replay(args):
    verify(args.output)
    out = fresh(args.output/'replay')
    counts = defaultdict(Counter); times = defaultdict(list); issues = []
    with JsonProcess([args.planner],cwd=ROOT) as plain, JsonProcess([args.planner],cwd=ROOT) as delegated, (out/'replies.jsonl').open('x',encoding='utf-8') as stream:
        guarded = MassGatePlanner(delegated)
        for index,(scope,row,obs) in enumerate(replay_populations()):
            responses = {}
            request = old.probe_request(obs)
            for label,process in ((('s0',plain),('s0g',guarded)) if index%2==0 else (('s0g',guarded),('s0',plain))):
                begin = time.perf_counter();reply = process.ask(request,timeout=1)
                responses[label] = dict(reply=reply,elapsed_ms=(time.perf_counter()-begin)*1000)
            original = row['research_planner']; ref = responses['s0']['reply']; candidate = responses['s0g']['reply']
            guard = candidate['mass_guard']; cc = counts[scope]
            cc['observations'] += 1;cc['skipped'] += guard['skip'];cc['delegated'] += not guard['skip']
            cc['old_F'] += original.get('decision') is not None
            keys = ('decision','first_main_score','first_main_chain')
            reference_same = all(ref.get(k)==original.get(k) for k in keys)
            candidate_same = all(candidate.get(k)==original.get(k) for k in keys)
            ident = dict(scope=scope,character=row['character'],seed=row['seed'],move=row.get('move',row.get('attempted_move')))
            if not guard['gate_checked']: issues.append(dict(**ident,reason='guard_did_not_validate_saved_input'))
            if guard['skip'] and original.get('decision') is not None: issues.append(dict(**ident,reason='skipped_saved_F'))
            if ref['score_probe_complete'] and not reference_same: issues.append(dict(**ident,reason='reference_policy_changed'))
            if candidate.get('score_probe_complete') and not candidate_same: issues.append(dict(**ident,reason='delegated_policy_changed'))
            if original.get('decision') and (not ref['score_probe_complete'] or not candidate.get('score_probe_complete') or not candidate_same):
                issues.append(dict(**ident,reason='lost_saved_F'))
            cc['reference_complete'] += ref['score_probe_complete'];cc['gated_complete'] += candidate.get('score_probe_complete') is True
            cc['incomplete_reference'] += not ref['score_probe_complete']
            cc['incomplete_gated'] += not guard['skip'] and not candidate.get('score_probe_complete')
            for label,item in responses.items():
                times[scope+'/'+label].append(item['elapsed_ms'])
                if guard['skip']:times[scope+'/'+label+'/skippable'].append(item['elapsed_ms'])
            stream.write(json.dumps(dict(**ident,observation=asdict(obs),responses=responses,reference_policy_equal=reference_same,candidate_policy_equal=candidate_same),ensure_ascii=False,separators=(',',':'))+'\n');stream.flush()
            if (index+1)%500==0:print('replay '+str(index+1),flush=True)
    reduction = all(statistics.mean(times[s+'/s0g/skippable']) < statistics.mean(times[s+'/s0/skippable']) for s in counts)
    ready = not issues and (counts['s0c']['observations'],counts['s0c']['skipped'],counts['s0c']['old_F'],counts['s40']['observations'],counts['s40']['old_F']) == (4316,1647,183,1095,30)
    result = dict(ready=ready,counts={k:dict(v) for k,v in counts.items()},issues=issues,
                  costs={k:old.cost(v) for k,v in times.items()},fixed_probe_cost_reduced=reduction,new_opening_trials=0)
    write(out/'results.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if not ready:raise SystemExit('Replay validation failed; stop before new seeds.')


def fixed(args):
    verify(args.output)
    if not load(args.output/'replay/results.json')['ready']:raise ValueError('replay not ready')
    out = fresh(args.output/'fixed')
    cases = [r for r in read_rows(S0C/'confirmation/steps.jsonl') if r.get('event')=='failure' and r['backend']=='s0']
    if len(cases)!=4:raise ValueError('fixed population changed')
    records=[];issues=[]
    with (out/'choices.jsonl').open('x',encoding='utf-8') as stream:
        for case_index,row in enumerate(cases):
            o=row['observation'];obs=Observation(**dict(o,field=tuple(o['field']),visible=tuple(o['visible'])))
            for repetition in range(20):
                decisions={};requests={}
                for label in ORDERS[(case_index*20+repetition)%6]:
                    init=time.perf_counter();actor=backend(args,label);init_ms=(time.perf_counter()-init)*1000
                    native_ask=actor.engine.native.ask;native_requests=[]
                    def record(request,*pos,**kw):
                        native_requests.append(deepcopy(request));return native_ask(request,*pos,**kw)
                    actor.engine.native.ask=record
                    before=process_sample(actor.processes());begin=time.perf_counter();decision=None;error=None
                    try:decision=actor.choose(obs)
                    except TimeoutError as exc:error=dict(type=type(exc).__name__,message=str(exc))
                    except Exception as exc:
                        error=dict(type=type(exc).__name__,message=str(exc));issues.append(dict(character=row['character'],seed=row['seed'],repetition=repetition,backend=label,error=error))
                    elapsed=(time.perf_counter()-begin)*1000;after=process_sample(actor.processes())
                    cpu={k:(after[k]['cpu_seconds']-before[k]['cpu_seconds'] if after[k]['cpu_seconds'] is not None and before[k]['cpu_seconds'] is not None else None) for k in before}
                    probe=deepcopy(actor.last_planner);actor.close()
                    item=dict(character=row['character'],seed=row['seed'],attempted_move=row['attempted_move'],backend=label,repetition=repetition,
                              observation=asdict(obs),initialization_ms=init_ms,elapsed_ms=elapsed,decision=decision,error=error,probe=probe,
                              native_request_sha256=hashlib.sha256(json.dumps(native_requests,sort_keys=True).encode()).hexdigest(),native_requests=native_requests,cpu_seconds=cpu)
                    records.append(item);stream.write(json.dumps(item,ensure_ascii=False,separators=(',',':'))+'\n');stream.flush()
                    if decision is not None:decisions[label]={k:decision.get(k) for k in ('x','r','next_field','next_chain')}
                    requests[label]=native_requests
                if len({json.dumps(v,sort_keys=True) for v in decisions.values()})>1:issues.append(dict(character=row['character'],seed=row['seed'],repetition=repetition,reason='completed_fixed_actions_differ'))
                # Timeout may stop a request sequence early; common requests must still agree.
                for a,b in itertools.combinations(ARMS,2):
                    n=min(len(requests[a]),len(requests[b]))
                    if requests[a][:n]!=requests[b][:n]:issues.append(dict(character=row['character'],seed=row['seed'],repetition=repetition,reason='B0_requests_changed',arms=[a,b]))
            print(json.dumps(dict(fixed_case=[row['character'],row['seed']],repetitions=20)),flush=True)
    summary={}
    for label in ARMS:
        rr=[r for r in records if r['backend']==label]
        summary[label]=dict(cost=old.cost([r['elapsed_ms'] for r in rr]),timeouts=sum(r['error'] is not None and r['error']['type']=='TimeoutError' for r in rr),
                            initialization_cost=old.cost([r['initialization_ms'] for r in rr]))
    result=dict(ready=len(records)==240 and not issues,choices=len(records),summary=summary,issues=issues,
                new_opening_trials=0,scope='Repeated fixed public observations; not extra success-rate samples')
    write(out/'results.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
    if not result['ready']:raise SystemExit('Fixed validation failed; stop before new seeds.')


def lookup_runs(runs,expected):
    keys=[(r['character'],r['seed'],r['backend']) for r in runs]
    required={(c,s,b) for c in TARGETS for s in expected for b in ARMS}
    if len(keys)!=len(set(keys)) or set(keys)!=required:raise ValueError('incomplete or duplicate triplets')
    return dict(zip(keys,runs))


def project(runs,baseline,candidate):
    return [dict(r,backend='b0' if r['backend']==baseline else 's0') for r in runs if r['backend'] in (baseline,candidate)]


def full_cost(runs):
    result={}
    for c in TARGETS:
        for b in ARMS:
            rr=[r for r in runs if r['character']==c and r['backend']==b]
            times=[v for r in rr for v in r['timings_ms']]+[r['failed_think_ms'] for r in rr if r.get('failed_think_ms') is not None]
            cpu=[r.get('total_cpu_seconds') for r in rr]
            value=old.cost(times)
            value['cpu_seconds']=sum(cpu) if cpu and all(v is not None for v in cpu) else None
            value['cpu_per_decision']=value['cpu_seconds']/len(times) if value['cpu_seconds'] is not None and times else None
            value['response_over_250ms']=sum(v>250 for r in rr for v in r['timings_ms'])
            result[c+'/'+b]=value
    return result


def clustered_timeout(runs,baseline,candidate,expected):
    index=lookup_runs(runs,expected)
    q=[sum(int(index[c,s,candidate]['outcome']=='timeout')-int(index[c,s,baseline]['outcome']=='timeout') for c in TARGETS) for s in expected]
    rng=random.Random(0x540); samples=sorted(sum(rng.choices(q,k=len(q)))/(2*len(q)) for _ in range(10000))
    return dict(difference=sum(q)/(2*len(q)),bootstrap95=[samples[250],samples[9750]],extra_trials=sum(q),
                warning='Point-estimate tolerance is not a statistical noninferiority proof')


def gate(runs,expected,ready,audits,provenance=True,fixed_reduction=True):
    invalid=dict(disposition='hold_invalid_or_incomplete',eligible=False)
    if not ready or not provenance or any(r['outcome'] in ('engine_error','unfinished') for r in runs):return invalid
    try:index=lookup_runs(runs,expected)
    except ValueError:return invalid
    required=set(index); audit_keys=[(a.get('character'),a.get('seed'),a.get('backend')) for a in audits]
    if len(audit_keys)!=len(set(audit_keys)) or set(audit_keys)!=required:return invalid
    if any(a['issues'] for a in audits):return dict(invalid,reason='proof_or_mass_guard_invalid')
    costs=full_cost(runs)
    if not all(v['cpu_per_decision'] is not None and v['p95_ms'] is not None for v in costs.values()):return dict(invalid,reason='cost_unavailable')
    main=old.clustered(project(runs,'b0','s0g'),expected)
    retain=old.clustered(project(runs,'s0','s0g'),expected)
    repeat=old.clustered(project(runs,'b0','s0'),expected)
    pairs=paired(runs,'b0','s0g')
    effect=main['difference']>=.05 and main['net_gain']>=7 and all(p['difference']>=0 for p in pairs.values())
    evidence=main['sign_flip_one_sided']<=.05
    retention=retain['difference']>=-.02
    early=all(sum(p['secondary_differences'][str(h)] for p in pairs.values())>=0 for h in (30,35))
    counts={b:Counter(r['outcome'] for r in runs if r['backend']==b) for b in ARMS}
    n=2*len(expected)
    timeouts={b:clustered_timeout(runs,b,'s0g',expected) for b in ('b0','s0')}
    safety=all(v['difference']<=.02 for v in timeouts.values()) and (
        counts['s0g']['dead']+counts['s0g']['nomove']<=max(counts[b]['dead']+counts[b]['nomove'] for b in ('b0','s0')))
    cost_ok=all(costs[c+'/s0g']['p95_ms']<=costs[c+'/b0']['p95_ms']+25 and
                costs[c+'/s0g']['cpu_per_decision']<=costs[c+'/b0']['cpu_per_decision']*1.15 for c in TARGETS)
    cost_ok=cost_ok and all(v['response_over_250ms']==0 for v in costs.values()) and fixed_reduction
    passed=effect and evidence and retention and early and safety and cost_ok
    return dict(disposition='eligible_for_next_research_baseline' if passed else 'hold_current_s0g',eligible=passed,
                effect=effect,evidence=evidence,retention=retention,early=early,safety=safety,cost=cost_ok,
                proof_deadlines=True,paired=pairs,clustered=dict(s0g_vs_b0=main,s0g_vs_s0=retain,s0_vs_b0=repeat),
                timeout_differences=timeouts,outcomes={b:dict(v) for b,v in counts.items()},costs=costs,
                research_incumbent='S0 remains a candidate; S0G hold does not invalidate S0C evidence',trials_per_arm=n)


def audit_trial(records,result,native):
    # The frozen proof auditor treats only label s0; map the label, not its inputs/steps.
    audit=old.audit_fire(records,dict(result,backend='s0' if result['backend']=='s0g' else result['backend']),native)
    for row in records:
        if result['backend']!='s0g':continue
        reply=row.get('research_planner',{});guard=reply.get('mass_guard')
        if guard is None:
            audit['issues'].append(dict(reason='missing_mass_guard',move=row.get('move',row.get('attempted_move'))));continue
        expected=mass_gate(row['observation'])
        if any(guard.get(k)!=v for k,v in expected.items()):audit['issues'].append(dict(reason='mass_guard_changed'))
        if guard['skip'] and (reply.get('decision') is not None or reply.get('probe_invoked') or reply.get('score_probe_complete') is True):
            audit['issues'].append(dict(reason='invalid_skipped_probe'))
    return audit


def same_observation_actions(records):
    groups={b:{(r['character'],r['seed'],r['move']):r for r in records if r['backend']==b and 'links' in r} for b in ('s0','s0g')}
    issues=[];same=0
    for key,row in groups['s0g'].items():
        ref=groups['s0'].get(key)
        if ref is not None and row['observation']==ref['observation']:
            same+=1
            if not old.compare_steps(row,ref):issues.append(dict(character=key[0],seed=key[1],move=key[2],reason='same_observation_different_action'))
    return dict(matched_observation_actions=same,issues=issues)


def execute(args,smoke=False):
    m=verify(args.output)
    replay_result=load(args.output/'replay/results.json')
    if not replay_result['ready'] or not load(args.output/'fixed/results.json')['ready'] or not load(args.output/'test-results/verification.json')['passed']:
        raise ValueError('required checks incomplete')
    if not smoke and not load(args.output/'smoke/results.json')['ready']:raise ValueError('smoke validation incomplete')
    if not smoke:
        scan=old.inventory_seeds(m['seeds'],args.output);write(args.output/'seed-inventory-before-run.json',scan)
        if scan['matches']:raise ValueError('independent seed already consumed')
    out=fresh(args.output/('smoke' if smoke else 'confirmation'))
    pairs_=[tuple(v) for v in m['settings']['smoke_pairs']] if smoke else [
        (c,s) for i,s in enumerate(m['seeds']) for c in (list(TARGETS) if i%2==0 else list(reversed(TARGETS)))]
    wall=time.perf_counter();end=wall+m['settings']['wall_cap_minutes']*60
    runs=[];records=[];stopped=False
    with (out/'steps.jsonl').open('x',encoding='utf-8') as stream:
        def emit(row):
            stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');stream.flush();records.append(row)
        for i,(c,s) in enumerate(pairs_):
            order=ORDERS[(i if smoke else s-62001)%6]
            for label in order:
                if time.perf_counter()>=end:stopped=True;break
                result,trial_rows=old.recorded_trial(c,s,label,lambda label=label:backend(args,label,end),
                    lambda character,seed:NativeEnvironment(args.native,character,seed),emit)
                runs.append(result);write(out/'runs.json',runs)
                print(json.dumps({k:result[k] for k in ('character','seed','backend','outcome','first_main_chain','first_main_score','success_move')}),flush=True)
                if result['outcome']=='engine_error':stopped=True;break
            if stopped:break
    measured_wall=time.perf_counter()-wall
    audits=[];invalid=[]
    with JsonProcess([args.native],cwd=ROOT) as native:
        for r in runs:
            subset=[v for v in records if (v['character'],v['seed'],v['backend'])==(r['character'],r['seed'],r['backend'])]
            try:a=audit_trial(subset,r,native)
            except ValueError as exc:
                invalid.append(dict(character=r['character'],seed=r['seed'],backend=r['backend'],error=str(exc)))
                a=dict(issues=[dict(reason='invalid_proof_or_guard')],reference_transitions=0,adopted_proof=False,first_proof_deadline=None)
            audits.append(dict(character=r['character'],seed=r['seed'],backend=r['backend'],**a))
    write(out/'fire-audit.json',audits)
    try:verify(args.output);provenance=True
    except ValueError:provenance=False
    action_audit=same_observation_actions(records);write(out/'same-observation-actions.json',action_audit)
    expected=24 if smoke else 384
    complete=len(runs)==expected and not any(r['outcome']=='unfinished' for r in runs)
    result=dict(complete=complete,planned=expected,started=len(runs),not_started=expected-len(runs),
                runs=runs,summary=summarize(runs),costs=full_cost(runs),provenance_unchanged=provenance,
                invalid_proofs=invalid,driver_wall_seconds=measured_wall,validation_wall_seconds=time.perf_counter()-wall-measured_wall,
                action_audit=action_audit,fire_audit_sha256=sha(out/'fire-audit.json'))
    if smoke:
        result['ready']=complete and provenance and not invalid and not action_audit['issues'] and all(not a['issues'] for a in audits) and not any(r['outcome']=='engine_error' for r in runs)
    else:
        result['gate']=gate(runs,m['seeds'],complete,audits,provenance and not invalid and not action_audit['issues'],replay_result['fixed_probe_cost_reduced'])
        if complete:result['paired']={a+'_vs_'+b:paired(runs,b,a) for a,b in (('s0g','b0'),('s0g','s0'),('s0','b0'))}
    write(out/'results.json',result)
    print(json.dumps(dict(complete=complete,ready=result.get('ready'),gate=result.get('gate')),ensure_ascii=False),flush=True)
    if smoke and not result['ready']:raise SystemExit('Smoke validation failed; stop before new seeds.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['preflight','replay','fixed','smoke','run'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native',type=Path,default=ROOT/'bin/f40-diagnostics/reference/bin/commit-build/fever_battle.exe')
    parser.add_argument('--build-manifest',type=Path,default=ROOT/'bin/f40-diagnostics/reference/bin/commit-build/build.json')
    parser.add_argument('--planner',type=Path,default=ROOT/'bin/firstscore40/build-v4/firstscore40.exe')
    parser.add_argument('--planner-build',type=Path,default=ROOT/'bin/firstscore40/build-v4/build.json')
    parser.add_argument('--config',type=Path,default=ROOT/'config.json')
    args=parser.parse_args();args.output=args.output.resolve()
    if args.command=='preflight':preflight(args)
    elif args.command=='replay':replay(args)
    elif args.command=='fixed':fixed(args)
    else:execute(args,smoke=args.command=='smoke')


if __name__=='__main__':main()
