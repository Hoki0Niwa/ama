"""Controlled public-reference seed checks; never report these as live success."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from .model import ROOT, Scoring
from .timing import ChainTiming
from .worker import JsonProcess


def benchmark(native, reference):
    score = Scoring()
    samples = []
    shapes = {
        '2': [f'2:{a}{b}' for a in 'RYGB' for b in 'RYGB'],
        'L': [f'L:{a}{a}{b}' for a in 'RYGB' for b in 'RYGB'],
        'J': [f'J:{a}{b}{a}' for a in 'RYGB' for b in 'RYGB'],
        '4': [f'4:{a}{a}{b}{b}' for a in 'RYGB' for b in 'RYGB' if a != b],
        '0': [f'0:{a}' for a in 'RYGB'],
    }
    for seed in reference['seeds']:
        native.ask(dict(op='validate', field=seed['field']))
        if native.ask(dict(op='resolve', field=seed['field']))['links']:
            raise ValueError('reference seed already clears before placing: '+seed['id'])
        for shape, pieces in shapes.items():
            # Find a favorable current piece by explicit enumeration; this is
            # a geometry fixture, not a random-queue performance estimate.
            best = None
            for piece in pieces:
                moves = native.ask(dict(op='placements', field=seed['field'], piece=piece))['placements']
                for move in moves:
                    if not move['dead'] and (best is None or len(move['links']) > best[0]):
                        best = (len(move['links']), piece)
            if best is None:
                samples.append(dict(seed=seed['id'], shape=shape, status='no_legal_current_piece'))
                continue
            chain, piece = best
            started = time.perf_counter()
            result = native.ask(dict(op='seed_search', field=seed['field'], queue=[piece],
                confirmed=0, unconfirmed=0, held_pending=0, remainder=0, garbage_phase=0,
                target_point=120, remaining_frames=1800, seed_chain=seed['seed_chain'],
                safety_frames=8, count_chain_frames=True, width=64,
                budget_ms=50, max_nodes=8000, timing=ChainTiming.for_mode('fever').native(),
                powers=score.data['characters']['raffina']['fever'], bonuses=score.data['bonuses']))
            first = result['choice']
            transition = native.ask(dict(op='transition', field=seed['field'], piece=piece,
                                         x=first['x'], r=first['r']))
            if transition['field'] != first['field'] or score.chain('raffina', transition['links'], 'fever') != first['link_points']:
                raise ValueError('solver result cannot be replayed')
            samples.append(dict(seed=seed['id'], shape=shape, selected_visible_piece=piece,
                reference_chain=seed['seed_chain'], reachable_chain=chain, solver_chain=first['chain'],
                solved=result['solved'], cutoff=result['cutoff'], replay_matches=True,
                elapsed_ms=(time.perf_counter()-started)*1000))
    return dict(status='controlled_reference_geometry_not_live_success_rate',
                color_model='canonical_colors_current_piece_selected_for_best_reachable_chain',
                sample_count=len(samples), solved=sum(s.get('solved',False) for s in samples),
                samples=samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--reference', type=Path, default=ROOT/'data/fever/seeds/namoko-reference.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with JsonProcess([args.native], cwd=ROOT) as native:
        result = benchmark(native, json.loads(args.reference.read_text(encoding='utf-8')))
    result['reference_sha256'] = hashlib.sha256(args.reference.read_bytes()).hexdigest()
    result['native_sha256'] = hashlib.sha256(args.native.read_bytes()).hexdigest()
    result['date'] = '2026-10-05'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='samples'}))


if __name__ == '__main__':
    main()
