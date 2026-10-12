"""Read-only policy probes and bridge-log extraction; no game/controller access."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.worker import JsonProcess
from fever_battle.model import Scoring


def heights(rows):
    return [sum(row[x] != '.' for row in rows) for x in range(6)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--output',type=Path,default=ROOT/'data/fever/baselines/2026-10-11-normal-defense-investigation.json')
    args=parser.parse_args()
    binary = args.native.resolve()
    baseline = json.loads((ROOT/'data/fever/baselines/2026-10-11-normal-fire-timing-investigation.json').read_text(encoding='utf-8'))
    template = deepcopy(next(c['request'] for c in baseline['cases'] if c['character']=='arle' and c['pending']==20 and c['event_at']==700))
    probes = []
    with JsonProcess([binary], cwd=ROOT) as native:
        for fever in (False, True):
            for count in (0, 1, 6, 20, 90, 160):
                req = deepcopy(template)
                req.update(enemy_events=[], confirmed=count, unconfirmed=0, enemy_fever=fever)
                reply = native.ask(req)
                probes.append(dict(name='packet', fever=fever, pending=count, request=req, reply=reply))
        # Separate first-game Fever avoidance from a later normal/normal exchange.
        for avoid in (False, True):
            req = deepcopy(template)
            req.update(enemy_events=[], confirmed=1, unconfirmed=0, enemy_fever=False,
                       avoid_own_fever=avoid, main_trigger_points=1000)
            probes.append(dict(name='small_full_priority', avoid=avoid, request=req, reply=native.ask(req)))
        column_heights = [6,12,6,6,12,6]
        rows = [''.join('RYGB'[(x+y)%4] if y<column_heights[x] else '.' for x in range(6)) for y in reversed(range(14))]
        for penalty in (0,-1000000):
            req = deepcopy(template)
            req.update(field=rows, queue=['2:YB'], enemy_events=[], confirmed=1,
                       unconfirmed=0, enemy_fever=False, builder=dict(x=1,r='U',fire=False))
            req['weights'].update(upper_12=penalty,upper_13=penalty)
            reply=native.ask(req)
            probes.append(dict(name='upper_tactics', penalty=penalty, request=req, reply=reply,
                               choice_heights=heights(reply['choice']['field'])))
    log=Path('C:/Users/ho_ki/git/ama-memory-bridge/observations/input-session.log')
    rows=[json.loads(s) for s in log.read_text(encoding='utf-16').splitlines() if s.startswith('{')]
    plans={}; fires=[]; upper=[]; threats=[]
    for r in rows:
        if r.get('auto')=='planning' and r.get('field') and r.get('mode')=='normal':
            plans[(r.get('ai'),r.get('pair'))]=r
            if r.get('enemy_chain'):
                threats.append(r)
        elif r.get('auto') in ('fire','locked') and r.get('mode')=='normal':
            p=plans.get((r.get('ai'),r.get('pair')))
            if not p: continue
            if r.get('auto')=='fire': fires.append(dict(plan=p,lock=r))
            # Log only has the root board. Upper placement proof needs simulation,
            # not interpreting the axis column as a final occupied cell.
            h=heights(p['field'].split('/'))
            if max(h[1],h[4])>=12: upper.append(dict(plan=p,lock=r,root_heights=h))
    small=[f for f in fires if f['lock'].get('chain',0)>=4 and 0<sum(f['plan'].get('nuisance',[0,0]))<=6]
    upper_additions=[]; small_replays=[]; return_capacity=[]
    scoring=Scoring()
    with JsonProcess([binary], cwd=ROOT) as native:
        for sample in upper:
            p,lock=sample['plan'],sample['lock']
            placements=native.ask(dict(op='placements',field=p['field'].split('/'),piece=p['queue'][0]))['placements']
            move=next((m for m in placements if m['x']==lock['x'] and m['r']==lock['r']),None)
            if move:
                h=heights(move['field'])
                if any(h[x]>=13 and h[x]>sample['root_heights'][x] for x in (1,4)):
                    upper_additions.append(dict(sample=sample,transition=move,result_heights=h))
        for sample in small:
            p,lock=sample['plan'],sample['lock']
            moves=native.ask(dict(op='placements',field=p['field'].split('/'),piece=p['queue'][0]))['placements']
            actual=next((m for m in moves if m['x']==lock['x'] and m['r']==lock['r']),None)
            if not actual: continue
            possible=[char for char in scoring.data['characters'] if
                      sum(scoring.link(char,i+1,l['groups'],l['colors']) for i,l in enumerate(actual['links']))==lock['score']]
            # Score-compatible tables only; log does not state the character.
            for char in possible[:1]:
                req=deepcopy(template)
                req.update(field=p['field'].split('/'),queue=p['queue'],confirmed=p['nuisance'][0],
                           unconfirmed=p['nuisance'][1],enemy_events=[],enemy_fever=False,
                           gauge=p['gauge'],powers=scoring.data['characters'][char]['normal'],
                           avoid_own_fever=False,main_trigger_points=40*sum(scoring.data['characters'][char]['normal'][:15]))
                reply=native.ask(req)
                small_replays.append(dict(sample=sample,score_compatible_characters=possible,
                    assumed_no_future_events=True,request=req,reply=reply))
        for p in [r for r in threats if r.get('reason')=='no_rescue_fast_finish' and r['enemy']['mode']=='normal'][:3]:
            cache={}; maximum_chain=0; maximum_points=0
            def visit(field,depth):
                nonlocal maximum_chain,maximum_points
                key=(tuple(field),depth)
                if key in cache: return
                cache[key]=True
                moves=native.ask(dict(op='placements',field=field,piece=p['queue'][depth]))['placements']
                for m in moves:
                    maximum_chain=max(maximum_chain,len(m['links']))
                    for char in scoring.data['characters']:
                        pts=sum(scoring.link(char,i+1,l['groups'],l['colors']) for i,l in enumerate(m['links']))
                        maximum_points=max(maximum_points,pts)
                    if not m['dead'] and not m['links'] and depth+1<len(p['queue']): visit(m['field'],depth+1)
            visit(p['field'].split('/'),0)
            return_capacity.append(dict(plan=p,maximum_chain=maximum_chain,maximum_points_any_character=maximum_points,
                visible=len(p['queue']),ignores_nuisance_and_timing=True,searched_boards=len(cache)))
    report=dict(native_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), probes=probes,
                bridge_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
                log_process_binary_unknown=True, normal_fires_with_plan=len(fires),
                small_packet_main_fires=small, upper_root_samples=upper,
                upper_additions=upper_additions,small_packet_replays=small_replays,
                optimistic_visible_return_capacity=return_capacity,
                enemy_chain_plans=len(threats), enemy_chain_samples=threats)
    out=args.output
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for p in probes:
        c=p['reply']['choice']
        print(p['name'],p.get('fever',p.get('avoid',p.get('penalty'))),p.get('pending'),
              c['x'],c['r'],c['chain'],c['defensive_fire'],p.get('choice_heights'))
    print('log:',len(fires),'normal fires;',len(small),'main fires for 1..6 pending;',len(upper),'high upper roots;',len(threats),'enemy-chain plans')
    print('upper additions:',len(upper_additions))
    for r in small_replays:
        print('small replay',r['sample']['lock']['t'],r['score_compatible_characters'],r['reply']['choice']['chain'],r['reply']['choice']['defensive_fire'])
    for r in return_capacity: print('return capacity',r['plan']['t'],r['maximum_chain'],r['maximum_points_any_character'],r['plan']['nuisance'])


if __name__=='__main__':
    main()
