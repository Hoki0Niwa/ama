"""Serial full-build/cold/cache timings on the same recorded boards; no live input."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=40)
    parser.add_argument('--output',type=Path,default=ROOT/'data/fever/baselines/visible-relief-v3-latency.json')
    args=parser.parse_args()
    if args.samples<2: parser.error('at least two samples required')
    source=ROOT/'data/fever/baselines/preparation-quality/live-first-round.json'
    raw=source.read_bytes();rows=json.loads(raw)['rows']
    variants={
        'before':('bin/small-chain-before/fever_battle.exe','bin/small-chain-before/normal_conversion.py'),
        'previous':('bin/visible-relief-v2/fever_battle.exe','bin/visible-relief-v2/normal_conversion.py'),
        'after':('bin/fever_battle/fever_battle.exe',None)}
    modules={}
    for name,(_,path) in variants.items():
        if path:
            spec=importlib.util.spec_from_file_location('fever_battle.latency_'+name,ROOT/path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules[name]=module
    report=dict(source_sha256=hashlib.sha256(raw).hexdigest(),
        method='fresh process; pattern/power sync before timer; first cycle discarded; alternating order; no concurrent build/full test suite; system background load not controlled; cached means completed same-board construction reused',samples=args.samples,runs=[])
    for seat,piece in [(1,19),(2,24)]:
        initial=deepcopy(next(r['request'] for r in rows if r.get('ai')==seat and r.get('pair')==piece and r.get('request')))
        initial.update(op='think',match_id='visible-relief-latency')
        initial.pop('active_placement',None);initial.pop('enemy_chain',None)
        initial['enemy'].update(field=['......']*14,mode='normal',phase='placing',gauge=0,
            normal_chain_max=0,mode_generation=0,confirmed=0,unconfirmed=0,
            normal_confirmed=0,normal_unconfirmed=0,fever_confirmed=0,fever_unconfirmed=0)
        initial['self'].update(confirmed=0,unconfirmed=0,normal_confirmed=0,normal_unconfirmed=0,fever_confirmed=0,fever_unconfirmed=0)
        initial['observation'].pop('in_flight',None)
        for mode in ['construction','cold','cached']:
            values={name:[] for name in variants};choices={name:[] for name in variants};calls={name:[] for name in variants}
            for iteration in range(args.samples+1):
                order=list(variants) if iteration%2==0 else list(reversed(variants))
                for name in order:
                    native,_=variants[name];engine=ModeBattleEngine(ROOT/native,ROOT/'bin/fever/fever.exe',ROOT/'config.json')
                    try:
                        engine.policy['normal_tactics']['quiet']=False
                        engine.policy['normal_build']['conversion']['reuse_visible']=name!='before'
                        if name in modules:
                            engine.normal_conversion=modules[name].NormalConversion(engine.native,engine.solo,engine.scoring)
                        request=deepcopy(initial);request['cold_spawn']=mode=='cold'
                        engine.mode_side(request['self'])
                        if mode=='cached':
                            engine.answer(request);request['cold_spawn']=True
                        original=engine.native.ask;ops=[]
                        def ask(req,*a,**kw):
                            ops.append(req['op']);return original(req,*a,**kw)
                        engine.native.ask=ask
                        started=time.perf_counter();reply=engine.answer(request);elapsed=1000*(time.perf_counter()-started)
                        if iteration:
                            values[name].append(elapsed);choices[name].append([reply['x'],reply['r'],reply['chain']]);calls[name].append(ops.count('solo'))
                    finally:engine.close()
            summary={name:dict(median_ms=statistics.median(v),p95_ms=sorted(v)[max(0,(95*len(v)+99)//100-1)],max_ms=max(v)) for name,v in values.items()}
            report['runs'].append(dict(seat=seat,piece=piece,mode=mode,request=initial,times_ms=values,choices=choices,solo_calls=calls,summary=summary))
            print(seat,piece,mode,summary,flush=True)
    report['sha256']={native:hashlib.sha256((ROOT/native).read_bytes()).hexdigest() for native,_ in variants.values()}
    report['sha256'].update({path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for _,path in variants.values() if path})
    report['sha256']['fever_battle/normal_conversion.py']=hashlib.sha256((ROOT/'fever_battle/normal_conversion.py').read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
