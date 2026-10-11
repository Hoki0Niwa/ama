"""Replay observed development positions with B0/reference/off/on observers.

No environment seed or hidden queue is sent to a backend. Summary logs retain
every root count and dropped examples; --detail-focus also retains every
candidate feature tuple for the predeclared focus positions (gzip JSONL).
"""
import argparse
from collections import Counter
from copy import deepcopy
import gzip
import json
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.first40_benchmark import LegacyBackend,Observation,percentile
from fever_battle.first40_provenance import fingerprints,process_sample,sha,snapshot

FOCUS={('raffina',31001),('raffina',31002),('rafisol',31004),('rafisol',31020)}


def stable_reply(reply):
    return {k:v for k,v in reply.items() if k not in ('search_ms','research_diagnostics')}


def supply(character,start,end):
    if end<start:return None
    patterns=json.loads((ROOT/'data/fever/dropsets.json').read_text(encoding='utf-8'))['characters']
    pattern=next(c['pattern'] for c in patterns if c['id']==character)
    mass={'2':2,'L':3,'J':3,'4':4,'0':4}
    return sum(mass[pattern[i%16]] for i in range(start,end))


def inspect(trace,character):
    counts=Counter();lost_examples=[];layer_count=0;root_loss_trees=0;full_dropped15=0
    for search in trace['searches']:
        for virtual in search['virtual_searches']:
            counts['expansion_nodes']+=virtual['expansion_nodes']
            counts['placement_attempts']+=virtual['placement_attempts']
            counts['b0_evaluations']+=virtual['b0_evaluations']
            counts['diagnostic_extra_potential_calls']+=virtual['diagnostic_extra_potential_calls']
            initial={r['root'] for r in virtual['root_placements']}
            final=set();ever_lost=False
            for layer in virtual['layers']:
                layer_count+=1
                if not layer['conservation']:raise ValueError('heap accounting did not conserve candidates')
                final={r['root'] for r in layer['roots'] if r['root']>=0 and r['counts'].get('kept',0)>0}
                if layer['depth']>1 and final!=initial:ever_lost=True
                for root in layer['roots']:
                    for reason in ('width_rejected','width_evicted','tt_cut','chain_prune','dead','unsafe_margin','kept'):
                        counts[reason]+=root['counts'].get(reason,0)
                t=search['placed_total']+layer['depth']
                for example in layer['examples']:
                    g=example['geometry'];C=g['Rg']+g['popped']-g['Kg']
                    example['after_t']=t
                    example['mass_slack']={str(h):(C+supply(character,t,h)-60 if t<=h else None) for h in (30,35,40)}
                    if example['state'] in (1,2,3) and g['Lg']>=15:
                        counts['dropped15_examples']+=1
                        if len(lost_examples)<8:
                            lost_examples.append(dict(virtual=virtual['virtual_id'],depth=layer['depth'],**example))
                for row in layer['records']:
                    if row[4] in (1,2,3) and row[5]>=15:full_dropped15+=1
            root_loss_trees+=ever_lost
    return dict(counts=dict(counts),layers=layer_count,virtual_trees_with_root_loss=root_loss_trees,
        full_detail_dropped_geometry15=full_dropped15,examples=lost_examples,
        causal_conclusion='Dropped geometry is not proof of a legal first15 completion by move40.')


