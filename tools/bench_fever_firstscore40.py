"""Score-first judge and B0/S0/H1 paired opening experiments; prototype colors."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.first40_benchmark import NativeEnvironment,normalize_step
from fever_battle.first40_provenance import fingerprints,sha
from fever_battle.firstscore40_backend import ScoreBackend,SETTINGS
from fever_battle.firstscore40_benchmark import SCHEMA,TARGETS,run_trial,rescore_result,summarize,paired
from tools.bench_fever_first40_deadline import prepare as prepare_reference


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def contract():
    return dict(schema=SCHEMA,targets=TARGETS,mainline_min_chain=10,horizon=40,secondary_horizons=[30,35],
        score_mode='normal',score_basis='executed first-mainline clear points; no previous fires/drop/all-clear bonus',
        visible=3,denominator='all started including dead/nomove/timeout/errors; unfinished retains bounds',
        color_model='prototype native splitmix4; local Steam scoring/physics unverified',
        first_below_score='absorbing failure',dead_overrides_score=True,second=False)


def gate(runs,complete):
    if not complete:return dict(pass_to_practical=False,disposition='hold_incomplete')
    lookup={(r['character'],r['seed'],r['backend']):r for r in runs}
    if not {'b0','s0','h1'}<={r['backend'] for r in runs}:return {'pass_to_practical':False,'disposition':'smoke_only'}
    comparisons=paired(runs,'s0','h1');b0=paired(runs,'b0','h1')
    gains=set(s for row in comparisons.values() for s in row['gain_seeds'])
    net=sum(len(row['gain_seeds'])-len(row['loss_seeds']) for row in comparisons.values())
    active=[r for r in runs if r['backend']=='h1' and r.get('multistep_goal')]
    active_seeds={r['seed'] for r in active}
    opportunity=len(active_seeds)>=4 and {r['character'] for r in active}==set(TARGETS)
    effect=net>=2 and len(gains)>=3 and all(row['difference']>=0 for row in comparisons.values()) and all(row['difference']>=0 for row in b0.values())
    secondary=all(delta>=-1 for row in comparisons.values() for delta in row['secondary_differences'].values())
    safe=True
    for c in TARGETS:
        for outcome in ('dead','nomove','timeout'):
            a=sum(r['character']==c and r['backend']=='s0' and r['outcome']==outcome for r in runs)
            b=sum(r['character']==c and r['backend']=='h1' and r['outcome']==outcome for r in runs)
            safe=safe and b<=a
    valid=not any(r['outcome']=='engine_error' for r in runs)
    passed=opportunity and effect and secondary and safe and valid
    return dict(pass_to_practical=passed,disposition='eligible_for_practical' if passed else ('hold_insufficient_opportunity' if not opportunity else 'not_adopted'),
                multistep_source_seeds=sorted(active_seeds),multistep_characters=sorted({r['character'] for r in active}),
                opportunity=opportunity,net_gain=net,gain_source_seeds=sorted(gains),effect=effect,
                secondary=secondary,safety=safe,valid=valid)


def rescore(args):
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report={};inputs={}
    for group in ('development24','additional40'):
        base=ROOT/'data/fever/baselines/2026-10-12-f40-deadline'/group
        saved=json.loads((base/'results.json').read_text());rows=defaultdict(list)
        for line in (base/'steps.jsonl').read_text().splitlines():
            row=json.loads(line)
            if 'links' in row:rows[row['character'],row['seed'],row['backend']].append(row)
        runs=[rescore_result(r,rows[r['character'],r['seed'],r['backend']]) for r in saved['runs']]
        report[group]=dict(runs=runs,summary=summarize(runs),paired=paired(runs,'b0','b1'))
        for name in ('results.json','steps.jsonl'):inputs[str(base/name)]=sha(base/name)
    expected=json.loads((ROOT/'data/fever/baselines/2026-10-12-firstscore40-plan/score_reanalysis.json').read_text())
    for g in report:
        for c in TARGETS:
            for b in ('b0','b1'):
                actual=report[g]['summary'][f'{b}/{c}']['metrics']
                assert [actual[f'Pscore_first@{h}']['successes'] for h in (30,35,40)]==[
                    expected['opening_groups'][g][c][b]['score_counts'][str(h)] for h in (30,35,40)]
    write(out/'results.json',dict(contract=contract(),complete=True,inputs=inputs,groups=report))
    print(json.dumps({'rescore_trials':sum(len(v['runs']) for v in report.values()),'complete':True}))


def prepare(args):
    args.baseline=ROOT/'data/fever/baselines/2026-10-12-f40-deadline/development24/steps.jsonl'
    out,manifest=prepare_reference(args)
    built=json.loads(args.planner_build.read_text())
    archive=args.planner_build.parent/'source-snapshot.zip'
    if sha(archive)!=built['source_snapshot_sha256']:raise ValueError('planner source archive mismatch')
    for path,digest in built['binaries'].items():
        if sha(path)!=digest:raise ValueError('planner binary changed')
    if str(args.planner.resolve()) not in built['binaries']:raise ValueError('planner not in its build manifest')
    for path,digest in built['source_sha256'].items():
        if Path(path).suffix in ('.cpp','.h','.cc') and sha(ROOT/path)!=digest:
            raise ValueError('compiled/header source changed since build: '+path)
    if sha(SETTINGS)!=built['research_settings_sha256']:raise ValueError('research settings changed since build')
    manifest.update(contract=contract(),experiment='S0 score firing and H1 retained tail plan',
        planner_build_manifest=built,planner_build_manifest_sha256=sha(args.planner_build),
        research_settings_sha256=sha(SETTINGS),research_settings=json.loads(SETTINGS.read_text()),
        planner_source_snapshot_sha256=sha(archive))
    manifest['settings']=dict(b0_width=250,b0_depth=8,b0_virtual_queues=6,b0_threads=6,
        research_threads=1,visible=3,margin=1,targets=TARGETS,first_main_threshold=10,horizon=40,
        time_budget='total choose watchdog; research 1000ms or practical 250ms; cooperatively bounded planner then B0',
        observation_input='public seven-field Observation only; no environment seed or future')
    manifest['binaries'].update(built['binaries'])
    (out/'planner-build.json').write_bytes(args.planner_build.read_bytes())
    (out/'planner-source-snapshot.zip').write_bytes(archive.read_bytes())
    (out/'research-settings.json').write_bytes(SETTINGS.read_bytes())
    spec=ROOT/'bin/firstscore40/preflight/experiment-spec.md'
    (out/'experiment-spec.md').write_bytes(spec.read_bytes())
    manifest['specification_sha256']=sha(spec)
    return out,manifest


def run(args):
    out,manifest=prepare(args)
    settings=json.loads(SETTINGS.read_text());seeds=args.seeds or settings['development_seeds']
    if len(set(seeds))!=len(seeds):raise ValueError('duplicate seeds')
    labels=args.backends;characters=list(TARGETS)
    if len(set(labels))!=len(labels):raise ValueError('duplicate backends')
    budget=250 if args.mode=='practical' else 1000
    started=time.perf_counter();global_end=started+args.wall_minutes*60
    manifest.update(seeds=seeds,characters=characters,backends=labels,expected_trials=len(seeds)*len(characters)*len(labels),
        choose_budget_ms=budget,global_wall_minutes=args.wall_minutes,
        candidate_order='rotate per seed and character; one trial at a time',seed_role='development',
        cpu_parallelism='research 1 or B0 6 sequential; no nested searches')
    write(out/'manifest.json',manifest);runs=[]
    with (out/'steps.jsonl').open('x',encoding='utf-8') as stream:
        def emit(row):
            stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');stream.flush()
        stop=False
        for ci,c in enumerate(characters):
            for si,s in enumerate(seeds):
                shift=(si+ci)%len(labels);order=labels[shift:]+labels[:shift]
                for label in order:
                    if time.perf_counter()>=global_end:stop=True;break
                    r=run_trial(c,s,label,lambda label=label:ScoreBackend(args.native,args.planner,args.config,label,budget,experiment_deadline=global_end),
                                lambda char,seed:NativeEnvironment(args.native,char,seed),emit)
                    runs.append(r)
                    write(out/'runs.json',runs)
                    print(json.dumps({k:r[k] for k in ('character','seed','backend','outcome','first_main_chain','first_main_score','success_move','multistep_goal')}),flush=True)
                if stop:break
            if stop:break
    manifest.update(source_unchanged=manifest['source_sha256']==fingerprints(),
                    binaries_unchanged=all(sha(path)==digest for path,digest in manifest['binaries'].items()),
                    settings_unchanged=sha(SETTINGS)==manifest['research_settings_sha256'])
    complete=len(runs)==manifest['expected_trials'] and not any(r['outcome']=='unfinished' for r in runs) and all(manifest[k] for k in ('source_unchanged','binaries_unchanged','settings_unchanged'))
    write(out/'manifest.json',manifest)
    comparisons={f'{a}->{b}':paired(runs,a,b) for a,b in (('b0','s0'),('s0','h1'),('b0','h1'))
                 if complete and {a,b}<=set(labels)}
    report=dict(contract=contract(),complete=complete,runs=runs,summary=summarize(runs),paired=comparisons,
                gate=gate(runs,complete),driver_wall_seconds=time.perf_counter()-started,manifest_sha256=sha(out/'manifest.json'),
                planned=manifest['expected_trials'],started=len(runs),not_started=manifest['expected_trials']-len(runs))
    write(out/'results.json',report);print(json.dumps({'complete':complete,'gate':report['gate']},ensure_ascii=False),flush=True)
    if not complete:raise SystemExit('Incomplete experiment; retained checkpoint, no adoption judgment.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['rescore','run'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--native',type=Path,default=ROOT/'bin/f40-diagnostics/reference/bin/commit-build/fever_battle.exe')
    p.add_argument('--build-manifest',type=Path,default=ROOT/'bin/f40-diagnostics/reference/bin/commit-build/build.json')
    p.add_argument('--planner',type=Path,default=ROOT/'bin/firstscore40/build-v4/firstscore40.exe')
    p.add_argument('--planner-build',type=Path,default=ROOT/'bin/firstscore40/build-v4/build.json')
    p.add_argument('--config',type=Path,default=ROOT/'config.json')
    p.add_argument('--mode',choices=['research','practical'],default='research')
    p.add_argument('--seeds',type=int,nargs='+');p.add_argument('--backends',nargs='+',choices=['b0','s0','h1'],default=['b0','s0','h1'])
    p.add_argument('--wall-minutes',type=float,default=90)
    args=p.parse_args();(rescore if args.command=='rescore' else run)(args)


if __name__=='__main__':main()
