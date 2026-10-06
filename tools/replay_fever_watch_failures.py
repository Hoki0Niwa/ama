"""Read-only replay of the observed piece preceding each early failed clear."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.calibrate import records, file_sha256
from fever_battle.mode_engine import ModeBattleEngine
from tools.verify_fever_extension import verify


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--native',type=Path,required=True)
    parser.add_argument('--previous-native',type=Path,required=True)
    parser.add_argument('--bridge',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.bridge))
    from fever_mode_bridge import Context, NotReady
    report=json.loads(args.report.read_text(encoding='utf-8'))
    cases=report['behaviour']['failed_chains_with_held_nuisance']
    wanted={(case['epoch'],case['seat']-1,case['onset']['frame_bounds'][1]):case for case in cases if case['onset']}
    context=Context(); epoch=0; previous=None; last=[None,None]; origins={}; snapshots=[]
    for name in report['recording_status']['closed_segments']:
        for packet in records(args.directory/name):
            if packet.get('event')!='sample': continue
            frame=packet['frame_before']
            if previous is not None and frame<previous:
                epoch+=1; last=[None,None]
            previous=frame
            try: context.update(packet)
            except (NotReady,ValueError): continue
            for seat in (0,1):
                case=wanted.get((epoch,seat,frame))
                if case:
                    snapshot=last[seat]
                    if snapshot and snapshot['self']['dropset_index']==case['queue_index']:
                        key=(snapshot['match_id'],snapshot['self']['mode_generation'],snapshot['self']['seed_id'],snapshot['self']['character'])
                        snapshots.append(dict(case=case,request=snapshot,seed_origin=origins.get(key)))
                try: request=context.request(seat)
                except (NotReady,ValueError): continue
                if request['self']['mode']=='fever':
                    key=(request['match_id'],request['self']['mode_generation'],request['self']['seed_id'],request['self']['character'])
                    origins.setdefault(key,request['self']['piece_id'])
                    last[seat]=deepcopy(request)
    old=ModeBattleEngine(args.previous_native,ROOT/'bin/fever/fever.exe',ROOT/'config.json')
    new=ModeBattleEngine(args.native,ROOT/'bin/fever/fever.exe',ROOT/'config.json')
    try:
        for snapshot in snapshots:
            request=snapshot['request']; own=request['self']
            key=(request['match_id'],own['mode_generation'],own['seed_id'],own['character'])
            for label,engine in (('before',old),('after',new)):
                engine.seed_solver.seed_origin=(key,snapshot['seed_origin'])
                reply=engine.answer(request)
                forecast=reply.get('seed_forecast')
                if forecast: verify(engine.native,engine.scoring,own,forecast)
                snapshot[label]=reply
    finally: old.close(); new.close()
    result=dict(source_report=str(args.report),native_sha256=file_sha256(args.native),
                previous_native_sha256=file_sha256(args.previous_native),results=snapshots,
                status='model_replay_only_running_ai_unchanged')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([dict(epoch=s['case']['epoch'],seat=s['case']['seat'],
        frame=s['request']['frame'],remaining=s['request']['self']['remaining_frames'],
        seed_confirmed=s['request']['self']['fever_confirmed'],
        before_chain=s['before'].get('chain'),after_chain=s['after'].get('chain'),
        before_reason=s['before'].get('reason'),after_reason=s['after'].get('reason'),
        deferred=s['after'].get('seed_forecast',{}).get('early_failure_deferred')) for s in snapshots]))


if __name__=='__main__': main()
