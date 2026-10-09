"""Read-only log statistics and controlled construction/override comparisons."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from fever_battle.mode_engine import ModeBattleEngine
from bench_fever_normal_build import side


def records(path):
    b=path.read_bytes()
    text=b.decode('utf-16' if b[:2] in (b'\xff\xfe',b'\xfe\xff') else 'utf-8-sig')
    out=[]
    for line in text.splitlines():
        try:out.append(json.loads(line))
        except ValueError:pass
    return out


def run(engine,queue,label,budget,quiet,limit=60):
    engine.policy['normal_tactics']['quiet']=quiet
    own,enemy=side('rafisol'),side('rafisol')
    # A normal, empty opponent cannot offset into Fever. No scripted attacks.
    enemy['queue']=queue[:3]
    reasons=Counter();small=[];peak=0;decisions=[]
    for i in range(min(limit,len(queue)-2)):
        own.update(queue=queue[i:i+3],piece_id=i,dropset_index=i%16,moves_since_chain=i,observed_frame=i)
        enemy['observed_frame']=i
        request=dict(protocol_version=3,rule='fever_battle',match_id=label,frame=i,
            observation=dict(frame_before=i,frame_after=i,match_status='running'),
            target_point=120,gauge_gain_on_offset=1,clock_policy=dict(count_chain_frames=True),
            self=own,enemy=enemy,solo_options=dict(beam_width=250,beam_depth=8))
        if budget:request['decision_budget_ms']=budget
        reply=engine.answer(request)
        if reply.get('action')!='place':return dict(end=reply,steps=i)
        reasons[reply['reason']]+=1
        step=engine.native.ask(dict(op='transition',field=own['field'],piece=own['queue'][0],x=reply['x'],r=reply['r']))
        chain=len(step['links']);peak=max(peak,sum(c not in '.#' for row in own['field'] for c in row))
        decisions.append(dict(piece=i,move=f"{reply['x']}{reply['r']}",reason=reply['reason'],chain=chain))
        if chain>=4 or step['dead']:
            return dict(end='dead' if step['dead'] else 'fire',chain=chain,steps=i+1,
                small_clears=small,peak_cells=peak,reasons=dict(reasons),decisions=decisions)
        if chain:small.append(dict(piece=i,chain=chain,reason=reply['reason']))
        own['field']=step['field']
    return dict(end='limit',chain=0,steps=limit,reasons=dict(reasons),small_clears=small,peak_cells=peak,decisions=decisions)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--local-only',action='store_true',help='retain completed controlled measurements and refresh local comparisons')
    args=parser.parse_args()
    rows=records(args.log)
    plans=[r for r in rows if r.get('auto')=='planning' and 'move' in r]
    fires=[r for r in rows if r.get('auto')=='fire']
    engine=ModeBattleEngine(ROOT/'bin/fever_battle/fever_battle.exe',ROOT/'bin/fever/fever.exe',ROOT/'config.json')
    report=dict(status='investigation_only_no_product_changes_or_game_input',log=str(args.log),
        native_sha256=hashlib.sha256((ROOT/'bin/fever_battle/fever_battle.exe').read_bytes()).hexdigest(),
        plans=len(plans),normal_fire_histogram=dict(Counter(str(r.get('chain')) for r in fires if r.get('mode')=='normal')),
        reasons=dict(Counter(r['reason'] for r in plans if r['mode']=='normal')),
        disruption_cases=[r for r in plans if r['reason']=='tactics_disrupt'],controlled=[])
    if args.local_only:
        report['controlled']=json.loads(args.output.read_text(encoding='utf-8'))['controlled']
    try:
        for seed in (() if args.local_only else (1,2)):
            queue=engine.native.ask(dict(op='queue',character='rafisol',seed=seed,count=63))['queue']
            for budget,quiet in ((100,True),(100,False),(0,False)):
                case=dict(seed=seed,decision_budget_ms=budget or None,quiet_tactics=quiet,
                    result=run(engine,queue,f'regression-{seed}-{budget}-{quiet}',budget,quiet))
                report['controlled'].append(case)
                print(json.dumps({**case,'result':{k:v for k,v in case['result'].items() if k!='decisions'}}),flush=True)
        # Capture a real tactical request; compare native versions and disable
        # only the new pressure reward, leaving construction options identical.
        report['local_comparisons']=[]
        for plan in [p for p in plans if p['reason']=='tactics_disrupt' and not p['enemy_chain'] and p['nuisance'][0]==0][:4]:
            own=side('rafisol');own.update(field=plan['field'].split('/'),queue=plan['queue'],gauge=plan['gauge'],
                dropset_index=plan['pair']%16,piece_id=plan['pair'],moves_since_chain=plan['pair'])
            opts=dict(engine.policy['solo_options'],beam_width=250,beam_depth=8,preserve_build=True)
            build=engine._solo_build(own,opts)
            target={k:v for k,v in plan['fever_disruption'].items() if k not in ('kind','enemy_seed_geometry')}
            enemy=side('rafisol','fever');enemy.update(field=plan['enemy']['field'].split('/'),
                seed_chain=plan['enemy']['seed_chain'],remaining_frames=plan['enemy']['remaining_frames'])
            from fever_battle import tactics
            policy=deepcopy(engine.policy['normal_tactics']);policy.update(budget_ms=1000,max_nodes=3000)
            captured=[];ask=engine.native.ask
            def capture(req,*a,**kw):
                if req.get('op')=='tactics':captured.append(deepcopy(req))
                return ask(req,*a,**kw)
            engine.native.ask=capture
            try:
                current_quiet=tactics.choose(engine.native,engine.scoring,own,120,1,policy,enemy=enemy,
                    fever=target,quiet=True,builder=(build['x'],build['r']),defense=dict(hold=0,kill=0,links=0,need=7))
            finally:engine.native.ask=ask
            req=captured[0]
            current=ask(req)
            req_zero=deepcopy(req);req_zero['weights']['disrupt']=0
            without=ask(req_zero)
            from fever_battle.worker import JsonProcess
            old=JsonProcess([ROOT/'bin/fever_battle/fever_battle-before-disruption.exe'],cwd=ROOT)
            try:
                previous=old.ask(req)
                previous_quiet=tactics.choose(old,engine.scoring,own,120,1,policy,enemy=enemy,
                    fever=target,quiet=True,builder=(build['x'],build['r']),defense=dict(hold=0,kill=0,links=0,need=7))
            finally:old.close()
            report['local_comparisons'].append(dict(ai=plan['ai'],t=plan['t'],piece=plan['pair'],
                builder=build,request=req,current=current,no_pressure_reward=without,previous_native=previous,
                current_quiet_accepted=current_quiet is not None,previous_quiet_accepted=previous_quiet is not None,
                limitation='Enemy queue and remaining chain events are absent from planning logs; geometry profiles not reconstructed.'))
    finally:engine.close()
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':main()
