"""Measure fixed logged boards without changing the operation-fall decisions.

Only placements, normal capacity, and isolated construction are reproduced;
this is not a reconstruction of the live protocol-3 request or input timing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine
from fever_check import normal


def measure(native, solo, cases):
    engine = ModeBattleEngine(native, solo, ROOT / 'config.json')
    rows = []
    try:
        for case in cases:
            engine.sync_pattern(dict(character=case['character'], pattern=case['pattern']))
            options = {**engine.policy['solo_options'], 'beam_width': 100,
                'beam_depth': 8, 'build_chain': 15, 'trigger': 15,
                'panic_chain': 13, 'panic_count': 70, 'panic_step': 2,
                'patience': 0, 'construction_scoring': True, 'preserve_build': True}
            requests = {
                'placements': dict(op='placements', field=case['field'], piece=case['queue'][0]),
                'capacity': dict(op='normal_capacity', field=case['field'], queue=case['queue'],
                    character=case['character'], margin=1, target=15, threat=False),
                'build': dict(rule='fever', solo=True, character=case['character'],
                    dropset_index=case['dropset_index'], self={'field': case['field'], 'queue': case['queue']},
                    plain_pairs=True, special_moves=True, include_next=True, **options),
            }
            row = dict(round=case['round'], pair=case['pair'], ms={}, replies={})
            for name, request in requests.items():
                start = time.perf_counter()
                result = (engine.solo if name == 'build' else engine.native).ask(request)
                row['ms'][name] = round((time.perf_counter() - start) * 1000, 2)
                row['replies'][name] = normal(result)
            rows.append(row)
    finally:
        engine.close()
    return dict(native_sha256=hashlib.sha256(Path(native).read_bytes()).hexdigest(),
                solo_sha256=hashlib.sha256(Path(solo).read_bytes()).hexdigest(), cases=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=ROOT / 'data/fever/baselines/2026-10-13-operation-fall-speed-cases.json')
    parser.add_argument('--before-native', required=True, type=Path)
    parser.add_argument('--before-solo', required=True, type=Path)
    parser.add_argument('--after-native', required=True, type=Path)
    parser.add_argument('--after-solo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    before = measure(args.before_native, args.before_solo, cases)
    after = measure(args.after_native, args.after_solo, cases)
    differences = [dict(round=a['round'], pair=a['pair'], op=name)
        for a, b in zip(before['cases'], after['cases'])
        for name in a['replies'] if a['replies'][name] != b['replies'][name]]
    args.output.write_text(json.dumps(dict(before=before, after=after, differences=differences),
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name in ('placements', 'capacity', 'build'):
        a = [r['ms'][name] for r in before['cases']]
        b = [r['ms'][name] for r in after['cases']]
        print(f'{name}: median {statistics.median(a):.2f} -> {statistics.median(b):.2f} ms; '
              f'max {max(a):.2f} -> {max(b):.2f} ms')
    print(f'{len(cases)} cases, {len(differences)} changed replies')
    return bool(differences)


if __name__ == '__main__':
    sys.exit(main())
