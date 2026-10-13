"""Does the tactical search keep a main chain while the opponent's chain still runs?

python tools/investigate_main_keep.py [--native bin/x/fever_battle.exe]

The boards are AI 2's of seed 2 on 2026-10-13 (doc/WORK_LOG.md): a 12 chain in hand, the opponent's
13 chain (116430 points, 963 nuisance at 120) under way with twelve pieces' time before it ends.
Piece 27 could fire the 12; piece 28 was stood on the third column and left a 3 chain, though two
placements kept the 12. The opponent's remaining links are not in the log: they are put here as ten
links growing with the square of their number, ending when the bridge's estimate said (752 frames
from piece 27). Synthetic in that respect; the boards, pieces and counts are the logged ones.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle import tactics                                   # noqa: E402
from fever_battle.mode_engine import ModeBattleEngine              # noqa: E402

PIECES = {
    27: dict(field='....../....Y./B...B./Y...B./BG..YB/BR..YR/YG.GRB/RR.BGB/RGGBGB/GRGYRG/RRYRRG/GBRYYB/GGBBRG/RRBYYY',
             queue=['2:RY', '2:BG', '2:BR'], unconfirmed=9, scored=1080, ends_in=752),
    28: dict(field='....../R...Y./B...B./Y...B./BG..YB/BR..YR/YG.GRB/RR.BGB/RGGBGB/GRGYRG/RRYRRG/GBRYYB/GGBBRG/RRBYYY',
             queue=['2:BG', '2:BR', '2:RR'], unconfirmed=17, scored=2040, ends_in=699),
}
TOTAL = 116430


def events(scored, ends_in, links=10):
    weights = [k * k for k in range(4, 4 + links)]
    left = TOTAL - scored
    points = [left * w // sum(weights) for w in weights]
    points[-1] += left - sum(points)
    return ([dict(type='link', frame=ends_in * (k + 1) // (links + 1), points=p) for k, p in enumerate(points)]
            + [dict(type='end', frame=ends_in)])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--fields', type=Path, help='JSON {piece: field} read from a session log, for the boards not written here')
    args = parser.parse_args()
    fields = json.loads(args.fields.read_text(encoding='utf-8')) if args.fields else {}
    engine = ModeBattleEngine(args.native, ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    try:
        longest = lambda rows: engine.native.ask(dict(op='holding', field=rows))['longest']
        for number, piece in PIECES.items():
            field = fields.get(str(number)) or piece['field']
            if field is None:
                continue
            rows = field.split('/')
            own = dict(character='ally', field=rows, queue=piece['queue'], confirmed=0, unconfirmed=piece['unconfirmed'],
                       remainder=0, garbage_phase=0, gauge=0, piece_id=number - 1, mode_generation=0, normal_chain_max=0)
            policy = dict(engine.policy['normal_tactics'], budget_ms=0)
            decision = tactics.evaluate(engine.native, engine.scoring, own, 120, 1, policy,
                                        enemy_events=events(piece['scored'], piece['ends_in']),
                                        enemy=dict(mode='normal', gauge=0), pace=63)
            choice = decision.forecast['choice']
            placed = engine.native.ask(dict(op='placements', field=rows, piece=piece['queue'][0]))['placements']
            after = {(p['x'], p['r']): (len(p['links']), longest(p['field'])) for p in placed if not p['dead']}
            print(f"piece {number} {piece['queue'][0]}: main on the board {longest(rows)}; chosen {choice['x']}{choice['r']}"
                  f" ({tactics.kind(choice)}, chain {choice['chain']}) leaves a main of {after[(choice['x'], choice['r'])][1]}")
            ranked = sorted(decision.forecast['candidates'], key=lambda c: -c['value'])
            for c in ranked[:8]:
                links, main = after.get((c['x'], c['r']), (None, None))
                print(f"    {c['x']}{c['r']} value {c['value']:>9} pops {links} main left {main}")
    finally:
        engine.close()


if __name__ == '__main__':
    main()