def select_positions(runs,steps):
    selected=[]
    for trial in runs:
        key=(trial['character'],trial['seed']);terminal=trial['placed_moves']
        if trial['first_main_chain'] in (13,14):offsets=(10,5,1,0)
        elif key in {('raffina',31004),('rafisol',31010)}:offsets=(5,1,0)
        else:continue
        for offset in offsets:
            move=terminal-offset
            if move>0:selected.append((steps[(*key,move)],trial['first_main_chain'],offset))
    return selected


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference-native',type=Path,required=True)
    p.add_argument('--diagnostic-native',type=Path,required=True)
    p.add_argument('--build-manifest',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--detail-focus',action='store_true')
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=json.loads(args.baseline.read_text(encoding='utf-8'))
    if not report['complete']:raise ValueError('reference benchmark must be complete')
    rows={}
    stepfile=args.baseline.parent/'steps.jsonl'
    for line in stepfile.read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if 'event' not in row:rows[(row['character'],row['seed'],row['move'])]=row
    selected=select_positions(report['runs'],rows)
    manifest=snapshot(out,[args.reference_native,args.diagnostic_native],args.build_manifest)
    manifest.update(inputs={str(p.resolve()):sha(p) for p in (args.baseline,stepfile)},
        scope='development observations only; all first13/14 failures plus two success controls',
        comparisons=['reference','diagnostics_off','diagnostics_on'],detail_focus=sorted(FOCUS),
        colors='prototype_splitmix4, not Steam',cpu_window='choose including Python/IPC/diagnostic JSON, excluding trace compression',
        expected_positions=len(selected))
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    engines={label:LegacyBackend(native,ROOT/'config.json',250,8) for label,native in
        [('reference',args.reference_native),('off',args.diagnostic_native),('on',args.diagnostic_native)]}
    native_ask=engines['on'].engine.native.ask
    context={}
    def observed_ask(request,**kwargs):
        request=deepcopy(request)
        if request.get('op')=='solo':
            assert len(request['request']['self']['queue'])==3
            assert 'seed' not in request and 'seed' not in request['request']
            request.update(research_diagnostics=True,research_placed_total=context['t'],research_detail_all=context['all'])
        return native_ask(request,**kwargs)
    engines['on'].engine.native.ask=observed_ask
    cases=[]
    try:
        with gzip.open(out/'diagnostics.jsonl.gz','wt',encoding='utf-8') as trace:
            for i,(row,first_chain,offset) in enumerate(selected):
                character,seed,move=row['character'],row['seed'],row['move']
                context.update(t=move-1,all=args.detail_focus and (character,seed) in FOCUS and offset in (5,1))
                obs=Observation(tuple(row['before']),tuple(row['queue']),character,move-1,move-1,row['options']['moves'],0)
                answers={};costs={}
                labels=['reference','off','on'];labels=labels[i%3:]+labels[:i%3]
                for label in labels:
                    engine=engines[label];engine.engine.normal_build_cache=None;engine.enemy=None
                    processes=engine.processes();before=process_sample(processes);start=time.perf_counter()
                    answers[label]=engine.choose(obs)
                    wall=(time.perf_counter()-start)*1000;after=process_sample(processes)
                    cpu={k:after[k]['cpu_seconds']-v['cpu_seconds'] if after[k]['cpu_seconds'] is not None and v['cpu_seconds'] is not None else None for k,v in before.items()}
                    costs[label]=dict(wall_ms=wall,cpu_seconds=cpu,process_memory=after)
                if stable_reply(answers['reference'])!=stable_reply(answers['off']) or stable_reply(answers['reference'])!=stable_reply(answers['on']):
                    raise ValueError(f'diagnostic changed B0 reply: {character}/{seed}/{move}')
                selected_placement={k:answers['reference'][k] for k in ('x','r','next_field','next_chain')}
                if (selected_placement['x'],selected_placement['r'],selected_placement['next_field'],selected_placement['next_chain'])!=(row['x'],row['r'],row['after'],row['chain']):
                    raise ValueError('reference replay placement differs from committed trial')
                diag=answers['on'].get('research_diagnostics')
                if diag is None:raise ValueError('diagnostic reply missing')
                analysis=inspect(diag,character)
                case=dict(character=character,seed=seed,move=move,terminal_first_chain=first_chain,offset_before_terminal=offset,
                    placement=selected_placement,costs=costs,detail_all=context['all'],analysis=analysis)
                trace.write(json.dumps(dict(case=case,diagnostics=diag),separators=(',',':'))+'\n');trace.flush()
                cases.append(case)
                print(json.dumps({k:case[k] for k in ('character','seed','move','detail_all')},ensure_ascii=False),flush=True)
    finally:
        for engine in engines.values():engine.close()
    times={label:[r['costs'][label]['wall_ms'] for r in cases] for label in engines}
    counts=Counter()
    for case in cases:counts.update(case['analysis']['counts'])
    summary=dict(positions=len(cases),all_replies_and_actual_placements_equal=True,
        counts=dict(counts),positions_with_root_loss=sum(r['analysis']['virtual_trees_with_root_loss']>0 for r in cases),
        positions_with_dropped_geometry15=sum(r['analysis']['counts'].get('dropped15_examples',0)>0 for r in cases),
        full_detail_positions=sum(r['detail_all'] for r in cases),
        cost={label:dict(mean_ms=statistics.mean(v),p95_ms=percentile(v,.95),max_ms=max(v)) for label,v in times.items()},
        conclusion='Structural loss and geometric alternatives can be observed; causal loss of a legal first15@40 is unproven.')
    manifest.update(source_unchanged=manifest['source_sha256']==fingerprints(),
        binaries_unchanged=all(sha(p)==v for p,v in manifest['binaries'].items()),
        diagnostic_trace_sha256=sha(out/'diagnostics.jsonl.gz'))
    if not manifest['source_unchanged'] or not manifest['binaries_unchanged']:raise ValueError('experiment inputs changed')
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
