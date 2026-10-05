"""Causal two-engine normal-board simulation with explicit prototype timing.

All-clear seeds must be supplied from recordings; a missing seed stops the run
with awaiting_seed rather than silently ignoring the Fever-rule reward.
"""
from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path

from .engine import BattleEngine
from .model import EMPTY, ROOT, Referee, integer


def simulate(engine, characters, seed, max_moves, placement_frames, link_frames, seeds=None,
             width=40, depth=8):
    integer(seed, 'seed')
    integer(max_moves, 'max_moves', 1, 9997)  # native queue limit includes NEXT2
    integer(placement_frames, 'placement_frames', 1, 10000)
    integer(link_frames, 'link_frames', 1, 10000)
    ref = Referee(characters)
    queues = [engine.native.ask({'op': 'queue', 'character': c, 'seed': seed, 'count': max_moves + 3})['queue']
              for c in characters]
    indexes, display_indexes, events, sequence = [0, 0], [0, 0], [], 0
    seed_indexes = [0, 0]
    def schedule(frame, kind, player, **values):
        nonlocal sequence
        sequence += 1
        heapq.heappush(events, (frame, sequence, {'type': kind, 'player': player, **values}))
    for player in range(2):
        schedule(0, 'ready', player)
    decisions, result = [], 'move_limit'
    while events:
        frame, order, event = heapq.heappop(events)
        player = event['player']
        if any(not p.alive for p in ref.players):
            result = 'finished'
            break
        event.update(frame=frame, order=order)
        if event['type'] == 'ready':
            if indexes[player] >= max_moves:
                continue
            if ref.players[player].awaiting_seed:
                supplied = (seeds or {}).get(characters[player], [])
                at = seed_indexes[player]
                if at >= len(supplied):
                    result = 'awaiting_seed'
                    break
                ref.apply(dict(event, type='seed', field=supplied[at]))
                seed_indexes[player] += 1
                # Use a distinct event identity at the same frame for the move.
                schedule(frame, 'ready', player)
                continue
            sides = []
            for i, p in enumerate(ref.players):
                visible_index = indexes[i] if i == player else display_indexes[i]
                queue = queues[i][visible_index:visible_index + 3]
                phase = ('waiting_seed' if p.awaiting_seed else 'chain' if p.active_chain else
                         'placing' if any(e[2]['type'] == 'place' and e[2]['player'] == i for e in events)
                         else 'controllable')
                sides.append({'character': characters[i], 'field': p.rows, 'mode': 'normal', 'gauge': 0,
                              'observed_frame': frame, 'phase': phase,
                              'moves_since_chain': p.moves_since_chain,
                              'queue': queue, 'dropset_index': visible_index, 'piece_id': visible_index,
                              'confirmed': p.pending(True), 'unconfirmed': p.pending(False), 'remainder': p.remainder,
                              'garbage_phase': p.garbage_phase})
            request = {'protocol_version': 2, 'rule': 'fever_normal_battle', 'match_id': f'simulation-{seed}',
                       'frame': frame, 'target_point': ref.target_point, 'gauge_gain_on_offset': 0,
                       'observation': {'frame_before': frame, 'frame_after': frame, 'match_status': 'running'},
                       'self': sides[player], 'enemy': sides[1-player],
                       'solo_options': {'beam_width': width, 'beam_depth': depth}}
            try:
                choice = engine.answer(request)
            except ValueError as error:
                result = 'no_surviving_move'
                decisions.append({'player': player, 'frame': frame, 'error': str(error)})
                break
            transition = engine.native.ask({'op': 'transition', 'field': sides[player]['field'],
                                            'piece': sides[player]['queue'][0], 'x': choice['x'], 'r': choice['r']})
            chain = f'{player}:{indexes[player]}'
            display_indexes[player] = indexes[player]
            schedule(frame + placement_frames, 'place', player, result=transition, chain=chain)
            decisions.append({'player': player, 'frame': frame, 'piece': sides[player]['queue'][0], 'choice': choice})
        elif event['type'] == 'place':
            effect = ref.apply(event)
            indexes[player] += 1
            if 'chain_started' in effect:
                points = engine.scoring.chain(characters[player], event['result']['links'])
                for link, value in enumerate(points, 1):
                    schedule(frame + link_frames * link, 'link', player, chain=event['chain'], link=link, points=value)
                schedule(frame + link_frames * len(points) + 1, 'end', player, chain=event['chain'])
            else:
                schedule(frame + 1, 'ready', player)
        else:
            ref.apply(event)
            if event['type'] == 'end':
                schedule(frame + 1, 'ready', player)
    if any(not p.alive for p in ref.players):
        result = 'finished'
    return {'result': result, 'moves': indexes, 'characters': characters, 'seed': seed, 'initial_target_point': 120,
            'color_model': 'prototype_splitmix4',
            'timing': {'status': 'explicit_prototype_costs', 'placement_frames': placement_frames, 'link_frames': link_frames},
            'state': ref.snapshot(), 'events': ref.log, 'decisions': decisions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--characters', nargs=2, default=['raffina', 'schezo'])
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--max-moves', type=int, default=100)
    parser.add_argument('--placement-frames', type=int, required=True)
    parser.add_argument('--link-frames', type=int, required=True)
    parser.add_argument('--seeds', type=Path)
    parser.add_argument('--native', type=Path, default=ROOT / 'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--solo', type=Path, default=ROOT / 'bin/fever/fever.exe')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    seeds = json.loads(args.seeds.read_text(encoding='utf-8')) if args.seeds else None
    engine = BattleEngine(args.native, args.solo, args.config)
    try:
        result = simulate(engine, args.characters, args.seed, args.max_moves, args.placement_frames, args.link_frames, seeds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in result.items() if k not in ('events', 'decisions')}, ensure_ascii=False))
    finally:
        engine.close()


if __name__ == '__main__':
    main()
