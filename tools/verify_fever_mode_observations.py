"""Replay real, stable Fever observations without operating the game.

All six modeled garbage cursors are evaluated separately: the game's partial-row
column order is not yet calibrated. A returned plan is geometry validation, not
evidence that the game executed it or that its input route fits the clock.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.model import Scoring, drop_garbage
from fever_battle.seed_solver import SeedSolver
from fever_battle.worker import JsonProcess


def verify(source, native, limit=20):
    selected, seen = [], set()
    text = source.read_text(encoding='utf-8')
    lines = text.splitlines()
    if source.suffix == '.json':
        # Tracked cases allow replay without distributing raw memory captures.
        saved = json.loads(text)
        if saved.get('status') != 'read_only_real_seed_geometry_replay_not_live_acceptance':
            raise ValueError('unsupported observation baseline')
        for case in saved['results']:
            side = case['input']
            p = dict(frame=case['frame'], active=dict(placed=case['piece_id']),
                     character=case['character'], settled_field=side['field'],
                     queue=dict(index=case['dropset_index'], visible=side['queue']),
                     target_point=case['target_point'], raw_clock_frames=side['remaining_frames'],
                     seed_last_chain=side['seed_chain'], remainder=side['remainder'],
                     normal_nuisance=dict(confirmed=side['normal_confirmed'],unconfirmed=side['normal_unconfirmed']),
                     fever_nuisance=dict(confirmed=side['fever_confirmed'],unconfirmed=side['fever_unconfirmed']))
            selected.append((case['seat']-1, p))
        lines = []
    patterns = {c['id']:c['pattern'] for c in json.loads(
        (ROOT/'data/fever/dropsets.json').read_text(encoding='utf-8'))['characters']}
    for line in lines:
        packet = json.loads(line)
        if packet.get('event') != 'sample':
            continue
        for seat, p in enumerate(packet['players']):
            if (p['mode'] != 'fever' or p['settled_field'] is None or p['player_state'] != 1
                    or p['active']['grounded'] or not p['field_settled'] or p['field_phase'] != 0
                    or p['mode_phase'] != 2 or p['raw_clock_frames'] == 0):
                continue
            key = (p['address'], p['active']['placed'])
            if key in seen:
                continue
            seen.add(key)
            selected.append((seat, p))
    selected = selected[:limit]
    results, scoring = [], Scoring()
    with JsonProcess([native], cwd=ROOT) as worker:
        solver = SeedSolver(worker, scoring)
        for seat, p in selected:
            pattern = patterns[p['character']]
            if any(piece[0] != pattern[(p['queue']['index']+i)%16]
                   for i,piece in enumerate(p['queue']['visible'])):
                raise ValueError('observed piece shape disagrees with character/cycle')
            side = dict(character=p['character'], field=p['settled_field'], queue=p['queue']['visible'],
                        fever_confirmed=p['fever_nuisance']['confirmed'],
                        fever_unconfirmed=p['fever_nuisance']['unconfirmed'],
                        normal_confirmed=p['normal_nuisance']['confirmed'],
                        normal_unconfirmed=p['normal_nuisance']['unconfirmed'], remainder=p['remainder'],
                        remaining_frames=p['raw_clock_frames'], seed_chain=p['seed_last_chain'])
            outcomes = []
            for cursor in range(6):
                reply = solver.solve({**side, 'garbage_phase': cursor}, p['target_point'], True,
                                     dict(budget_ms=1000, max_nodes=8000))
                choice = reply['choice']
                rows, next_cursor = side['field'], cursor
                for piece, move in zip(side['queue'], reply['path']):
                    replay = worker.ask(dict(op='transition', field=rows, piece=piece,
                                             x=move['x'], r=move['r']))
                    points = scoring.chain(p['character'], replay['links'], 'fever')
                    if move['chain'] != len(replay['links']) or move['link_points'] != points:
                        raise AssertionError('seed path disagrees with legal placement/score replay')
                    rows, _ = drop_garbage(replay['field'], move['dropped'], next_cursor)
                    next_cursor = (next_cursor + move['dropped']) % 6
                    if rows != move['field'] or next_cursor != move['garbage_phase']:
                        raise AssertionError('seed path disagrees with replayed field/cursor')
                outcomes.append(dict(cursor=cursor, x=choice['x'], r=choice['r'], chain=choice['chain'],
                                     success=reply['solved'], fire_at=choice['fire_at'],
                                     cutoff=reply['cutoff'], expanded=reply['expanded']))
            results.append(dict(seat=seat+1, frame=p['frame'], piece_id=p['active']['placed'],
                                character=p['character'], dropset_index=p['queue']['index'],
                                target_point=p['target_point'], input=side, outcomes=outcomes,
                                same_first_move_for_all_cursors=len({(o['x'],o['r']) for o in outcomes})==1))
    return dict(status='read_only_real_seed_geometry_replay_not_live_acceptance',
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
                hidden_colors_read=False, controller=False, clock_domain='pc_15209927_internal',
                samples=len(results), searches=len(results)*6,
                successes=sum(o['success'] for r in results for o in r['outcomes']),
                remaining_unverified=['actual_partial_row_column_order', 'input_route_deadline',
                                      'predicted_chain_and_score_vs_game', 'opponent_future_attack'], results=results)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--native',type=Path,default=ROOT/'bin/t15/fever_battle.exe')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=20)
    args=parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error('limit must be 1..10000')
    result=verify(args.input,args.native,args.limit)
    with args.output.open('x',encoding='utf-8') as out:
        json.dump(result,out,ensure_ascii=False,indent=2); out.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))


if __name__=='__main__': main()
