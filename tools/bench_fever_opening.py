"""Compare continuous opening construction with the same queues and CPU budget.

No game input. Prototype color queues, no opponent attack; not a win-rate test.
"""
import argparse
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine
sys.path.insert(0,str(ROOT/'tools'))
from bench_fever_normal_build import side


def run(engine,character,seed,width,visible,budget,quiet,stop_chain,depth):
    queue=engine.native.ask(dict(op='queue',character=character,seed=seed,count=123))['queue']
    own,enemy=side(character),side(character)
    enemy['queue']=queue[:3]
    engine.policy['normal_tactics']['quiet']=quiet
    reasons=Counter();clears=[];depths=Counter();moves=[]
    moves_since_chain=0
    own['normal_chain_max']=0
    for i in range(120):
        own.update(field=own['field'],queue=queue[i:i+visible],piece_id=i,dropset_index=i%16,
            observed_frame=i,moves_since_chain=moves_since_chain)
        enemy['observed_frame']=i
        req=dict(protocol_version=3,rule='fever_battle',match_id=f'opening-{character}-{seed}-{width}-{visible}-{quiet}',frame=i,
            observation=dict(frame_before=i,frame_after=i,match_status='running'),target_point=120,
            gauge_gain_on_offset=1,clock_policy=dict(count_chain_frames=True),self=own,enemy=enemy,
            solo_options=dict(beam_width=width,beam_depth=depth))
        if budget:req['decision_budget_ms']=budget
        reply=engine.answer(req)
        if reply.get('action')!='place':return dict(end=reply,steps=i)
        reasons[reply['reason']]+=1
        if reply.get('normal_build_completed_depth') is not None:depths[reply['normal_build_completed_depth']]+=1
        step=engine.native.ask(dict(op='transition',field=own['field'],piece=own['queue'][0],x=reply['x'],r=reply['r']))
        chain=len(step['links']);moves.append(dict(piece=i,chain=chain,reason=reply['reason'],
            move=f"{reply['x']}{reply['r']}",depth=reply.get('normal_build_completed_depth')))
        if chain:clears.append(dict(piece=i,chain=chain,reason=reply['reason']))
        if chain>=stop_chain or step['dead']:
            return dict(end='dead' if step['dead'] else 'fire',chain=chain,steps=i+1,
                clears=clears,reasons=dict(reasons),depth_histogram=dict(depths),moves=moves)
        own['field']=step['field']
        own['normal_chain_max']=max(own['normal_chain_max'],chain)
        moves_since_chain=0 if chain else moves_since_chain+1
    return dict(end='limit',chain=0,steps=120,clears=clears,reasons=dict(reasons),depth_histogram=dict(depths),moves=moves)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,default=ROOT/'bin/fever_battle/fever_battle.exe')
    # SoloBuilder uses op=solo inside --native; the compatibility solo path is unused.
    parser.add_argument('--stop-chain',type=int,default=15)
    parser.add_argument('--character',default='rafisol')
    parser.add_argument('--seeds',type=int,default=4)
    parser.add_argument('--width',type=int,default=250)
    parser.add_argument('--depth',type=int,default=8)
    parser.add_argument('--score-weight',type=int)
    parser.add_argument('--visible',type=int,default=3)
    parser.add_argument('--budget',type=int,default=100)
    parser.add_argument('--quiet',action='store_true')
    parser.add_argument('--allow-builder-clears',action='store_true',help='offline comparison of the original builder root selection')
    parser.add_argument('--legacy-quiet',action='store_true',help='reproduce the previous permissive quiet adoption in this process only')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.legacy_quiet:
        from fever_battle import tactics
        source=inspect.getsource(tactics.choose).replace(
            "useful_harass = harass and choice.get('projected_harass', False)",
            "useful_harass = harass\n        killing = choice['projected_kill'] > 0").replace(
            "choice['sent'] and useful_harass", "choice['sent'] and (useful_harass or killing)")
        scope=dict(tactics.choose.__globals__)
        exec(compile(source,'offline_legacy_quiet','exec'),scope)
        tactics.choose=scope['choose']
    engine=ModeBattleEngine(args.native,ROOT/'bin/fever/fever.exe',ROOT/'config.json')
    if args.score_weight is not None:
        engine.solo.sets['fever']['score']=args.score_weight
    if args.allow_builder_clears:
        original=engine._normal_options
        engine._normal_options=lambda req,own: dict(original(req,own),preserve_build=False)
    rows=[]
    try:
        for seed in range(1,args.seeds+1):
            row=run(engine,args.character,seed,args.width,args.visible,args.budget,args.quiet,args.stop_chain,args.depth)
            rows.append(dict(seed=seed,**row))
            print(json.dumps(dict(seed=seed,**{k:v for k,v in row.items() if k!='moves'})),flush=True)
    finally:engine.close()
    report=dict(native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
        builder='op=solo inside native worker',settings=vars(args),runs=rows,
        status='prototype_color_queues_no_opponent_attack_no_game_input')
    args.output.write_text(json.dumps(report,default=str,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':main()
