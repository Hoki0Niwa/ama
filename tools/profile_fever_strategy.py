"""Attribute offline decision latency to worker operations, including cold-cache controls."""
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine


def measure(request):
    engine = ModeBattleEngine(ROOT/'bin/fever_battle/fever_battle.exe', ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    calls = []
    ask = engine.native.ask
    think = engine._think
    in_think = False
    think_ms = []

    def traced_think(*args, **kwargs):
        nonlocal in_think
        before = in_think
        in_think = True
        start = time.perf_counter_ns()
        try:
            return think(*args, **kwargs)
        finally:
            think_ms.append((time.perf_counter_ns()-start)/1e6)
            in_think = before

    def traced(value, *args, **kwargs):
        start = time.perf_counter_ns()
        result = ask(value, *args, **kwargs)
        elapsed = (time.perf_counter_ns()-start)/1e6
        detail = dict(op=value.get('op'), ms=elapsed, in_think=in_think)
        if value.get('op') == 'solo':
            detail['options'] = value['request']
            detail['completed_depth'] = result.get('search_completed_depth')
        if value.get('op') == 'tactics':
            detail['limits'] = {k:value.get(k) for k in ('width','max_nodes','budget_ms')}
        calls.append(detail)
        return result

    engine.native.ask = traced
    engine._think = traced_think
    try:
        start = time.perf_counter_ns()
        reply = engine.answer(request)
        elapsed = (time.perf_counter_ns()-start)/1e6
        return dict(ms=elapsed, think_ms=sum(think_ms), reported_ms=reply.get('search_ms'), reason=reply.get('reason'),
                    calls=calls, reused=reply.get('search_reused',False))
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--variants', nargs='+', choices=('mainline','capped_build','no_window','cold_spawn','hybrid','width32','depth6'),
                        default=('mainline','capped_build','no_window','cold_spawn','hybrid'))
    parser.add_argument('--output', type=Path, default=ROOT/'bin/strategy-profile.json')
    args = parser.parse_args()
    cases = json.loads(args.fixture.read_text(encoding='utf-8'))['cases']
    names = tuple(args.variants)
    rows = []
    for repeat in range(args.repeats):
        for index, case in enumerate(cases):
            offset = (repeat+index) % len(names)
            for name in names[offset:]+names[:offset]:
                req = deepcopy(case['request'])
                req.pop('normal_tactics', None)
                if name == 'capped_build':
                    req.setdefault('solo_options', {}).update(beam_width=32, beam_depth=6)
                elif name == 'width32':
                    req.setdefault('solo_options', {})['beam_width'] = 32
                elif name == 'depth6':
                    req.setdefault('solo_options', {})['beam_depth'] = 6
                elif name == 'no_window':
                    req['normal_tactics'] = dict(window_build=dict(enabled=False))
                elif name == 'cold_spawn':
                    req['cold_spawn'] = True
                elif name == 'hybrid':
                    req['normal_tactics'] = dict(strategy='hybrid')
                rows.append(dict(case=index, repeat=repeat, variant=name, **measure(req)))
    summary = {}
    for name in names:
        chosen = [r for r in rows if r['variant']==name]
        times = sorted(r['ms'] for r in chosen)
        operations = defaultdict(float)
        for row in chosen:
            for call in row['calls']:
                operations[call['op']] += call['ms']
        summary[name] = dict(n=len(times), median=statistics.median(times),
            think_median=statistics.median(r['think_ms'] for r in chosen),
            p95=times[(95*len(times)+99)//100-1], max=max(times),
            mean_worker_ms={k:v/len(times) for k,v in sorted(operations.items(),key=lambda x:-x[1])})
    hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        (args.fixture, ROOT/'bin/fever_battle/fever_battle.exe',ROOT/'config.json')}
    args.output.write_text(json.dumps(dict(summary=summary, hashes=hashes, rows=rows),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
