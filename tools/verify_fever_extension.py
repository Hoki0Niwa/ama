"""Replay captured seeds and compare bounded extension on controlled queues.

These are native model checks, not live battle results or Steam color RNG.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.model import Scoring, drop_garbage
from fever_battle.seed_solver import SeedSolver
from fever_battle.worker import JsonProcess


def verify(native, scoring, own, result):
    field = own['field']
    for depth, step in enumerate(result['path']):
        actual = native.ask(dict(op='transition', field=field, piece=own['queue'][depth],
                                x=step['x'], r=step['r']))
        assert actual['locked_field'] == step['locked_field']
        assert scoring.chain(own['character'], actual['links'], 'fever') == step['link_points']
        assert not step['chain'] or depth == len(result['path']) - 1
        if not step['dropped']:
            assert actual['field'] == step['field']
        elif step.get('post_drop_field_known', True):
            if step['garbage_phase'] is None:
                assert step['dropped'] % 6 == 0  # full rows do not depend on remainder order
                before_phase = 0
            else:
                before_phase = (step['garbage_phase'] - step['dropped']) % 6
            dropped, _ = drop_garbage(actual['field'], step['dropped'], before_phase)
            assert dropped == step['field']
        field = step['field']
    if result['solved']:
        assert result['path'][-1]['chain'] >= own['seed_chain']


def summary(result, elapsed):
    return dict(choice={key: result['choice'][key] for key in
                       ('x', 'r', 'chain', 'all_clear')},
                last_chain=result['path'][-1]['chain'], solved=result['solved'],
                steps=len(result['path']), cutoff=result['cutoff'], expanded=result['expanded'],
                potential=result['path'][-1].get('extension_potential'), elapsed_ms=elapsed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--previous-native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    scoring = Scoring()
    source = ROOT/'data/fever/baselines/2026-10-05-t15-live-seeds.json'
    captures = json.loads(source.read_text(encoding='utf-8'))['results']
    records, simulations = [], []
    with JsonProcess([args.native], cwd=ROOT) as current, JsonProcess([args.previous_native], cwd=ROOT) as previous:
        solvers = dict(previous_quick=SeedSolver(previous, scoring),
                       current_quick=SeedSolver(current, scoring), current_extend=SeedSolver(current, scoring))
        for index, capture in enumerate(captures):
            own = dict(capture['input'], garbage_phase=0, mode_generation=1, seed_id=index,
                       piece_id=0)
            record = dict(character=own['character'], frame=capture['frame'], input=own, checks={})
            for name, solver in solvers.items():
                started = time.perf_counter()
                result = solver.solve(own, capture['target_point'], True,
                                      dict(strategy=name.rsplit('_', 1)[-1]), match_id='captured-replay')
                elapsed = (time.perf_counter()-started)*1000
                verify(current, scoring, own, result)
                record['checks'][name] = summary(result, elapsed)
            records.append(record)
        reference = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        seed3 = next(s['field'] for s in reference['seeds'] if s['id'] == 'hirazumi-3')
        for queue_seed in range(1, 11):
            # Driver owns the queue; every solver request sees at most 3 pieces.
            queue = current.ask(dict(op='queue', character='raffina', seed=queue_seed, count=32))['queue']
            simulation = dict(queue_seed=queue_seed, queue_model='prototype_independent_colors_not_steam', outcomes={})
            for name in ('previous_quick', 'current_extend'):
                solver = solvers[name]
                field = seed3
                steps = []
                for turn in range(24):
                    own = dict(character='raffina', field=field, queue=queue[turn:turn+3],
                               fever_confirmed=0, fever_unconfirmed=0, normal_confirmed=0,
                               normal_unconfirmed=0, remainder=0, garbage_phase=0,
                               remaining_frames=1800-turn*42, seed_chain=3,
                               mode_generation=1, seed_id=queue_seed, piece_id=turn)
                    started = time.perf_counter()
                    result = solver.solve(own, 120, True, dict(strategy=name.rsplit('_', 1)[-1]),
                                          match_id='controlled-extension-'+name)
                    verify(current, scoring, own, result)
                    steps.append(summary(result, (time.perf_counter()-started)*1000))
                    field = result['choice']['field']
                    if result['choice']['chain'] or result['choice']['dead']:
                        break
                simulation['outcomes'][name] = dict(placements=len(steps), chain=steps[-1]['choice']['chain'],
                                                   all_clear=steps[-1]['choice']['all_clear'], steps=steps)
            simulations.append(simulation)
    result = dict(date='2026-10-06', status='native_model_replay_and_controlled_queues_not_live_acceptance',
                  captured_garbage_phase_assumption='fixed_zero_for_comparison_not_observed_steam_order',
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
                  previous_native_sha256=hashlib.sha256(args.previous_native.read_bytes()).hexdigest(),
                  comparison='explicit_previous_quick_vs_current_quick_and_extend_not_full_old_tactics',
                  captured_count=len(records), path_replay_matches=True, captured=records,
                  controlled=simulations, controller=False, solver_visible_queue_limit=3)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(captured=len(records), controlled=len(simulations), path_replay_matches=True,
        chains=[(s['outcomes']['previous_quick']['chain'],s['outcomes']['current_extend']['chain']) for s in simulations])))


if __name__ == '__main__':
    main()
