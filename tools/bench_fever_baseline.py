"""Two offline measurements through protocol 3, as a baseline for search changes.

python tools/bench_fever_baseline.py seed  --output REPORT.json
python tools/bench_fever_baseline.py entry --output REPORT.json
python tools/bench_fever_baseline.py fever --output REPORT.json

seed:  each public reference seed is played on a Fever board with the pieces
       of the prototype colour model, until its first clear or the clock ends.
entry: a normal board is built while a scripted opponent adds a few confirmed
       nuisance every few pieces; the run ends on gauge 7, death or the limit.
fever: one whole Fever on the model clock. Each clear is followed by the public
       reference seed of the next level (one link up on success, down on a
       failure, two more on an all clear), until the clock or the board ends it.

Prototype colour model and modelled clocks, no opponent board and no input:
neither figure is a live success rate or a battle result.
"""
import argparse
from unittest.mock import patch
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


def fever_run(engine, character, colours, args, seeds, limit=120):
    """One Fever from its first seed to the end of the clock: points, seeds and chains."""
    from fever_battle.mode import next_seed
    timing = ChainTiming.for_mode('fever')
    queue = engine.native.ask(dict(op='queue', character=character, seed=colours, count=limit+3))['queue']
    kinds = sorted({s['kind'] for s in seeds})
    def seed_of(level, number):
        for shift in range(len(kinds)):
            found = next((s for s in seeds if s['kind'] == kinds[(number+shift) % len(kinds)]
                          and s['seed_chain'] == level), None)
            if found:
                return found
    own, enemy = side(character), side(character)
    if args.opponent == 'chain':
        # An opponent who holds a main chain: the seed is built on, not fired at once to land on them.
        enemy['field'] = next(s['field'] for s in seeds if s['seed_chain'] == 12)
    enemy['queue'] = queue[:3]
    level, number, clock = args.level, 0, args.clock
    own.update(mode='fever', gauge=7, stored_field=list(EMPTY), clock_running=True, mode_generation=1,
        field=seed_of(level, 0)['field'], seed_base=level, seed_chain=level, seed_id=1, remaining_frames=clock,
        normal_confirmed=args.held)
    row = dict(colours=colours, points=0, seeds=0, success=0, all_clears=0, chains=[], held_left=args.held)
    since = 0
    for move in range(limit):
        own.update(queue=queue[move:move+3], dropset_index=move % 16, piece_id=move, moves_since_chain=since)
        try:
            reply = engine.answer(request(f'fever-{colours}', move, own, enemy, 1))
        except ValueError as error:
            return dict(row, end=str(error), moves=move)
        if reply.get('action') != 'place':
            return dict(row, end=reply.get('reason'), moves=move)
        result = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                        x=reply['x'], r=reply['r']))
        if result['dead']:
            return dict(row, end='dead', moves=move+1)
        choice = reply['seed_forecast']['choice']
        since += 1
        if result['links']:
            points = engine.scoring.chain(character, result['links'], 'fever')
            chain = len(points)
            row['points'] += sum(points); row['seeds'] += 1; row['chains'].append(chain)
            row['success'] += chain >= level; row['all_clears'] += result['all_clear']
            for point in points:
                amount, own['remainder'], _ = convert(point, own['remainder'], 120, own['normal_confirmed'])
                own['normal_confirmed'] -= min(own['normal_confirmed'], amount)
            row['held_left'] = own['normal_confirmed']
            # The clock after the chain and its awards, by the solver's own model.
            clock = choice['remaining_after_rewards'] - timing.chain_ready_frames
            if clock <= 0 or choice['end_at'] >= own['remaining_frames']:
                return dict(row, end='clock', moves=move+1)
            level = next_seed(level, chain, result['all_clear'])
            number += 1; since = 0
            own.update(field=seed_of(level, number)['field'], seed_base=level, seed_chain=level,
                       seed_id=number+1, remaining_frames=clock)
            continue
        split = timing.split_extra_frames[max(result['split_distances'], default=0)]
        own['remaining_frames'] = max(0, own['remaining_frames'] - timing.placement_frames - timing.spawn_frames - split)
        own['field'] = result['field']
        if not own['remaining_frames']:
            return dict(row, end='clock', moves=move+1)
    return dict(row, end='limit', moves=limit)


def fever_bench(engine, args):
    seeds = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))['seeds']
    rows = [fever_run(engine, args.character, colours, args, seeds) for colours in range(1, args.queues+1)]
    ends = {}
    for r in rows:
        ends[r['end']] = ends.get(r['end'], 0) + 1
    fired = sum(r['seeds'] for r in rows)
    summary = dict(character=args.character, clock=args.clock, first_level=args.level, held=args.held,
        samples=len(rows), ends=ends, mean_points=round(statistics.mean(r['points'] for r in rows)),
        median_points=round(statistics.median(r['points'] for r in rows)),
        mean_seeds=round(fired/len(rows), 2), success_rate=round(sum(r['success'] for r in rows)/max(1, fired), 4),
        mean_longest_chain=round(statistics.mean(max(r['chains'], default=0) for r in rows), 2),
        all_clears=sum(r['all_clears'] for r in rows),
        mean_held_left=round(statistics.mean(r['held_left'] for r in rows), 1))
    return summary, rows


