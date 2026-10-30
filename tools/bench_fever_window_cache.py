"""Compare saved Python source with the current engine using identical native binaries."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine

GAMEPLAY = ('action','x','r','color','shape','fire','chain','next_chain','next_score',
            'next_field','next_all_clear','link_points','reason','decision_kind',
            'selected_move_loses','normal_root_values','normal_root_queue',
            'gauge_forecast','decision_dependencies','disruption_timing','arrival',
            'fever_disruption','entry_fire','gauge_wait')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def run(cls, request):
    engine = cls(ROOT/'bin/fever_battle/fever_battle.exe', ROOT/'bin/fever/fever.exe',ROOT/'config.json')
    calls = []
    ask = engine.solo.ask
    think = engine._think
    think_ms = []

    def traced(value, *args, **kwargs):
        start = time.perf_counter_ns()
        result = ask(value, *args, **kwargs)
        calls.append(dict(width=value.get('beam_width'), depth=value.get('beam_depth'),
            ms=(time.perf_counter_ns()-start)/1e6, request_sha=digest([value,kwargs]), result_sha=digest({k:v for k,v in result.items() if k != 'search_ms'})))
        return result

    def timed(*args, **kwargs):
        start = time.perf_counter_ns()
        try:
            return think(*args, **kwargs)
        finally:
            think_ms.append((time.perf_counter_ns()-start)/1e6)

    engine.solo.ask = traced
    engine._think = timed
    try:
        reply = engine.answer(deepcopy(request))
        return dict(think_ms=sum(think_ms), calls=calls,
            gameplay={k:reply.get(k) for k in GAMEPLAY})
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline_source', type=Path)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, default=ROOT/'bin/window-cache-comparison.json')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('fever_battle._cache_baseline', args.baseline_source)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    cases = json.loads(args.fixture.read_text(encoding='utf-8'))['cases']
    rows = []
    for repeat in range(args.repeats):
        for index, case in enumerate(cases):
            result = {}
            order = ('before','after') if (repeat+index)%2==0 else ('after','before')
            for name in order:
                result[name] = run(baseline.ModeBattleEngine if name=='before' else ModeBattleEngine,case['request'])
            a,b = result['before'], result['after']
            if a['gameplay'] != b['gameplay']:
                raise AssertionError(f'changed gameplay at case {index}: '+str([k for k in GAMEPLAY if a['gameplay'][k]!=b['gameplay'][k]]))
            # Every retained native search has exactly the same input and result.
            for call in b['calls']:
                assert any((call['request_sha'],call['result_sha'])==(old['request_sha'],old['result_sha']) for old in a['calls']), (index,call)
            rows.append(dict(case=index, repeat=repeat, **result))
    summary = {}
    for index in range(len(cases)):
        chosen = [r for r in rows if r['case']==index]
        summary[index] = {name:dict(median_ms=statistics.median(r[name]['think_ms'] for r in chosen),
            widths=[c['width'] for c in chosen[0][name]['calls']]) for name in ('before','after')}
    hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (
        args.baseline_source,args.fixture,ROOT/'fever_battle/mode_engine.py',ROOT/'bin/fever_battle/fever_battle.exe',ROOT/'config.json')}
    args.output.write_text(json.dumps(dict(hashes=hashes,rows=rows,summary=summary),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
