"""Continuous opening/second construction; prototype colors, no opponent/input.

Uses the protocol-3 builder options and actual native transitions. Tactical
overrides, seed distribution on all-clear, nuisance and gauge aren't simulated.
Keep the resulting fields after clears: resetting to empty is not a second test.
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
sys.path.insert(0, str(ROOT / 'tools'))
from fever_battle.mode_engine import ModeBattleEngine
from bench_fever_normal_build import side


def run(engine, character, seed, width, depth, limit, variant, enemy_fever=False):
    queue = engine.native.ask(dict(op='queue', character=character, seed=seed, count=limit+3))['queue']
    own, enemy = side(character), side(character)
    if enemy_fever: enemy['mode']='fever'
    own['normal_chain_max'] = 0
    enemy['queue'] = queue[:3]
    records, fires, elapsed = [], [], []
    for move in range(limit):
        own.update(queue=queue[move:move+3], dropset_index=move, piece_id=move, observed_frame=move)
        request = dict(self=own, enemy=enemy, solo_options=dict(trigger=14, beam_width=width, beam_depth=depth),
                       second_target_chain=14, gauge_gain_on_offset=1)
        options = engine._normal_options(request, own)
        started = time.perf_counter()
        # Variant switches are native-only test inputs; they cannot change the target.
        try:
            result = engine._solo_build(own, options) if variant == 'full' else engine.solo.ask(dict(rule='fever', solo=True, character=character, dropset_index=move,
                self=dict(field=own['field'], queue=own['queue']), include_next=True,
                plain_pairs=True, special_moves=True,
                **{**options, 'construction_scoring': options.get('construction_scoring', False) and variant != 'legacy',
                   'rebuild': options.get('rebuild', False) and variant == 'full'}))
        except (ValueError, RuntimeError, TimeoutError) as error:
            if not isinstance(error, ValueError):
                engine_failure=ROOT/'bin/sustained/benchmark-failure.json'
                engine_failure.parent.mkdir(parents=True,exist_ok=True)
                engine_failure.write_text(json.dumps(dict(own=own,options=options,character=character,
                    seed=seed,move=move,error=str(error)),ensure_ascii=False,indent=1),encoding='utf-8')
            return dict(seed=seed, end=str(error), fires=fires, moves=move, trace=records)
        elapsed.append((time.perf_counter()-started)*1000)
        if 'error' in result:
            return dict(seed=seed, end=result['error'], fires=fires, moves=move, trace=records)
        transition = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                            x=result['x'], r=result['r']))
        links = len(transition['links'])
        records.append(dict(move=move, piece=own['queue'][0], before=own['field'],
                            x=result['x'], r=result['r'], links=links, after=transition['field'],
                            fire=result['fire'], target=options['build_chain'],
                            capacity=deepcopy(engine.normal_capacity),
                            reconstruction=result.get('reconstruction')))
        if links >= 3:
            fires.append(dict(move=move, chain=links, since_previous=move+1-(fires[-1]['move']+1 if fires else 0),
                              capacity=options['trigger'] == 1, remain=sum(c!='.' for r in transition['field'] for c in r)))
        if transition['dead']:
            end = 'dead'; break
        own['field'] = transition['field']
        own['normal_chain_max'] = max(own['normal_chain_max'], links)
        own['moves_since_chain'] = 0 if links else own['moves_since_chain']+1
        if sum(f['chain'] >= 13 for f in fires) >= 3:
            end = 'three_large'; break
    else:
        end = 'limit'
    return dict(seed=seed, end=end, moves=move+1, fires=fires, trace=records,
                mean_ms=round(sum(elapsed)/len(elapsed), 2), max_ms=round(max(elapsed), 2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    p.add_argument('--characters', nargs='+', default=['raffina', 'rafisol'])
    p.add_argument('--seeds', type=int, default=2)
    p.add_argument('--width', type=int, default=250)
    p.add_argument('--depth', type=int, default=8)
    p.add_argument('--limit', type=int, default=120)
    p.add_argument('--enemy-fever', action='store_true')
    p.add_argument('--solo', type=Path, default=ROOT/'bin/fever/fever.exe')
    p.add_argument('--variant', choices=['legacy', 'score', 'full'], default='full')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    engine = ModeBattleEngine(a.native, a.solo, ROOT/'config.json')
    runs = []
    try:
        for character in a.characters:
            for seed in range(1, a.seeds+1):
                row = dict(character=character, **run(engine, character, seed, a.width, a.depth, a.limit, a.variant, a.enemy_fever))
                runs.append(row)
                print(json.dumps({k:v for k,v in row.items() if k != 'trace'}), flush=True)
    finally:
        engine.close()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(dict(settings=vars(a), runs=runs,
        native_sha256=hashlib.sha256(a.native.read_bytes()).hexdigest(),
        solo_sha256=hashlib.sha256(a.solo.read_bytes()).hexdigest(),
        status='prototype_colors_no_opponent_no_seed_distribution_no_game_input'), default=str,
        ensure_ascii=False, indent=1)+'\n', encoding='utf-8')


if __name__ == '__main__': main()
