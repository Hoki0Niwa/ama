"""Replay recorded protocol-3 requests through the current tactics and list what changed.

python tools/replay_fever_tactics.py --native bin/t15/fever-tactics.exe --output REPORT.json
Offline only: nothing here shows that the game accepts or benefits from a move.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine

SOURCES = ('data/fever/baselines/2026-10-06-normal-colors.json',
           'data/fever/baselines/2026-10-06-fever-watch-failure-replay.json')


def recorded():
    for name in SOURCES:
        data = json.loads((ROOT/name).read_text(encoding='utf-8'))
        for index, case in enumerate(data.get('cases', data.get('results', []))):
            before = case.get('choice') or case.get('after') or {}
            yield f'{Path(name).stem}#{index}', case['request'], before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    engine = ModeBattleEngine(args.native, ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    rows = []
    try:
        for name, request, before in recorded():
            own = request['self']
            try:
                reply = engine.answer(request)
            except (ValueError, KeyError) as error:
                rows.append(dict(case=name, error=str(error)))
                continue
            rows.append(dict(case=name, mode=own['mode'], gauge=own['gauge'],
                confirmed=own['confirmed'], unconfirmed=own['unconfirmed'],
                held=own['normal_confirmed']+own['normal_unconfirmed'] if own['mode'] == 'fever' else 0,
                remaining_frames=own['remaining_frames'], enemy_chain=request.get('enemy_chain') is not None,
                recorded=dict(x=before.get('x'), r=before.get('r'), chain=before.get('chain'), reason=before.get('reason')),
                now=dict(x=reply.get('x'), r=reply.get('r'), chain=reply.get('chain'), reason=reply.get('reason'))))
    finally:
        engine.close()
    report = dict(native_sha256=hashlib.sha256(Path(args.native).read_bytes()).hexdigest(),
        sources=list(SOURCES), live_input_verified=False, cases=rows)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
