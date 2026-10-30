"""Compare captured normal builds; no opponent actions or live input are replayed."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import bench_fever_conversion as bench
from fever_battle.mode_engine import ModeBattleEngine


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variants',nargs='+',choices=['before','previous','after'],default=['before','previous','after'])
    parser.add_argument('--after-native',type=Path,default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--side-slots',type=int,default=4)
    parser.add_argument('--output',type=Path,default=ROOT/'data/fever/baselines/visible-relief-v3-comparison.json')
    args=parser.parse_args()
    source = ROOT/'data/fever/baselines/preparation-quality/live-first-round.json'
    rows = json.loads(source.read_text(encoding='utf-8'))['rows']
    legacy = ROOT/'bin/small-chain-before/normal_conversion.py'
    spec = importlib.util.spec_from_file_location('fever_battle.legacy_conversion', legacy)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        legacy_python_sha256=hashlib.sha256(legacy.read_bytes()).hexdigest(),
        condition='quiet tactics disabled; recorded pieces; no opponent actions/input; stop at >=13 links', runs=[])
    for seat in (1, 2):
        events = [r for r in rows if r.get('ai') == seat and r.get('request')]
        pieces = {}
        for event in events:
            own = event['request']['self']
            for k, piece in enumerate(own['queue']):
                if k == 0 or own['piece_id']+k not in pieces:
                    pieces[own['piece_id']+k] = piece
        for start in (0, 24):
            initial = next(r['request'] for r in events if r.get('pair') == start)
            for variant in args.variants:
                native = ROOT/({'before':'bin/small-chain-before/fever_battle.exe', 'previous':'bin/visible-relief-v2/fever_battle.exe', 'after':str(args.after_native)}[variant])
                def factory(*engine_args):
                    engine = ModeBattleEngine(*engine_args)
                    engine.policy["normal_build"]["conversion"]["side_frontier_slots"] = args.side_slots
                    engine.policy["normal_build"]["conversion"]["reuse_visible"] = variant == "after"
                    if variant == 'previous':
                        prior_spec = importlib.util.spec_from_file_location('fever_battle.previous_conversion', ROOT/'bin/visible-relief-v2/normal_conversion.py')
                        prior = importlib.util.module_from_spec(prior_spec)
                        prior_spec.loader.exec_module(prior)
                        engine.policy['normal_build']['conversion']['reuse_visible'] = True
                        engine.normal_conversion = prior.NormalConversion(engine.native, engine.solo, engine.scoring)
                    if variant == 'before':
                        engine.normal_conversion = module.NormalConversion(engine.native, engine.solo, engine.scoring)
                    return engine
                bench.ModeBattleEngine = factory
                result = bench.run(native, initial, pieces, True, 72)
                trace = result['trace']
                times = sorted(r['decision_ms'] for r in trace)
                summary = dict(seat=seat,start=start,variant=variant,end=result['end'],
                    native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
                    single=sum(r['chain']==1 for r in trace),
                    small=sum(2<=r['chain']<=4 for r in trace),
                    adopted=sum(r['reason']=='normal_capacity_conversion' and 2<=r['chain']<=4 for r in trace),
                    adoption_pieces=[r['piece'] for r in trace if r['reason']=='normal_capacity_conversion' and 2<=r['chain']<=4],
                    main_score=max((r['score'] for r in trace if r['chain']>=8), default=0),
                    main_chain=max(r['chain'] for r in trace),
                    median_ms=statistics.median(times),p95_ms=times[min(len(times)-1,int(len(times)*.95))],
                    max_ms=max(times),trace=trace)
                report['runs'].append(summary)
                print({k:v for k,v in summary.items() if k not in ('trace','native_sha256')}, flush=True)
    out=args.output
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__':
    main()
