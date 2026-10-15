"""How fast a character builds a main chain alone, with the mod's shape cycle (doc/DROPSETS.md).

python tools/bench_fever_pace.py --output out.json [--seeds 20]

Same loop as tools/bench_fever_opening.py (the live engine, one decision per piece, no opponent, no
input), but the queue follows a given 16-move cycle, so the mod's cycles of 2026-10-14 can be used.
Colors are drawn uniformly from 4 (not the game's table). Reports, per setting, the piece at which the
board first holds a chain of 10/12/13/14 (engine `holding`), and the first fire the engine itself chose:
piece, chain, cells, puyos per link. Not a win-rate test.
"""
import argparse
import json
import random
import statistics as st
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))
from fever_battle.mode_engine import ModeBattleEngine      # noqa: E402
from bench_fever_normal_build import side                   # noqa: E402

MOD = dict(ally='22222220222222J4', rafisol='2JL4222422202LJ0')
OFFICIAL = dict(ally='2222L22220222224', rafisol='222L222J24L024J0')
COLORS = 'RGBY'
SIZE = {'2': 2, 'J': 3, 'L': 3, '4': 4, '0': 1}


def queue_of(pattern, seed, count):
    rng = random.Random(seed)
    out = []
    for i in range(count):
        s = pattern[i % 16]
        a, b = rng.choice(COLORS), rng.choice(COLORS)
        if s == '2':
            cols = a + b
        elif s == 'J':          # the shapes the engine accepts: J is ABA, L is AAB, 4 is AABB with A != B
            cols = a + b + a
        elif s == 'L':
            cols = a + a + b
        elif s == '4':
            while b == a:
                b = rng.choice(COLORS)
            cols = a + a + b + b
        else:
            cols = a
        out.append(f'{s}:{cols}')
    return out


def puyos(piece):
    s = piece[0]
    return {'2': 2, 'J': 3, 'L': 3, '4': 4, '0': 4}[s]


def run(engine, character, pattern, seed, width, depth, budget, limit=70):
    queue = queue_of(pattern, seed, limit+3)
    own, enemy = side(character), side(character)
    own['pattern'] = pattern
    enemy['pattern'] = pattern
    enemy['queue'] = queue[:3]
    reach = {}
    first = None
    for i in range(limit):
        own.update(field=own['field'], queue=queue[i:i+3], piece_id=i, dropset_index=i % 16, observed_frame=i)
        enemy['observed_frame'] = i
        req = dict(protocol_version=3, rule='fever_battle', match_id=f'pace-{character}-{seed}-{width}', frame=i,
            observation=dict(frame_before=i, frame_after=i, match_status='running'), target_point=120,
            gauge_gain_on_offset=1, clock_policy=dict(count_chain_frames=True), self=own, enemy=enemy,
            solo_options=dict(beam_width=width, beam_depth=depth), decision_budget_ms=budget)
        reply = engine.answer(req)
        if reply.get('action') != 'place':
            break
        step = engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0], x=reply['x'], r=reply['r']))
        chain = len(step['links'])
        if step['dead']:
            first = first or dict(piece=i+1, chain=chain, dead=True)
            break
        cells_before = sum(c not in './#' for row in own['field'] for c in row)
        if chain and chain >= 8 and first is None:
            first = dict(piece=i+1, chain=chain, cells=cells_before + puyos(queue[i]),
                         per_link=round((cells_before + puyos(queue[i]) - sum(c not in './#' for row in step['field'] for c in row))/chain, 2),
                         reason=reply['reason'])
        own['field'] = step['field']
        h = engine.native.ask(dict(op='holding', field=own['field']))['longest']
        for goal in (10, 12, 13, 14):
            if h >= goal and goal not in reach:
                reach[goal] = i+1
        if first is not None and chain >= 8:
            break
    return dict(seed=seed, reach=reach, first=first)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    ap.add_argument('--seeds', type=int, default=20)
    ap.add_argument('--budget', type=int, default=100)
    ap.add_argument('--retain-floor', type=int, help='policy normal_build.retain_floor for this run (default: the policy file)')
    ap.add_argument('--retain-fire-cells', type=int, help='policy normal_build.retain_fire_cells for this run (0: never fire)')
    ap.add_argument('--retain-cells', type=int, help='policy normal_build.retain_cells (the retention applies from this many puyos)')
    ap.add_argument('--retain-fire-chain', type=int, help='policy normal_build.retain_fire_chain for this run')
    ap.add_argument('--forced-lookahead', type=int, choices=[0, 1], help='policy normal_build.forced_lookahead for this run')
    ap.add_argument('--retain-fire-safe-moves', type=int, help='policy normal_build.retain_fire_safe_moves for this run (-1: off)')
    ap.add_argument('--only', nargs='*', help='labels (first words) of the settings to run')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    settings = [
        ('rafisol mod  w200', 'rafisol', MOD['rafisol'], 200),
        ('ally mod     w100', 'ally', MOD['ally'], 100),
        ('ally mod     w200', 'ally', MOD['ally'], 200),
        ('ally official w100', 'ally', OFFICIAL['ally'], 100),
        ('rafisol official w200', 'rafisol', OFFICIAL['rafisol'], 200),
    ]
    engine = ModeBattleEngine(args.native, ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    if args.retain_floor is not None:
        engine.policy['normal_build']['retain_floor'] = args.retain_floor if args.retain_floor > 0 else None
    if args.retain_fire_cells is not None:
        engine.policy['normal_build']['retain_fire_cells'] = args.retain_fire_cells or None
    if args.retain_cells is not None:
        engine.policy['normal_build']['retain_cells'] = args.retain_cells
    if args.retain_fire_chain is not None:
        engine.policy['normal_build']['retain_fire_chain'] = args.retain_fire_chain
    if args.forced_lookahead is not None:
        engine.policy['normal_build']['forced_lookahead'] = bool(args.forced_lookahead)
    if args.retain_fire_safe_moves is not None:
        engine.policy['normal_build']['retain_fire_safe_moves'] = None if args.retain_fire_safe_moves < 0 else args.retain_fire_safe_moves
    if args.only:
        settings = [s for s in settings if s[0].split()[0] in args.only and ('mod' in s[0])]
    report = {}
    try:
        for label, character, pattern, width in settings:
            rows = [run(engine, character, pattern, seed, width, 8, args.budget) for seed in range(args.seeds)]
            report[label] = rows
            fires = [r['first'] for r in rows if r['first'] and not r['first'].get('dead')]
            def med(v): return st.median(v) if v else None
            line = dict(label=label, n=len(rows), fired=len(fires),
                fire_piece=med([f['piece'] for f in fires]), fire_chain=med([f['chain'] for f in fires]),
                fire_cells=med([f['cells'] for f in fires]), per_link=med([f['per_link'] for f in fires]),
                dead=sum(1 for r in rows if r['first'] and r['first'].get('dead')))
            for goal in (10, 12, 13, 14):
                got = [r['reach'][goal] for r in rows if goal in r['reach']]
                line[f'hold{goal}'] = (len(got), med(got))
            print(json.dumps(line, ensure_ascii=False), flush=True)
    finally:
        engine.close()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
