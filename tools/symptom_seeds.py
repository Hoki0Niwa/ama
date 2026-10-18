"""Which game seeds showed a symptom, and the seed list that replays only those.

The seed mod (hoki0niwa.seed32, record = 1) writes one line per match to
ppmod/data/hoki0niwa.seed32/seeds_<date>_<time>.txt; the Nth match of a game run is the Nth
`round over` of the bridge session log. This joins the two and prints, per symptom, the seeds and the
`seed_list = ...` lines for ppmod/config/hoki0niwa.seed32.ini.

    python tools/symptom_seeds.py LOG SEEDS.txt [--symptom triple_loop early_fire any_triple_failure]

triple_loop         a triple piece whose placement failed nine or more times (the piece fell unoperated)
any_triple_failure  one or more failed triple placements
early_fire          the first normal-mode chain of seven or more that ended below 12 links

Only the colours follow the seed; the opponent's moves and timing are live, so a symptom may or may
not recur on its seed. tools/check_logged_unreachable.py answers the position-level question at once.
"""
import argparse
import io
import json
import re
from collections import Counter, defaultdict


def read_seeds(path):
    """match number -> seed. Columns: match, game, seed(hex), seed(dec), source, time."""
    seeds = {}
    for line in io.open(path, encoding='utf-8-sig'):
        parts = line.rstrip('\n').split('\t')
        if len(parts) >= 4 and parts[0].isdigit():
            seeds[int(parts[0])] = int(parts[3])
    return seeds


def scan(log):
    rounds = 0
    loops = defaultdict(Counter)       # round -> {piece id: failures}
    triple_failures = Counter()
    first_big = {}
    with io.open(log, 'r', encoding='utf-16', errors='replace') as handle:
        for line in handle:
            if line.startswith('{"auto": "round over"'):
                rounds += 1
            elif line.startswith('{"auto": "analysis failed, retrying"'):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                identity = row.get('decision_identity') or {}
                match = re.search(r'round-(\d+)$', identity.get('match_id', ''))
                current = int(match.group(1)) if match else rounds + 1
                if row.get('piece', '?')[0] in 'LJ' and row.get('reason', '').startswith('placement is no longer'):
                    triple_failures[current] += 1
                    loops[current][identity.get('piece_id')] += 1
            elif line.startswith('{"auto": "fire"'):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                current = rounds + 1
                if row.get('mode') == 'normal' and row.get('chain', 0) >= 7 and current not in first_big:
                    first_big[current] = row['chain']
    return dict(rounds=rounds,
                triple_loop={r: max(c.values()) for r, c in loops.items() if max(c.values()) >= 9},
                any_triple_failure=dict(triple_failures),
                early_fire={r: c for r, c in first_big.items() if c < 12})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log')
    parser.add_argument('seeds')
    parser.add_argument('--symptom', nargs='+', default=['triple_loop'],
                        choices=['triple_loop', 'any_triple_failure', 'early_fire'])
    args = parser.parse_args()
    seeds, found = read_seeds(args.seeds), scan(args.log)
    print(json.dumps(dict(rounds_in_log=found['rounds'], matches_in_seed_file=len(seeds))))
    chosen = {}
    for symptom in args.symptom:
        table = {r: seeds[r] for r in sorted(found[symptom]) if r in seeds}
        missing = [r for r in found[symptom] if r not in seeds]
        note = ' (%d rounds without a recorded seed)' % len(missing) if missing else ''
        print('%s: %d seeds%s' % (symptom, len(table), note))
        for r, seed in table.items():
            print('  round %4d  seed %6d  %s' % (r, seed, found[symptom][r]))
        chosen.update(table)
    ordered = sorted(set(chosen.values()))
    print('\n# ppmod/config/hoki0niwa.seed32.ini  [tweak]')
    print('seed_list = ' + ','.join(str(s) for s in ordered))
    print('seed_list_end = loop')
    print('reset_on_set = 1')
    print('record = 1')


if __name__ == '__main__':
    main()