def entry_run(engine, character, colours, args, limit=90):
    """Build on a normal board while nuisance arrives; stop at gauge 7."""
    queue = engine.native.ask(dict(op='queue', character=character, seed=colours, count=limit+3))['queue']
    own, enemy = side(character), side(character)
    enemy['queue'] = queue[:3]
    enemy['gauge'] = 6      # one offset from Fever: nothing sent kills, so the scripted packets alone decide
    row = dict(colours=colours)
    reasons, offsets, dropped, biggest, since_chain, slowest = {}, 0, 0, 0, 0, 0.0
    first_attack = None
    longest = lambda rows: engine.native.ask(dict(op='stock', field=rows, want=7))['longest']
    built = 0       # the longest chain the board held when nuisance first arrived
    due = {}        # move at which an arrival seen earlier is confirmed
    timing = ChainTiming().native()
    piece_frames = timing['placement_frames'] + timing['spawn_frames']
    # The main chain while nuisance is pending: moves on which this piece could fire it whole
    # (within one link of the longest, four links or more), whether it was, and what it then sent.
    main = dict(could_fire=0, fired=False, fired_chain=0, fired_points=0, broken=False)
    decisions = {}
    for move in range(limit):
        if move >= args.start and (move - args.start) % args.every == 0:
            # With a warning the packet is first seen unconfirmed, as one sent by a chain still running.
            own['unconfirmed'] += args.amount
            due[move + args.warning] = due.get(move + args.warning, 0) + args.amount
            if first_attack is None:
                first_attack, built = move, longest(own['field'])
        landed = min(own['unconfirmed'], due.pop(move, 0))
        own['unconfirmed'] -= landed
        own['confirmed'] += landed
        own['normal_confirmed'], own['normal_unconfirmed'] = own['confirmed'], own['unconfirmed']
        own.update(queue=queue[move:move+3], dropset_index=move % 16, piece_id=move, moves_since_chain=since_chain)
        started = time.monotonic()
        # An unconfirmed packet comes with the end of the chain that sends it, as an observed chain gives it.
        lands = [dict(type='end', frame=(min(due) - move) * piece_frames)] if due and own['unconfirmed'] else []
        try:
            told = own if not args.unknown_phase else dict(own, garbage_phase=None, garbage_phase_status='unknown')
            with patch.object(engine, '_enemy_events', return_value=lands):
                reply = engine.answer(request(f'entry-{colours}', move, told, enemy, 1))
        except ValueError as error:      # the engine found no placement that survives
            reply = dict(error=str(error))
        slowest = max(slowest, time.monotonic()-started)
        if 'error' in reply or reply.get('action') != 'place':
            return dict(row, end='dead' if 'no placement survives' in reply.get('error', '') else
                reply.get('error', reply.get('reason')), moves=move, gauge=own['gauge'], reasons=reasons)
        reasons[reply['reason']] = reasons.get(reply['reason'], 0) + 1
        result = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                        x=reply['x'], r=reply['r']))
        if own['confirmed'] + own['unconfirmed'] and not main['fired']:
            whole = max(4, longest(own['field']) - 1)
            main['could_fire'] += any(len(p['links']) >= whole and not p['dead'] for p in engine.native.ask(
                dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements'])
            if len(result['links']) >= whole:
                main.update(fired=True, fired_chain=len(result['links']),
                            fired_points=sum(engine.scoring.chain(character, result['links'])))
            elif result['links'] and not result['dead'] and longest(result['field']) < whole:
                main['broken'] = True
        row['main'] = main
        if own['confirmed'] + own['unconfirmed']:
            # What this decision did to the main chain, as tools/analyze_fever_matches.py counts it in live logs.
            held = longest(own['field'])
            chain = len(result['links'])
            if held >= 4 and chain >= held - 1:
                what = 'main chain fired whole'
            elif held >= 4 and chain and not result['dead'] and longest(result['field']) < held - 1:
                what = 'main chain broken by a smaller clear'
            elif chain:
                what = 'smaller clear, main chain kept' if held >= 4 else 'clear, no main chain held'
            else:
                what = 'no clear'
            decisions[what] = decisions.get(what, 0) + 1
        row['decisions'] = decisions
        if result['dead']:
            return dict(row, end='dead', moves=move+1, gauge=own['gauge'], reasons=reasons)
        board = result['field']
        since_chain += 1
        if result['links']:
            biggest = max(biggest, len(result['links']))
            if len(result['links']) >= engine.policy['reset_moves_at_chain']:
                since_chain = 0
            for point in engine.scoring.chain(character, result['links']):
                amount, own['remainder'], _ = convert(point, own['remainder'], 120,
                                                      own['confirmed'] + own['unconfirmed'])
                taken = min(own['confirmed'], amount)
                own['confirmed'] -= taken
                flying = min(own['unconfirmed'], amount - taken)
                own['unconfirmed'] -= flying
                taken += flying
                if taken:
                    offsets += 1
                    own['gauge'] = min(7, own['gauge'] + 1)
            if own['gauge'] == 7:
                return dict(row, end='entry', moves=move+1, moves_after_first_attack=move+1-first_attack,
                    offset_links=offsets, dropped=dropped, biggest_chain=biggest, reasons=reasons,
                    board_cells=sum(c != '.' for r in board for c in r), slowest_ms=round(slowest*1000),
                    built_chain=built, kept_chain=longest(board), held=own['confirmed'] + own['unconfirmed'])
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
    def kind(r):
        m = r.get('main', dict(fired=False, could_fire=0))
        return 'fired_whole' if m['fired'] else 'could_fire_and_did_not' if m['could_fire'] else 'never_could_fire'
    main = {}
    for r in rows:
        end = 'dead' if r['end'] == 'dead' else 'cleared' if r.get('held') == 0 else 'held' if r['end'] == 'entry' else r['end']
        main.setdefault(kind(r), {}).setdefault(end, 0)
        main[kind(r)][end] += 1
    fired = [r['main'] for r in rows if r.get('main', {}).get('fired')]
    summary = dict(character=args.character,
        attack=dict(start=args.start, every=args.every, amount=args.amount, warning=args.warning),
        samples=len(rows), ends=ends, entry_rate=round(len(entered)/len(rows), 4),
        mean_moves_after_first_attack=round(statistics.mean(r['moves_after_first_attack'] for r in entered), 2) if entered else None,
        mean_dropped_before_entry=round(statistics.mean(r['dropped'] for r in entered), 2) if entered else None,
        mean_built_chain=round(statistics.mean(r['built_chain'] for r in entered), 2) if entered else None,
        mean_kept_chain=round(statistics.mean(r['kept_chain'] for r in entered), 2) if entered else None,
        mean_held_at_entry=round(statistics.mean(r['held'] for r in entered), 2) if entered else None,
        decisions_under_a_packet={what: sum(r.get('decisions', {}).get(what, 0) for r in rows)
            for what in sorted({k for r in rows for k in r.get('decisions', {})})},
        main_chain=main, main_chain_broken=sum(r.get('main', {}).get('broken', False) for r in rows),
        mean_fired_chain=round(statistics.mean(m['fired_chain'] for m in fired), 2) if fired else None,
        mean_fired_points=round(statistics.mean(m['fired_points'] for m in fired)) if fired else None,
        mean_gauge_when_not_entered=round(statistics.mean(r['gauge'] for r in rows if r['end'] != 'entry'), 2)
            if len(entered) < len(rows) else None,
        slowest_ms=max((r.get('slowest_ms', 0) for r in rows), default=0))
    return summary, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('bench', choices=('seed', 'entry', 'fever'))
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--solo', type=Path, default=ROOT/'bin/fever/fever.exe')
    parser.add_argument('--character', default='raffina')
    parser.add_argument('--queues', type=int, default=4, help='colour sequences per condition')
    parser.add_argument('--clock', type=int, default=900, help='seed: frames on the Fever clock at the first piece')
    parser.add_argument('--level', type=int, default=5, help='fever: chain length of the first seed')
    parser.add_argument('--held', type=int, default=0, help='fever: nuisance held for the normal board')
    parser.add_argument('--start', type=int, default=12, help='entry: piece at which nuisance first arrives')
    parser.add_argument('--every', type=int, default=3, help='entry: pieces between arrivals')
    parser.add_argument('--amount', type=int, default=4, help='entry: confirmed nuisance per arrival')
    parser.add_argument('--opponent', choices=('empty', 'chain'), default='chain',
                        help='fever: the opponent on a normal board, empty or holding a 12 chain')
    parser.add_argument('--unknown-phase', action='store_true',
                        help='entry: the engine is not told which columns take a partial row, as in live play')
    parser.add_argument('--warning', type=int, default=0,
                        help='entry: pieces an arrival stays unconfirmed before it is confirmed')
    parser.add_argument('--objective', choices=('mainline', 'fever_aim'),
                        help='entry: normal build objective, in place of the policy file')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    engine = mode_engine.ModeBattleEngine(args.native, args.solo, ROOT/'config.json')
    if args.objective:
        engine.policy['normal_build']['objective'] = args.objective
    try:
        summary, rows = dict(seed=seed_bench, entry=entry_bench, fever=fever_bench)[args.bench](engine, args)
    finally:
        engine.close()
    summary.update(bench=args.bench, objective=engine.policy['normal_build']['objective'], native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
                   solo_sha256=hashlib.sha256(args.solo.read_bytes()).hexdigest())
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.output:
        args.output.write_text(json.dumps(dict(summary=summary, runs=rows,
            status='offline_prototype_colour_model_modelled_clock_not_live'), ensure_ascii=False, indent=1)+'\n',
            encoding='utf-8')


if __name__ == '__main__':
    main()
