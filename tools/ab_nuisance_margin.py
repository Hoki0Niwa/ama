"""Seat-against-seat comparison of the normal board's nuisance-check margin, in the independent simulator.

python tools/ab_nuisance_margin.py --sim-root C:\\Users\\ho_ki\\git\\fever-simulator --matches 100 --workers 8 \\
    --margins 10 0 --output results.json

Each seed is played twice with the same two characters, swapping which seat gets which margin
(`timing.nuisance_check_margin` of data/fever/battle_policy.json, set per seat before every answer), so a
margin is measured against the other margin on both characters. `--policy-high a.b=value` puts a policy
value (for example `normal_build.retain_fire_chain=12`) on the engine of the `high` seat only; with equal
margins the two seats then differ in that value alone. Per game it records the winner and, per
seat, the nuisance that fell (`stats.dropped`), the drops (`drop` events with a count) and how many of those
followed a piece that was split, from the simulator's own events.

The simulator is an offline approximation of the game (its README and docs/VALIDATION.md list what is not
matched): a difference here is a reading of this engine against itself, not a result in the game.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


class Seat:
    """An Ama engine that puts its own margin on the module-wide setting before each answer."""
    def __init__(self, engine, margin, timing, policy=None):
        self.engine, self.margin, self.timing = engine, margin, timing
        for path, value in (policy or {}).items():
            node = engine.policy
            *keys, last = path.split('.')
            for key in keys:
                node = node[key]
            node[last] = value

    def answer(self, request):
        self.timing.set_normal_check_margin(self.margin)
        return self.engine.answer(request)

    def close(self):
        self.engine.close()


def play(job):
    sim_root = Path(job['sim_root'])
    sys.path[:0] = [str(ROOT), str(sim_root/'tools')]
    from fever_battle.mode_engine import ModeBattleEngine
    from fever_battle import timing
    from ama_selfplay import run_game
    from client import Simulator
    scenario = json.loads(Path(job['scenario']).read_text(encoding='utf-8'))
    scenario.setdefault('options', {}).update(max_moves=500, color_model='steam_seed32', trace=True, training_stream=0)
    settings = dict(solo_options=dict(beam_width=job['width'], beam_depth=8),
                    seed_options=dict(max_nodes=8000, budget_ms=50), gauge_gain=scenario['options'].get('gauge_gain', 1))
    native = str(ROOT/'bin/fever_battle/fever_battle.exe')
    config = str(ROOT/'config.json')
    engines = [Seat(ModeBattleEngine(native, str(ROOT/'bin/fever/fever.exe'), config), m, timing,
                    job.get('policy_high') if seat == job['high_seat'] else None)
               for seat, m in enumerate(job['margins'])]
    try:
        with Simulator() as sim:
            game = run_game(engines, sim, job['seed'], scenario, settings, f"ab-{job['seed']}-{job['order']}")
            recording = sim.ask('recording')
    finally:
        for engine in engines:
            engine.close()
    events = recording['events']
    last_lock = {}
    seats = []
    # the first chain of 8 or more links a player ended before entering Fever: its first main chain
    entered, first_main = set(), {}
    for event in events:
        if event['type'] == 'enter':
            entered.add(event.get('player'))
        elif event['type'] == 'end' and event.get('player') not in entered and event['player'] not in first_main                 and event.get('length', 0) >= 8:
            first_main[event['player']] = event['length']
    for seat in (0, 1):
        seats.append(dict(margin=job['margins'][seat], dropped=0, drop_events=0, drops_after_split=0, drop_30=0,
                          first_main=first_main.get(seat)))
    for event in events:
        p = event.get('player')
        if event['type'] == 'lock':
            last_lock[p] = event
        elif event['type'] == 'drop' and event.get('count', 0) > 0:
            seats[p]['dropped'] += event['count']
            seats[p]['drop_events'] += 1
            seats[p]['drop_30'] += event['count'] >= 30
            seats[p]['drops_after_split'] += (last_lock.get(p) or {}).get('split_distance', 0) > 0
    final = game['final']
    return dict(seed=job['seed'], order=job['order'], margins=job['margins'], high_seat=job['high_seat'], result=final['result'],
                winner=final['winner'], frame=final['frame'], seats=seats,
                characters=[p.get('character') for p in final['players']],
                stats=[final['players'][s]['stats'] for s in (0, 1)], decisions=game['decisions'])


def summarize(games, low, high):
    """Counts for the `high` side (the first seat of order 0, the second of order 1) against the other."""
    out = Counter()
    per = defaultdict(Counter)
    for g in games:
        if g['result'] != 'finished':
            out['unfinished'] += 1
            continue
        hi = g['high_seat']
        lo = 1 - hi
        out['games'] += 1
        out['wins_high'] += g['winner'] == hi
        out['wins_low'] += g['winner'] == lo
        for name, side in (('high', hi), ('low', lo)):
            s = g['seats'][side]
            for key in ('dropped', 'drop_events', 'drops_after_split', 'drop_30'):
                per[name][key] += s[key]
            per[name]['moves'] += g['stats'][side]['moves']
            per[name]['sent'] += g['stats'][side]['sent']
            per[name]['cancelled'] += g['stats'][side]['cancelled']
            first = s.get('first_main')
            per[name]['first_main_fired'] += first is not None
            per[name]['first_main_12plus'] += (first or 0) >= 12
            per[name]['first_main_below_12'] += first is not None and first < 12
        out['frames'] += g['frame']
    return out, per


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sim-root', type=Path, required=True)
    parser.add_argument('--matches', type=int, default=50, help='seeds; each is played in both seat orders')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--margins', type=int, nargs=2, default=[10, 0], metavar=('HIGH', 'LOW'))
    parser.add_argument('--width', type=int, default=100)
    parser.add_argument('--policy-high', nargs='*', default=[], metavar='PATH=VALUE',
                        help='policy values for the high seat only, e.g. normal_build.retain_fire_chain=12')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--scenario', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    high, low = args.margins
    scenario = str((args.scenario or args.sim_root/'data/standard_mod.json').resolve())
    policy_high = {k: json.loads(v) for k, v in (item.split('=', 1) for item in args.policy_high)}
    jobs = []
    for i in range(args.matches):
        for order, margins in enumerate(([high, low], [low, high])):
            jobs.append(dict(sim_root=str(args.sim_root.resolve()), scenario=scenario, seed=args.seed + i, order=order,
                             margins=margins, width=args.width, high_seat=order, policy_high=policy_high))
    games, started = [], time.perf_counter()
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(play, job) for job in jobs]
        for done, future in enumerate(as_completed(futures), 1):
            try:
                games.append(future.result())
            except Exception as error:      # a failed game is reported, not hidden
                games.append(dict(result='error', error=repr(error)))
            if done % 20 == 0:
                print(f'{done}/{len(jobs)} games, {time.perf_counter()-started:.0f}s', flush=True)
    ok = [g for g in games if g.get('result') != 'error']
    out, per = summarize(ok, low, high)
    report = dict(margins=dict(high=high, low=low), games=len(games), errors=len(games) - len(ok), totals=dict(out),
                  per_side={k: dict(v) for k, v in per.items()}, wall_seconds=round(time.perf_counter() - started, 1))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.output:
        args.output.write_text(json.dumps(dict(report=report, games=games), ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
