"""Uninterrupted normal-board building through protocol 3: the chain fired per seed.

python tools/bench_fever_normal_build.py --native bin/fever_battle/fever_battle.exe --seeds 8
Compares what the battle entry point builds with the solo engine's own choice.
Prototype colour model, no opponent and no input: not a battle result.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle import mode_engine
from fever_battle.model import EMPTY


def side(character, mode='normal'):
    return dict(character=character, field=list(EMPTY), mode=mode, gauge=7 if mode == 'fever' else 0,
        observed_frame=0, phase='controllable', moves_since_chain=0, dropset_index=0, piece_id=0,
        queue=[], confirmed=0, unconfirmed=0, remainder=0, garbage_phase=None, garbage_phase_status='unknown',
        mode_generation=0, seed_id=0, prepared_frames=900, remaining_frames=0, clock_running=False,
        seed_base=5, seed_chain=5, stored_field=None, normal_confirmed=0, normal_unconfirmed=0,
        fever_confirmed=0, fever_unconfirmed=0)


def run(engine, character, seed, options, pending, limit=60):
    queue = engine.native.ask(dict(op='queue', character=character, seed=seed, count=limit+3))['queue']
    own, enemy = side(character), side(character)
    enemy['queue'] = queue[:3]
    own.update(unconfirmed=pending, normal_unconfirmed=pending)
    reasons, slowest, small = {}, 0.0, 0
    for move in range(limit):
        own.update(queue=queue[move:move+3], dropset_index=move % 16, piece_id=move, moves_since_chain=move)
        own['observed_frame'] = enemy['observed_frame'] = move
        request = dict(protocol_version=3, rule='fever_battle', match_id=f'build-{seed}', frame=move,
            observation=dict(frame_before=move, frame_after=move, match_status='running'), target_point=120,
            gauge_gain_on_offset=1, clock_policy=dict(count_chain_frames=True), self=own, enemy=enemy,
            solo_options=options)
        started = time.monotonic()
        reply = engine.answer(request)
        slowest = max(slowest, time.monotonic()-started)
        if 'error' in reply or reply.get('action') != 'place':
            return dict(seed=seed, chain=0, moves=move, end=reply.get('error', reply.get('reason')), reasons=reasons)
        reasons[reply['reason']] = reasons.get(reply['reason'], 0) + 1
        result = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                        x=reply['x'], r=reply['r']))
        # A clear below the policy's main-chain size is part of the build, as in a match.
        if len(result['links']) >= engine.policy['reset_moves_at_chain']:
            return dict(seed=seed, chain=len(result['links']), moves=move+1, end='fire', reasons=reasons,
                        small_clears=small, slowest_ms=round(slowest*1000))
        small += bool(result['links'])
        if result['dead']:
            return dict(seed=seed, chain=0, moves=move+1, end='dead', reasons=reasons)
        own['field'] = result['field']
    return dict(seed=seed, chain=0, moves=limit, end='no_fire', reasons=reasons)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--character', default='raffina')
    parser.add_argument('--seeds', type=int, default=8)
    parser.add_argument('--width', type=int, default=50)
    parser.add_argument('--depth', type=int, default=8)
    parser.add_argument('--pending', type=int, default=0, help='unconfirmed nuisance held throughout')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    engine = mode_engine.ModeBattleEngine(args.native, ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    try:
        rows = [run(engine, args.character, seed, dict(beam_width=args.width, beam_depth=args.depth), args.pending)
                for seed in range(1, args.seeds+1)]
    finally:
        engine.close()
    chains = [row['chain'] for row in rows]
    summary = dict(character=args.character, width=args.width, depth=args.depth, pending=args.pending,
        chains=chains, mean=round(statistics.mean(chains), 2),
        at_least_10=sum(c >= 10 for c in chains), at_least_13=sum(c >= 13 for c in chains))
    for row in rows:
        print(json.dumps(row))
    print(json.dumps(summary))
    if args.output:
        args.output.write_text(json.dumps(dict(summary=summary, runs=rows,
            status='offline_prototype_colour_model_no_opponent'), indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
