"""Replay recorded strategy positions and time cached execution without game input."""
import argparse
from copy import deepcopy
import importlib.util
import json
import statistics
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.chain_to_us import flights_to_us
from fever_battle.gauge_wait import retime_cached


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,default=ROOT/'data/fever/golden/live-strategy-regressions.json')
    parser.add_argument('--before-gauge-source',type=Path)
    parser.add_argument('--retime-repeats',type=int,default=0)
    parser.add_argument('--output',type=Path,default=ROOT/'bin/live-policy-replay.json')
    args=parser.parse_args()
    before=None
    if args.before_gauge_source:
        spec=importlib.util.spec_from_file_location('fever_battle._before_wait',args.before_gauge_source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        before=module.GaugeWait
    results=[]
    for case in json.loads(args.fixture.read_text(encoding='utf-8'))['cases']:
        req=deepcopy(case['request']);req.pop('op',None)
        engine=ModeBattleEngine(ROOT/'bin/fever_battle/fever_battle.exe',ROOT/'bin/fever/fever.exe',ROOT/'config.json')
        row=dict(line=case['line'],ai=case['ai'],rate=req['target_point'])
        try:
            prepared=engine.answer(dict(req,op='prepare_observed'))
            start=time.perf_counter_ns();reply=engine.answer(req)
            row.update(prepared=prepared.get('prepared'),execution_ms=(time.perf_counter_ns()-start)/1e6,
                reused=reply.get('search_reused',False),reason=reply.get('reason'),chain=reply.get('chain'),
                cells=sum(c not in '.#' for r in req['self']['field'] for c in r),
                build_options=getattr(engine,'last_normal_options',None))
            if args.retime_repeats and reply.get('offset_timing'):
                samples=[]
                for _ in range(args.retime_repeats):
                    start=time.perf_counter_ns();retime_cached(reply,req)
                    samples.append((time.perf_counter_ns()-start)/1e6)
                samples.sort()
                row['retiming_latency']=dict(n=len(samples),median_ms=statistics.median(samples),
                    p95_ms=samples[(95*len(samples)+99)//100-1],max_ms=max(samples))
            shot=case.get('recorded_reply',{})
            if shot and req['target_point']<120 and req['self']['mode']=='normal':
                own,enemy=req['self'],req['enemy']
                placements=engine.native.ask(dict(op='placements',field=own['field'],piece=own['queue'][0]))['placements']
                placed=next(p for p in placements if (p['x'],p['r'])==(shot['x'],shot['r']))
                points=engine.scoring.chain(own['character'],placed['links'])
                flights=flights_to_us(engine._enemy_events(req,enemy),enemy,req['target_point'])
                baseline=dict(x=shot['x'],r=shot['r'],fire=True,link_points=points)
                for name,wait in [('after',engine.gauge_wait)]+([] if before is None else [('before',before(engine.native,engine.scoring))]):
                    chosen=wait.choose(req,own,enemy,deepcopy(baseline),engine.policy['normal_build']['gauge_wait'],req['target_point'],flights)
                    row[name]=dict(status=wait.status,hold=None if chosen is None else chosen.get('hold_frames'))
            results.append(row)
            print(json.dumps({k:v for k,v in row.items() if k!='build_options'}))
        finally:engine.close()
    args.output.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
