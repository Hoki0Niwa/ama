#!/usr/bin/env python3
"""Run bench_fever for several settings and summarize the results.

usage: sweep.py -o OUT_DIR [--character raffina] [--seeds 1001-1040] [--moves 100] [--jobs 2]
                NAME[:key=value,...] [NAME[:key=value,...] ...]

A key is a weight of the base set (config.json "fever", else "build"), or one of the bench_fever
environment settings: width, depth, trigger, goal, visible, panic_count, panic_chain, panic_step, shave. For example

    sweep.py -o bin/t6 base t15:trigger=15 side:trigger=15,side=50

Each setting writes OUT_DIR/NAME.tsv, .txt (snapshots) and .jsonl (moves). An existing NAME.tsv with
every seed is reused, so a sweep can be extended without replaying. `--summary` only prints.
"""
import argparse
import json
import os
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path(os.environ.get('AMA_FEVER_BENCH', ROOT / 'bin/bench_fever/bench_fever.exe'))
ENV = {'width': 'BEAM_WIDTH', 'depth': 'BEAM_DEPTH', 'trigger': 'BEAM_TRIGGER', 'goal': 'BENCH_GOAL',
       'visible': 'QUEUE_VISIBLE', 'panic_count': 'PANIC_COUNT', 'panic_chain': 'PANIC_CHAIN',
       'shave': 'SHAVE_CHAIN', 'plain_pairs': 'PLAIN_PAIRS', 'margin': 'MARGIN', 'patience': 'PATIENCE', 'patience_step': 'PATIENCE_STEP', 'panic_step': 'PANIC_STEP'}


def load(path):
    return [line.split('\t') for line in path.read_text().splitlines()] if path.is_file() else []


def run(out, name, settings, base, character, seeds, moves):
    tsv = out / f'{name}.tsv'
    if len(load(tsv)) == seeds[1] - seeds[0]:
        return
    weights = dict(base)
    environment = dict(os.environ)
    for key, value in settings.items():
        if key in ENV:
            environment[ENV[key]] = value
        elif key in weights:
            weights[key] = int(value)
        else:
            raise SystemExit(f'unknown setting "{key}"')
    for suffix in ('tsv', 'txt', 'jsonl', 'json'):
        (out / f'{name}.{suffix}').unlink(missing_ok=True)
    (out / f'{name}.json').write_text(json.dumps(weights))
    subprocess.run([str(BENCH), str(out / f'{name}.json'), character, str(seeds[0]), str(seeds[1]), str(tsv),
                    str(moves), str(out / f'{name}.txt'), str(out / f'{name}.jsonl')],
                   env=environment, check=True, capture_output=True)


def summarize(name, rows):
    """One line per setting. A game's chain is its longest one; a dead game still counts as played."""
    if not rows:
        return f'{name:<24} no result'
    chains = [int(r[5]) for r in rows]
    fired = [r for r in rows if r[2] == 'fired']
    rate = lambda goal: 100 * sum(c >= goal for c in chains) / len(rows)
    moves = statistics.mean(int(r[6]) for r in fired) if fired else 0
    ms = sum(int(r[8]) for r in rows) / max(1, sum(int(r[6]) for r in rows))
    return (f'{name:<24} n={len(rows):<4} chain {statistics.mean(chains):5.2f}  '
            f'>=10 {rate(10):5.1f}%  >=12 {rate(12):5.1f}%  >=13 {rate(13):5.1f}%  >=14 {rate(14):5.1f}%  '
            f'>=15 {rate(15):5.1f}%  dead {sum(r[2] == "dead" for r in rows):<3} '
            f'other {sum(r[2] in ("timeout", "nomove") for r in rows):<3} moves {moves:5.1f}  '
            f'small {statistics.mean(int(r[12]) for r in rows):4.2f}  ms/move {ms:5.0f}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-o', '--out', required=True)
    parser.add_argument('--character', default='raffina')
    parser.add_argument('--seeds', default='1001-1040', help='inclusive range')
    parser.add_argument('--moves', type=int, default=100)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--summary', action='store_true')
    parser.add_argument('settings', nargs='+')
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    begin, end = map(int, args.seeds.split('-'))
    config = json.loads((ROOT / 'config.json').read_text())
    base = config.get('fever', config['build'])

    jobs = []
    for spec in args.settings:
        name, _, text = spec.partition(':')
        settings = dict(item.split('=') for item in text.split(',')) if text else {}
        jobs.append((name, settings))

    if not args.summary:
        with ThreadPoolExecutor(args.jobs) as pool:
            for future in [pool.submit(run, out, name, settings, base, args.character, (begin, end + 1), args.moves)
                           for name, settings in jobs]:
                future.result()

    for name, _ in jobs:
        print(summarize(name, load(out / f'{name}.tsv')))


if __name__ == '__main__':
    main()
