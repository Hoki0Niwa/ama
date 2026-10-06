"""Compare repeated visible-three seed decisions using actual model clocks.

Driver queues are synthetic offline data; each solver sees only current/NEXT2.
No controller, memory reader, or live-session restart is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.model import Scoring
from fever_battle.seed_solver import SeedSolver
from fever_battle.worker import JsonProcess
from tools.verify_fever_extension import verify


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',type=Path,required=True)
    p.add_argument('--previous-native',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); scoring=Scoring()
    refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))['seeds']
    cases=[]
    with JsonProcess([args.native],cwd=ROOT) as new, JsonProcess([args.previous_native],cwd=ROOT) as old:
        solvers={'before':SeedSolver(old,scoring),'after':SeedSolver(new,scoring)}
        for clock in (600,900,1500):
            for rng_seed in range(1,7):
                ref=next(s for s in refs if s['id']=='hirazumi-3')
                queue=new.ask(dict(op='queue',character='raffina',seed=rng_seed,count=64))['queue']
                case=dict(queue_seed=rng_seed,initial_frames=clock,initial_seed=ref['id'],outcomes={})
                for label,solver in solvers.items():
                    own=dict(character='raffina',field=ref['field'],queue=[],fever_confirmed=0,
                             fever_unconfirmed=0,normal_confirmed=1000,normal_unconfirmed=0,
                             confirmed=0,remainder=0,garbage_phase=0,remaining_frames=clock,seed_chain=3,
                             seed_base=3,mode_generation=1,seed_id=rng_seed,piece_id=0)
                    steps=[]
                    for turn in range(60):
                        own['queue']=queue[turn:turn+3];own['piece_id']=turn
                        start=time.perf_counter()
                        result=solver.solve(own,120,True,dict(strategy='extend'),match_id=f'{label}-{clock}-{rng_seed}')
                        cost=(time.perf_counter()-start)*1000
                        verify(new,scoring,own,result);first=result['choice']
                        steps.append(dict(remaining_frames=own['remaining_frames'],visible_queue=own['queue'],
                                          choice=first,planned_final_chain=result['path'][-1]['chain'],
                                          planned_fire_at=result['path'][-1]['fire_at'],search_ms=cost,
                                          expanded=result['expanded'],cutoff=result['cutoff']))
                        if first['chain'] or first['dead'] or own['remaining_frames']==0:break
                        own['field']=first['field']
                        own['remaining_frames']=max(0,own['remaining_frames']-first['end_at']-12)
                    last=steps[-1];choice=last['choice']
                    case['outcomes'][label]=dict(placements=len(steps),chain=choice['chain'],
                        fire_remaining_frames=last['remaining_frames']-choice['fire_at'],
                        next_seed_input_fits=choice['next_seed_input_fits'],dead=choice['dead'],steps=steps)
                cases.append(case)
    result=dict(status='synthetic_visible_three_model_clock_replay_not_live_acceptance',controller=False,
        held_nuisance=1000,queue_model='prototype_not_steam_color_rng',solver_budget_ms=50,solver_max_nodes=8000,
        native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
        previous_native_sha256=hashlib.sha256(args.previous_native.read_bytes()).hexdigest(),cases=cases)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([dict(clock=c['initial_frames'],seed=c['queue_seed'],
        before=(c['outcomes']['before']['placements'],c['outcomes']['before']['chain'],c['outcomes']['before']['fire_remaining_frames']),
        after=(c['outcomes']['after']['placements'],c['outcomes']['after']['chain'],c['outcomes']['after']['fire_remaining_frames'])) for c in cases]))


if __name__=='__main__':main()
