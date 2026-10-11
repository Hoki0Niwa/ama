"""Offline sensitivity probes; no production engine/config changes or game input."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.model import Scoring
from fever_battle import tactics


def rows(value):
    return value.split('/') if isinstance(value, str) else value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--output',type=Path,default=ROOT/'data/fever/baselines/2026-10-11-battle-symptoms-deep.json')
    args=parser.parse_args()
    binary = args.native
    engine = ModeBattleEngine(binary, ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    report = dict(native_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  status='offline_synthetic_sensitivity_and_saved_trace_not_live_battle',
                  capacity=[], capacity_counterfactual=[], defense=[], safety_filter=[], horizon=[], pace=[], scoring={})
    try:
        traces = json.loads((ROOT/'data/fever/baselines/2026-10-11-second-final.json').read_text(encoding='utf-8'))
        for run in traces['runs']:
            for item in run['trace']:
                if not item['fire']:
                    continue
                field = item['before']
                count = sum(c != '.' for row in field for c in row)
                cells = {'2':2,'L':3,'J':3,'4':4,'0':4}[item['piece'][0]]
                placements = engine.native.ask(dict(op='placements', field=field, piece=item['piece']))['placements']
                safe = [p for p in placements if not p['dead'] and not p['links']
                        and sum(c != '.' for row in rows(p['field']) for c in row) >= count+cells
                        and all(sum(row[x] != '.' for row in rows(p['field'])) <= h
                                for x,h in ((1,12),(4,12),(2,10),(3,10)))]
                report['capacity'].append(dict(character=run['character'],seed=run['seed'],move=item['move'],
                    field=field,piece=item['piece'],count=count,cells=cells,total_threshold=count+cells>=68,
                    safe_nonclear_count=len(safe),current_capacity=count+cells>=68 or any(sum(row[x]!='.' for row in field)>11 for x in (2,3)) or not safe,
                    actual_chain=item['links'],safe_moves=[dict(x=p['x'],r=p['r']) for p in safe]))
                if item['links'] >= 3 and safe:
                    queue=[r['piece'] for r in run['trace'] if item['move']<=r['move']<item['move']+3]
                    options=dict(rule='fever',solo=True,character=run['character'],dropset_index=item['move'],
                        self=dict(field=field,queue=queue),include_next=True,plain_pairs=True,special_moves=True,
                        beam_width=250,beam_depth=8,build_chain=14,margin=1,construction_scoring=True,
                        rebuild=True,preserve_build=True,panic_count=0,panic_step=0,patience=0)
                    results=[]
                    for trigger in (1,14):
                        r=engine.solo.ask({**options,'trigger':trigger,'panic_chain':trigger})
                        t=engine.native.ask(dict(op='transition',field=field,piece=item['piece'],x=r['x'],r=r['r']))
                        results.append(dict(trigger=trigger,reply=r,transition=t))
                    extensions=[]
                    for p in safe:
                        if len(queue)<2: continue
                        q=queue[1:]
                        r=engine.solo.ask({**options,'dropset_index':item['move']+1,'self':dict(field=p['field'],queue=q),
                            'trigger':1,'panic_chain':1})
                        extensions.append(dict(move=dict(x=p['x'],r=p['r']),field=p['field'],visible_fire=r))
                    report['capacity_counterfactual'].append(dict(character=run['character'],seed=run['seed'],
                        move=item['move'],queue=queue,field=field,results=results,extensions=extensions))
        saved = json.loads((ROOT/'data/fever/baselines/2026-10-11-normal-defense-investigation.json').read_text(encoding='utf-8'))
        base = next(p['request'] for p in saved['probes'] if p['name']=='packet' and not p['fever'] and p['pending']==90)
        for pending in (20,90,160,300):
            for gauge in (0,5,6):
                for avoid in (False,True):
                    req = deepcopy(base)
                    req.update(confirmed=pending,gauge=gauge,avoid_own_fever=avoid,max_nodes=3000,width=12,budget_ms=0)
                    reply = engine.native.ask(req)
                    c=reply['choice']
                    alternatives=[p for p in reply['candidates'] if p['survives'] and p['defense_commitment']]
                    report['defense'].append(dict(pending=pending,gauge=gauge,avoid_entry=avoid,request=req,
                        choice=c,completed_depth=reply['completed_depth'],deeper_pass_skipped=reply['deeper_pass_skipped'],
                        secured_alternatives=len(alternatives),chosen_unsecured_with_alternative=not c['defense_commitment'] and bool(alternatives)))
        # Same request with only margin changed: does physical safety pruning hide a secured response?
        for pace in (42,120,240):
            req=deepcopy(base)
            req.update(queue=['2:GB','2:YR','2:GB'],confirmed=0,unconfirmed=0,pace_frames=pace,budget_ms=0,
                enemy_events=[dict(type='link',frame=350,points=10800),dict(type='end',frame=400)])
            r=engine.native.ask(req)
            report['pace'].append(dict(pace=pace,request=req,result=r))
        for pending in (90,160,300):
            for margin in (0,1,2):
                req=deepcopy(base); req.update(confirmed=pending,margin=margin,budget_ms=0,max_nodes=3000)
                r=engine.native.ask(req)
                report['safety_filter'].append(dict(pending=pending,margin=margin,choice=r['choice'],
                    root_candidates=len(r['candidates']),completed_depth=r['completed_depth']))
        links=[dict(groups=[4],colors=1)]*7
        scoring=Scoring()
        for character in scoring.data['characters']:
            report['scoring'][character]={m:sum(scoring.chain(character,links,m)) for m in ('normal','fever')}
        second=json.loads((ROOT/'data/fever/baselines/2026-10-11-second-fire-timing-investigation.json').read_text(encoding='utf-8'))
        for sample in second['probes']:
            for timeline in ('large_tail_now','large_tail_late'):
                events=next(v['events'] for v in sample['variants'] if v['name']==timeline)
                for nodes in (300,3000,20000):
                    policy=deepcopy(engine.policy['normal_tactics'])
                    policy.update(max_nodes=nodes,width=12,budget_ms=0)
                    decision=tactics.evaluate(engine.native,engine.scoring,sample['own'],120,1,policy,
                        enemy_events=events,enemy=sample['enemy'],builder=(sample['build']['x'],sample['build']['r']),
                        builder_fire=sample['build']['fire'] and sample['build'].get('fire_moves',1)==1,
                        fever=dict(enemy_fever=True,their_end=0,enemy_reply_nuisance=428),enemy_hold=486)
                    report['horizon'].append(dict(ai=sample['ai'],pair=sample['pair'],timeline=timeline,
                        events=events,nodes=nodes,decision_status=decision.status,result=decision.forecast))
    finally:
        engine.close()
    out=args.output
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('capacity cases',len(report['capacity']))
    print('capacity with safe nonclear',[(p['character'],p['seed'],p['move'],p['count'],p['actual_chain'],p['safe_nonclear_count']) for p in report['capacity'] if p['safe_nonclear_count']])
    print('unsecured with secured alternative',[(p['pending'],p['gauge'],p['avoid_entry']) for p in report['defense'] if p['chosen_unsecured_with_alternative']])
    print('defense depth',sorted(set(p['completed_depth'] for p in report['defense'])))
    print('margin',[(p['pending'],p['margin'],p['choice']['chain'],p['choice']['defense_commitment'],p['root_candidates']) for p in report['safety_filter']])
    print('horizon',[(p['ai'],p['pair'],p['timeline'],p['nodes'],p['decision_status'],p['result']['completed_depth'],p['result']['choice']['chain'],p['result']['choice']['defense_commitment']) for p in report['horizon']])
    print('pace',[(p['pace'],p['result']['choice']['frame'],p['result']['choice']['projected_return_frame'],p['result']['choice']['projected_sufficient_return']) for p in report['pace']])


if __name__=='__main__':
    main()
