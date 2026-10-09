"""Summarize search/input delays from a UTF-16 Fever bridge session log."""
import argparse
from collections import Counter
import json
from pathlib import Path


def analyze(path):
    rows = []
    for line in path.read_text(encoding='utf-16', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    groups = {}
    for mode in ('normal', 'fever'):
        for attack in (False, True):
            plans = [r for r in rows if r.get('auto') == 'planning' and r.get('decision_identity')
                     and r.get('mode') == mode and bool(r.get('enemy_chain')) == attack]
            times = {}
            for key in ('search_ms', 'wait_ms'):
                values = sorted(r[key] for r in plans if isinstance(r.get(key), (int, float)))
                times[key] = dict(zip(('median', 'p90', 'maximum'),
                    (round(values[int((len(values)-1)*p)], 2) for p in (.5, .9, 1)))) if values else None
            groups[f'{mode}_enemy_chain_{attack}'] = dict(count=len(plans),
                cache=dict(Counter(r.get('cache') for r in plans)), **times)
    opening = [r for r in rows if r.get('auto') == 'planning' and r.get('decision_identity')
               and r['decision_identity'].get('piece_id') == 0 and r.get('mode') == 'normal']
    opening_waits = sorted(r['wait_ms'] for r in opening if isinstance(r.get('wait_ms'), (int, float)))
    opening_summary = dict(count=len(opening), cache=dict(Counter(r.get('cache') for r in opening)),
        wait_min_ms=min(opening_waits, default=None), wait_max_ms=max(opening_waits, default=None))
    return dict(opening=opening_summary, source=str(path), status='observed_log_not_a_controlled_speed_comparison', groups=groups,
        early_discard_reasons=dict(Counter(r.get('reason') for r in rows
            if r.get('auto') == 'planning' and r.get('cache') == 'early' and r.get('used') is False)),
        input_retries=dict(Counter(r.get('reason') for r in rows
            if r.get('auto') == 'analysis failed, retrying')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = analyze(args.log)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
