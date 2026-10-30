"""Small clears made while building the first main, through protocol 3 (the live decision path).

python tools/bench_fever_single_clear.py --native bin/fever_battle/fever_battle.exe --solo bin/fever/fever.exe \
    --character rafisol --seeds 1-20 --output out.json

Plays each seed until a chain of --main links or more, death, or --limit pieces. Every clear below that is
recorded with the board's puyo count before the piece, the reply's reason and the nuisance the clear would send
at target point 120 (score // 120, carry and margin time ignored). A "leveling" clear is one of 1-2 links that
sends less than --min-sent. Prototype colour model, an idle opponent (empty normal board, gauge 6, no main yet),
no input and no clock: what the build does to itself, not what the clear does to an opponent or a battle result.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))
from fever_battle import mode_engine  # noqa: E402
from bench_fever_normal_build import side  # noqa: E402


def cells(field):
    return sum(c not in '.' for row in field for c in row)


def run(engine, character, seed, options, main, limit, min_sent):
    queue = engine.native.ask(dict(op='queue', character=character, seed=seed, count=limit+3))['queue']
    own, enemy = side(character), side(character)
    enemy['queue'] = queue[:3]
    enemy['gauge'] = 6
    # An opponent still building its first main: the time a clear that sends nothing leaves it.
    enemy['normal_chain_max'] = 0
    own['normal_chain_max'] = 0
    clears, slowest, since, times = [], 0.0, 0, []
    reasons = {}
    for move in range(limit):
        own.update(queue=queue[move:move+3], dropset_index=move % 16, piece_id=move, moves_since_chain=since)
        own['observed_frame'] = enemy['observed_frame'] = move
        request = dict(protocol_version=3, rule='fever_battle', match_id=f'single-{character}-{seed}', frame=move,
            observation=dict(frame_before=move, frame_after=move, match_status='running'), target_point=120,
            gauge_gain_on_offset=1, clock_policy=dict(count_chain_frames=True), self=own, enemy=enemy,
            solo_options=options)
        started = time.monotonic()
        reply = engine.answer(request)
        slowest = max(slowest, time.monotonic()-started)
        times.append(dict(ms=round((time.monotonic()-started)*1000), cells=cells(own['field'])))
        if 'error' in reply or reply.get('action') != 'place':
            return dict(seed=seed, end=reply.get('error', reply.get('reason')), moves=move, main=0, clears=clears,
                        reasons=reasons, slowest_ms=round(slowest*1000), times=times)
        reasons[reply['reason']] = reasons.get(reply['reason'], 0) + 1
        result = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                        x=reply['x'], r=reply['r']))
        links = len(result['links'])
        if links >= main:
            return dict(seed=seed, end='main', moves=move+1, main=links, cells=cells(own['field']), clears=clears,
                        reasons=reasons, slowest_ms=round(slowest*1000), times=times)
        if links:
            sent = sum(engine.scoring.chain(character, result['links'])) // 120
            # An all clear's bonus is not in `sent`; the tactic is reported but not counted as leveling.
            clears.append(dict(move=move, links=links, sent=sent, cells=cells(own['field']), reason=reply['reason'],
                               fire=bool(reply.get('fire')),
                               leveling=links <= 2 and sent < min_sent and not result['all_clear']))
        if result['dead']:
            return dict(seed=seed, end='dead', moves=move+1, main=0, clears=clears, reasons=reasons,
                        slowest_ms=round(slowest*1000), times=times)
        own['normal_chain_max'] = max(own['normal_chain_max'], links)
        if links >= engine.policy['reset_moves_at_chain']:
            since = 0
        else:
            since += 1
        own['field'] = result['field']
    return dict(seed=seed, end='limit', moves=limit, main=0, clears=clears, reasons=reasons,
                slowest_ms=round(slowest*1000), times=times)


def summarize(rows):
    mains = [r['main'] for r in rows if r['end'] == 'main']
    leveling = [sum(c['leveling'] for c in r['clears']) for r in rows]
    return dict(games=len(rows), main=len(mains), dead=sum(r['end'] == 'dead' for r in rows),
        limit=sum(r['end'] == 'limit' for r in rows), other=sum(r['end'] not in ('main', 'dead', 'limit') for r in rows),
        main_mean=round(statistics.mean(mains), 2) if mains else 0,
        main_13=sum(m >= 13 for m in mains), main_10=sum(m >= 10 for m in mains),
        leveling=sum(leveling), games_leveling=sum(n > 0 for n in leveling),
        sending=sum(not c['leveling'] for r in rows for c in r['clears']),
        sent=sum(c['sent'] for r in rows for c in r['clears']),
        moves_mean=round(statistics.mean(r['moves'] for r in rows), 2),
        slowest_ms=max(r['slowest_ms'] for r in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--solo', type=Path, default=ROOT/'bin/fever/fever.exe')
    parser.add_argument('--config', type=Path, default=ROOT/'config.json')
    parser.add_argument('--character', default='rafisol')
    parser.add_argument('--seeds', default='1-20', help='first-last, inclusive')
    parser.add_argument('--width', type=int, default=250)
    parser.add_argument('--depth', type=int, default=16)
    parser.add_argument('--main', type=int, default=8, help='links that end the game as the first main')
    parser.add_argument('--limit', type=int, default=80)
    parser.add_argument('--min-sent', type=int, default=6)
    parser.add_argument('--policy', type=Path, help='battle policy JSON to use instead of data/fever/battle_policy.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    first, last = map(int, args.seeds.split('-'))
    engine = mode_engine.ModeBattleEngine(args.native, args.solo, args.config)
    if args.policy:
        engine.policy = json.loads(args.policy.read_text(encoding='utf-8'))
    try:
        rows = []
        for seed in range(first, last+1):
            rows.append(run(engine, args.character, seed, dict(beam_width=args.width, beam_depth=args.depth),
                            args.main, args.limit, args.min_sent))
            print(json.dumps({k: v for k, v in rows[-1].items() if k not in ('clears', 'times')}
                             | dict(leveling=sum(c['leveling'] for c in rows[-1]['clears']))), flush=True)
    finally:
        engine.close()
    summary = dict(character=args.character, seeds=args.seeds, width=args.width, depth=args.depth,
                   main_links=args.main, min_sent=args.min_sent, policy=str(args.policy or 'default'),
                   native=str(args.native), **summarize(rows))
    print(json.dumps(summary))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(summary=summary, runs=rows,
            status='offline_prototype_colour_model_idle_opponent'), indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
