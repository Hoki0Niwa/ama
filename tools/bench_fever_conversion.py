"""Compare conversion on/off from a captured board, with recorded pieces and no new attacks.

Input is {rows: [...]} saved by a bridge-log investigation. This is an offline
construction comparison, not a replay of the opponent, game timing or match outcome.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine


def run(native, initial, pieces, enabled, limit):
    engine = ModeBattleEngine(native, ROOT / 'bin/fever/fever.exe', ROOT / 'config.json')
    engine.policy['normal_build']['conversion']['enabled'] = enabled
    engine.policy['normal_tactics']['quiet'] = False
    req = deepcopy(initial)
    req.pop('active_placement', None)
    req.pop('enemy_chain', None)
    req['enemy'].update(field=['......'] * 14, mode='normal', phase='placing', gauge=0,
        normal_chain_max=0, mode_generation=0,
        confirmed=0, unconfirmed=0, normal_confirmed=0, normal_unconfirmed=0,
        fever_confirmed=0, fever_unconfirmed=0)
    req['self'].update(confirmed=0, unconfirmed=0, normal_confirmed=0, normal_unconfirmed=0,
                       fever_confirmed=0, fever_unconfirmed=0)
    req['observation'].pop('in_flight', None)
    req['match_id'] = f'conversion-comparison-{enabled}'
    req['op'] = 'think'
    start = req['self']['piece_id']
    trace = []
    try:
        for offset in range(limit):
            index = start + offset
            if any(index + k not in pieces for k in range(3)):
                return dict(end='recorded_queue_ends', trace=trace)
            own = req['self']
            own.update(queue=[pieces[index + k] for k in range(3)], piece_id=index,
                       dropset_index=(initial['self']['dropset_index'] + offset) % 16)
            frame = initial['frame'] + offset * 60
            req['frame'] = frame
            req['observation'].update(frame_before=frame, frame_after=frame)
            own['observed_frame'] = req['enemy']['observed_frame'] = frame
            begun = time.monotonic()
            reply = engine.answer(req)
            elapsed = (time.monotonic() - begun) * 1000
            step = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                         x=reply['x'], r=reply['r']))
            chain = len(step['links'])
            forecast = reply.get('capacity_conversion', {})
            trace.append(dict(piece=index, x=reply['x'], r=reply['r'], chain=chain,
                score=sum(engine.scoring.chain(own['character'], step['links'])),
                reason=reply['reason'], cells=sum(c != '.' for r in step['field'] for c in r),
                conversion=forecast.get('conversion_chain'),
                retained_points=forecast.get('retained_points'), reference_points=forecast.get('reference_points'),
                normal_root_values=reply.get('normal_root_values'),
                field_before=own['field'], queue=own['queue'],
                repair_min=forecast.get('repair_chain_min'),
                repair_max=forecast.get('repair_chain_max'), decision_ms=elapsed))
            own['field'] = step['field']
            own['moves_since_chain'] = 0 if chain else (own.get('moves_since_chain') or 0) + 1
            own['normal_chain_max'] = max(own.get('normal_chain_max', 0), chain)
            if step['dead'] or chain >= 13:
                return dict(end='dead' if step['dead'] else 'large_chain', trace=trace)
        return dict(end='limit', trace=trace)
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--native', type=Path, default=ROOT / 'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--seat', type=int, default=2)
    parser.add_argument('--piece', type=int, default=24)
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    rows = json.loads(raw)['rows']
    events = [r for r in rows if r.get('ai') == args.seat and r.get('request')]
    initial = next(r['request'] for r in events if r.get('pair') == args.piece)
    pieces = {}
    for event in events:
        own = event['request']['self']
        for offset, piece in enumerate(own['queue']):
            # Keep the directly observed current piece over an older NEXT hint.
            if offset == 0 or own['piece_id'] + offset not in pieces:
                pieces[own['piece_id'] + offset] = piece
    report = dict(source_sha256=hashlib.sha256(raw).hexdigest(),
        native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
        status='recorded_pieces_from_one_board_no_new_opponent_attacks_no_input_or_match_timing',
        runs={str(on): run(args.native, initial, pieces, on, args.limit) for on in (False, True)})
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for name, row in report['runs'].items():
        print(name, row['end'], [(r['piece'], r['chain'], r['reason']) for r in row['trace']])


if __name__ == '__main__':
    main()
