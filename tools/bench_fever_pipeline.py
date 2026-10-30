"""Compare requested-quality replies with/without request-local native reuse."""
import argparse
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.worker import JsonProcess


def semantic(value):
    if isinstance(value,dict):return {k:semantic(v) for k,v in value.items() if not k.endswith('_ms')}
    if isinstance(value,(list,tuple)):return [semantic(v) for v in value]
    return value


def measure(case,native,enabled):
    engine=ModeBattleEngine(native,ROOT/'bin/fever/fever.exe',ROOT/'config.json')
    try:
        if not enabled:
            engine.native.decision=nullcontext
            engine.native.ask=lambda request,timeout=10:JsonProcess.ask(engine.native,request,timeout)
        start=time.perf_counter()
        reply=engine.answer(deepcopy(case['request']))
        return dict(ms=1000*(time.perf_counter()-start),reply=reply,work=engine.native.last_work)
    finally:engine.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--native',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=[]
    for case in json.loads((ROOT/'data/fever/golden/pipeline-refactor.json').read_text(encoding='utf-8'))['cases']:
        samples={False:[],True:[]};expected=None
        for repeat in range(args.repeats):
            for enabled in ((False,True) if repeat%2==0 else (True,False)):
                sample=measure(case,args.native,enabled);actual=semantic(sample['reply'])
                if expected is None:expected=actual
                if actual!=expected:raise AssertionError((case['label'],'reply changed'))
                samples[enabled].append(sample)
        row=dict(label=case['label'],identical=True,
            before_ms=statistics.median(x['ms'] for x in samples[False]),
            after_ms=statistics.median(x['ms'] for x in samples[True]),
            work=samples[True][-1]['work'])
        out.append(row);print(json.dumps(row),flush=True)
    args.output.write_text(json.dumps(out,indent=2),encoding='utf-8')

if __name__=='__main__':main()
