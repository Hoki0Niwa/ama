"""Two offline measurements through protocol 3, as a baseline for search changes.

python tools/bench_fever_baseline.py seed  --output REPORT.json
python tools/bench_fever_baseline.py entry --output REPORT.json

seed:  each public reference seed is played on a Fever board with the pieces
       of the prototype colour model, until its first clear or the clock ends.
entry: a normal board is built while a scripted opponent adds a few confirmed
       nuisance every few pieces; the run ends on gauge 7, death or the limit.

Prototype colour model and modelled clocks, no opponent board and no input:
neither figure is a live success rate or a battle result.
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
from fever_battle import mode_engine
from fever_battle.model import EMPTY, convert, drop_garbage
from fever_battle.timing import ChainTiming


def side(character):
    return dict(character=character, field=list(EMPTY), mode='normal', gauge=0,
        observed_frame=0, phase='controllable', moves_since_chain=0, dropset_index=0, piece_id=0,
        queue=[], confirmed=0, unconfirmed=0, remainder=0, garbage_phase=0,
        mode_generation=0, seed_id=0, prepared_frames=900, remaining_frames=0, clock_running=False,
        seed_base=5, seed_chain=5, stored_field=None, normal_confirmed=0, normal_unconfirmed=0,
        fever_confirmed=0, fever_unconfirmed=0)


def request(name, move, own, enemy, gain):
    own['observed_frame'] = enemy['observed_frame'] = move
    return dict(protocol_version=3, rule='fever_battle', match_id=name, frame=move,
        observation=dict(frame_before=move, frame_after=move, match_status='running'), target_point=120,
        gauge_gain_on_offset=gain, clock_policy=dict(count_chain_frames=True), self=own, enemy=enemy)


def seed_run(engine, character, seed, colours, start, clock, limit=24):
    """One seed, from its first piece to its first clear."""
    timing = ChainTiming.for_mode('fever')
    queue = engine.native.ask(dict(op='queue', character=character, seed=colours, count=start+limit+3))['queue']
    own, enemy = side(character), side(character)
    enemy['queue'] = queue[:3]
    own.update(mode='fever', gauge=7, field=seed['field'], stored_field=list(EMPTY), clock_running=True,
        remaining_frames=clock, seed_base=seed['seed_chain'], seed_chain=seed['seed_chain'], mode_generation=1, seed_id=1)
    row = dict(seed=seed['id'], target=seed['seed_chain'], colours=colours, start=start)
    slowest = 0.0
    for move in range(limit):
        index = start + move
        own.update(queue=queue[index:index+3], dropset_index=index % 16, piece_id=index, moves_since_chain=move)
        started = time.monotonic()
        reply = engine.answer(request(f'seed-{seed["id"]}-{colours}-{start}', move, own, enemy, 1))
        slowest = max(slowest, time.monotonic()-started)
        if 'error' in reply or reply.get('action') != 'place':
            return dict(row, end=reply.get('error', reply.get('reason')), chain=0, placements=move)
        result = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                        x=reply['x'], r=reply['r']))
        used = clock - own['remaining_frames']
        if result['links']:
            chain = len(result['links'])
            return dict(row, end='fire', chain=chain, success=chain >= seed['seed_chain'],
                over=chain - seed['seed_chain'], all_clear=result['all_clear'], placements=move+1,
                frames_to_fire=used + reply.get('seed_forecast', {}).get('choice', {}).get('fire_at', 0),
                slowest_ms=round(slowest*1000))
        if result['dead']:
            return dict(row, end='dead', chain=0, placements=move+1)
        split = timing.split_extra_frames[max(result['split_distances'], default=0)]
        own['remaining_frames'] = max(0, own['remaining_frames'] - timing.placement_frames - timing.spawn_frames - split)
        own['field'] = result['field']
        if not own['remaining_frames']:
            return dict(row, end='clock', chain=0, placements=move+1)
    return dict(row, end='limit', chain=0, placements=limit)


def seed_bench(engine, args):
    reference = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
    rows = [seed_run(engine, args.character, seed, colours, start, args.clock)
            for seed in reference['seeds'] for colours in range(1, args.queues+1)
            for start in (0, 5, 11)]
    fired = [r for r in rows if r['end'] == 'fire']
    wins = [r for r in fired if r['success']]
    ends = {}
    for r in rows:
        ends[r['end']] = ends.get(r['end'], 0) + 1
    by_target = {}
    for r in rows:
        total, ok = by_target.get(r['target'], (0, 0))
        by_target[r['target']] = (total+1, ok+bool(r.get('success')))
    summary = dict(character=args.character, clock=args.clock, samples=len(rows), ends=ends,
        success=len(wins), success_rate=round(len(wins)/len(rows), 4),
        mean_placements_on_success=round(statistics.mean(r['placements'] for r in wins), 2) if wins else None,
        mean_frames_to_fire_on_success=round(statistics.mean(r['frames_to_fire'] for r in wins), 1) if wins else None,
        mean_links_over_target_on_success=round(statistics.mean(r['over'] for r in wins), 2) if wins else None,
        all_clears=sum(bool(r.get('all_clear')) for r in fired),
        success_by_target={str(k): dict(samples=t, success=s) for k, (t, s) in sorted(by_target.items())},
        slowest_ms=max((r.get('slowest_ms', 0) for r in rows), default=0))
    return summary, rows


def entry_run(engine, character, colours, args, limit=90):
    """Build on a normal board while nuisance arrives; stop at gauge 7."""
    queue = engine.native.ask(dict(op='queue', character=character, seed=colours, count=limit+3))['queue']
    own, enemy = side(character), side(character)
    enemy['queue'] = queue[:3]
    row = dict(colours=colours)
    reasons, offsets, dropped, biggest, since_chain, slowest = {}, 0, 0, 0, 0, 0.0
    first_attack = None
    for move in range(limit):
        if move >= args.start and (move - args.start) % args.every == 0:
            own['confirmed'] += args.amount
            first_attack = move if first_attack is None else first_attack
        own['normal_confirmed'] = own['confirmed']
        own.update(queue=queue[move:move+3], dropset_index=move % 16, piece_id=move, moves_since_chain=since_chain)
        started = time.monotonic()
        try:
            reply = engine.answer(request(f'entry-{colours}', move, own, enemy, 1))
        except ValueError as error:      # the engine found no placement that survives
            reply = dict(error=str(error))
        slowest = max(slowest, time.monotonic()-started)
        if 'error' in reply or reply.get('action') != 'place':
            return dict(row, end='dead' if 'no placement survives' in reply.get('error', '') else
                reply.get('error', reply.get('reason')), moves=move, gauge=own['gauge'], reasons=reasons)
        reasons[reply['reason']] = reasons.get(reply['reason'], 0) + 1
        result = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                        x=reply['x'], r=reply['r']))
        if result['dead']:
            return dict(row, end='dead', moves=move+1, gauge=own['gauge'], reasons=reasons)
        board = result['field']
        since_chain += 1
        if result['links']:
            biggest = max(biggest, len(result['links']))
            if len(result['links']) >= engine.policy['reset_moves_at_chain']:
                since_chain = 0
            for point in engine.scoring.chain(character, result['links']):
                amount, own['remainder'], _ = convert(point, own['remainder'], 120, own['confirmed'])
                taken = min(own['confirmed'], amount)
                own['confirmed'] -= taken
                if taken:
                    offsets += 1
                    own['gauge'] = min(7, own['gauge'] + 1)
            if own['gauge'] == 7:
                return dict(row, end='entry', moves=move+1, moves_after_first_attack=move+1-first_attack,
                    offset_links=offsets, dropped=dropped, biggest_chain=biggest, reasons=reasons,
                    board_cells=sum(c != '.' for r in board for c in r), slowest_ms=round(slowest*1000))
        elif own['confirmed']:
            count = min(30, own['confirmed'])
            board, _ = drop_garbage(board, count, own['garbage_phase'])
            own['confirmed'] -= count
            own['garbage_phase'] = (own['garbage_phase'] + count) % 6
            dropped += count
            if board[2][2] != '.' or board[2][3] != '.':
                return dict(row, end='dead', moves=move+1, gauge=own['gauge'], reasons=reasons, dropped=dropped)
        own['field'] = board
    return dict(row, end='limit', moves=limit, gauge=own['gauge'], offset_links=offsets, dropped=dropped,
                biggest_chain=biggest, reasons=reasons)


def entry_bench(engine, args):
    rows = [entry_run(engine, args.character, colours, args) for colours in range(1, args.queues+1)]
    entered = [r for r in rows if r['end'] == 'entry']
    ends = {}
    for r in rows:
        ends[r['end']] = ends.get(r['end'], 0) + 1
    summary = dict(character=args.character, attack=dict(start=args.start, every=args.every, amount=args.amount),
        samples=len(rows), ends=ends, entry_rate=round(len(entered)/len(rows), 4),
        mean_moves_after_first_attack=round(statistics.mean(r['moves_after_first_attack'] for r in entered), 2) if entered else None,
        mean_dropped_before_entry=round(statistics.mean(r['dropped'] for r in entered), 2) if entered else None,
        mean_gauge_when_not_entered=round(statistics.mean(r['gauge'] for r in rows if r['end'] != 'entry'), 2)
            if len(entered) < len(rows) else None,
        slowest_ms=max((r.get('slowest_ms', 0) for r in rows), default=0))
    return summary, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('bench', choices=('seed', 'entry'))
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--solo', type=Path, default=ROOT/'bin/fever/fever.exe')
    parser.add_argument('--character', default='raffina')
    parser.add_argument('--queues', type=int, default=4, help='colour sequences per condition')
    parser.add_argument('--clock', type=int, default=900, help='seed: frames on the Fever clock at the first piece')
    parser.add_argument('--start', type=int, default=12, help='entry: piece at which nuisance first arrives')
    parser.add_argument('--every', type=int, default=3, help='entry: pieces between arrivals')
    parser.add_argument('--amount', type=int, default=4, help='entry: confirmed nuisance per arrival')
    parser.add_argument('--objective', choices=('mainline', 'fever_aim'),
                        help='entry: normal build objective, in place of the policy file')
    parser.add_argument('--tactics', choices=('ladder', 'unified'),
                        help='entry: how a threat on the normal board is answered, in place of the policy file')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    engine = mode_engine.ModeBattleEngine(args.native, args.solo, ROOT/'config.json')
    if args.tactics:
        engine.policy['normal_tactics']['mode'] = args.tactics
    if args.objective:
        engine.policy['normal_build']['objective'] = args.objective
    try:
        summary, rows = (seed_bench if args.bench == 'seed' else entry_bench)(engine, args)
    finally:
        engine.close()
    summary.update(bench=args.bench, objective=engine.policy['normal_build']['objective'],
                   tactics=engine.policy['normal_tactics']['mode'], native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
                   solo_sha256=hashlib.sha256(args.solo.read_bytes()).hexdigest())
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.output:
        args.output.write_text(json.dumps(dict(summary=summary, runs=rows,
            status='offline_prototype_colour_model_modelled_clock_not_live'), ensure_ascii=False, indent=1)+'\n',
            encoding='utf-8')


if __name__ == '__main__':
    main()
