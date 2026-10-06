"""Measure known NEXT counts on the same solo queues, with resumable per-seed results.

NEXT counts include the current pair. The benchmark receives the actual future
queue, so this measures perfect information rather than a color-bag predictor.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = (
    'BEAM_WIDTH', 'BEAM_DEPTH', 'BEAM_TRIGGER', 'BEAM_TARGET', 'BEAM_ZORO',
    'FIRE_GUARD', 'FIRE_GUARD_FIRE', 'FIRE_GUARD_COUNT', 'FIRE_GUARD_SCORE',
    'FIRE_GUARD_KEEP', 'FIRE_PANIC_COUNT', 'QUEUE_VISIBLE',
)


def read_case(path, seed):
    if not path.is_file():
        return None
    lines = path.read_text().splitlines()
    if len(lines) != 1:
        return None
    row = lines[0].split('\t')
    if len(row) != 19 or int(row[0]) != seed:
        return None
    return row


def statistics_for(rows):
    games = [rows[seed] for seed in sorted(rows)]
    fired = [row for row in games if row[1] == 'fired']
    total_moves = sum(int(row[5]) for row in games)
    total_game_ms = sum(int(row[7]) for row in games)
    return dict(
        games=len(games), fired=len(fired),
        over130=sum(int(row[2]) >= 130000 for row in games),
        over150=sum(int(row[2]) >= 150000 for row in games),
        non_firing=len(games) - len(fired),
        mean_score=statistics.mean(int(row[2]) for row in games),
        mean_fired_score=statistics.mean(int(row[2]) for row in fired) if fired else None,
        mean_single_clears=statistics.mean(int(row[16]) for row in games),
        mean_small_clears=statistics.mean(int(row[15]) for row in games),
        max_single_clears=max(int(row[16]) for row in games),
        mean_moves=statistics.mean(int(row[5]) for row in games),
        mean_fired_moves=statistics.mean(int(row[5]) for row in fired) if fired else None,
        total_game_ms=total_game_ms, total_moves=total_moves,
        approx_ms_per_move=total_game_ms / total_moves if total_moves else None,
        max_decision_ms=max(int(row[8]) for row in games),
    )


def write_atomic(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--next-counts', type=int, nargs='+', default=[3, 6, 12, 16])
    parser.add_argument('--seed-begin', type=int, default=0)
    parser.add_argument('--seeds', type=int, default=40)
    parser.add_argument('--width', type=int, default=250)
    parser.add_argument('--depth', type=int, default=16)
    parser.add_argument('--trigger', type=int, default=130000)
    parser.add_argument('--max-moves', type=int, default=100)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if args.seeds <= 0 or args.jobs <= 0 or args.width <= 0 or args.max_moves <= 0:
        parser.error('seeds, jobs, width and max-moves must be positive')
    if not 2 <= args.depth <= 128 or any(not 2 <= n <= args.depth for n in args.next_counts):
        parser.error('NEXT counts must be between 2 and the depth; depth must be 2..128')
    counts = list(dict.fromkeys(args.next_counts))
    executable = args.exe.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = ROOT / 'bin/bench/next-count-20261005/cases' / output.name
    cases.mkdir(parents=True, exist_ok=True)
    weights = json.loads(args.config.read_text(encoding='utf-8'))['build']
    manifest = dict(
        seed_begin=args.seed_begin, seeds=args.seeds, next_counts=counts,
        width=args.width, depth=args.depth, trigger=args.trigger,
        target=0, zoro=False, panic_count=74, max_moves=args.max_moves,
        stop_score=78000, jobs=args.jobs, weights=weights,
        binary_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        information='Actual queue supplied; known pair count includes current pair.',
        search='Six sampled tails below depth; one beam search when the horizon is fully known. Sampled tails have exactly the requested length.',
        timing=('Serial runs; game wall-clock time divided by moves approximates decision time.'
                if args.jobs == 1 else
                'Concurrent runs; wall-clock timings are not used for speed claims.'),
    )
    manifest_path = output / 'manifest.json'
    if manifest_path.is_file() and json.loads(manifest_path.read_text()) != manifest:
        parser.error('output already belongs to a different experiment; use a new directory')
    write_atomic(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    weight_path = output / 'build.json'
    write_atomic(weight_path, json.dumps(weights, indent=2) + '\n')
    results = {count: {} for count in counts}
    seeds = range(args.seed_begin, args.seed_begin + args.seeds)
    pending = []
    for seed in seeds:
        for count in counts:
            case = cases / f'next-{count}-seed-{seed}.tsv'
            row = read_case(case, seed)
            if row is not None:
                results[count][seed] = row
            else:
                pending.append((count, seed))

    def save():
        summary = {}
        for count, rows in results.items():
            if not rows:
                continue
            write_atomic(output / f'next-{count}.tsv', ''.join(
                '\t'.join(rows[seed]) + '\n' for seed in sorted(rows)))
            write_atomic(output / f'next-{count}-fields.txt', ''.join(
                (cases / f'next-{count}-seed-{seed}-fields.txt').read_text()
                for seed in sorted(rows)))
            summary[str(count)] = statistics_for(rows)
        write_atomic(output / 'summary.json', json.dumps(summary, indent=2) + '\n')

    def run_case(count, seed):
        destination = cases / f'next-{count}-seed-{seed}.tsv'
        # Incomplete attempts are rerun without appending to their partial rows.
        destination.write_text('')
        field_path = cases / f'next-{count}-seed-{seed}-fields.txt'
        field_path.write_text('')
        environment = dict(os.environ)
        for key in OVERRIDES:
            environment.pop(key, None)
        environment.update(BEAM_WIDTH=str(args.width), BEAM_DEPTH=str(args.depth),
                           BEAM_TRIGGER=str(args.trigger), BEAM_TARGET='0', BEAM_ZORO='0',
                           FIRE_GUARD='0', FIRE_PANIC_COUNT='74', QUEUE_VISIBLE=str(count))
        result = subprocess.run(
            [str(executable), str(weight_path), str(seed), str(seed + 1), str(destination),
             str(args.max_moves), str(field_path)],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)
        (cases / f'next-{count}-seed-{seed}.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'NEXT {count}, seed {seed}: {result.stdout}{result.stderr}')
        row = read_case(destination, seed)
        if row is None:
            raise RuntimeError(f'NEXT {count}, seed {seed}: invalid benchmark result')
        return count, seed, row

    save()
    print(f'Resuming {sum(map(len, results.values()))}/{args.seeds * len(counts)} completed games', flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_case, count, seed) for count, seed in pending]
        for future in as_completed(futures):
            count, seed, row = future.result()
            results[count][seed] = row
            save()
            completed = sum(map(len, results.values()))
            if completed % 8 == 0 or completed == args.seeds * len(counts):
                print(f'{completed}/{args.seeds * len(counts)} games completed', flush=True)
    print(json.dumps({str(n): statistics_for(rows) for n, rows in results.items()}, indent=2), flush=True)


if __name__ == '__main__':
    main()
