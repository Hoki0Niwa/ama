"""Replay logged "placement is no longer reachable" decisions without playing a game.

extract: read a bridge session log (UTF-16 jsonl) and keep each distinct failed placement:
         the board, the piece, the move the engine chose, where the controller lost the route.
check:   ask an engine binary which placements it offers on those boards and ask an
         operations library whether the offered/failed move has an executable route from the spawn.

    python tools/check_logged_unreachable.py extract LOG --output data/fever/baselines/....json
    python tools/check_logged_unreachable.py check FIXTURE [--engine EXE] [--dll DLL]

The logged moves are ones the game could not execute; a build passes for a piece kind when it no longer offers
them (exit status 1 otherwise). Replaying this takes seconds, no game or bridge.
"""
import argparse
import ctypes as C
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
SHAPES = {'2': 2, 'L': 3, 'J': 3, '4': 4, '0': 0}


class Press(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('dx', 'turn', 'x', 'y', 'r', 'armed', 'quick', 'frames')]


def extract(log, output):
    cases = {}
    with io.open(log, 'r', encoding='utf-16', errors='replace') as handle:
        for line in handle:
            if not line.startswith('{"auto": "analysis failed, retrying"'):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not (row.get('reason', '').startswith('placement is no longer') and row.get('move') and row.get('field')):
                continue
            key = (row['field'], row['piece'], row['move'])
            case = cases.setdefault(key, dict(field=row['field'].split('/'), piece=row['piece'], move=row['move'],
                                              lost_at=row.get('lost_at'), occurrences=0, first=row.get('decision_identity')))
            case['occurrences'] += 1
    result = dict(source=os.path.basename(log), cases=sorted(cases.values(), key=lambda c: (-c['occurrences'], c['piece'])))
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return result


def heights(field):
    result = []
    for x in range(6):
        h = 0
        for row, text in enumerate(field):
            if text[x] != '.':
                h = len(field) - row
                break
        result.append(h)
    return result


def check(fixture, engine_path, dll_path, kinds=('triple',)):
    """The logged moves are ones the game could not execute. A build passes for a piece kind when it no
    longer offers them. `routable` reports whether the operations library models the move as executable:
    True means the route model agrees with the engine and is itself wrong about the game."""
    from fever_battle.worker import JsonProcess
    data = json.loads(Path(fixture).read_text(encoding='utf-8'))
    dll = C.CDLL(str(dll_path))
    dll.ama_operation_route.argtypes = [C.POINTER(C.c_int)] + [C.c_int] * 9 + [C.POINTER(Press), C.c_int]
    dll.ama_operation_route.restype = C.c_int
    engine = JsonProcess([str(engine_path)])
    stats = {}
    for case in data['cases']:
        shape = SHAPES[case['piece'][0]]
        kind = 'triple' if shape == 3 else 'pair' if shape == 2 else 'other'
        h = heights(case['field'])
        x, r = int(case['move'][:-1]), 'URDL'.index(case['move'][-1])
        out = (Press * 1024)()
        pivot = x + (shape == 3 and r in (2, 3))
        routable = dll.ama_operation_route((C.c_int * 6)(*h), shape, 2, 0, 0, 0, pivot, r, 0, 1, out, len(out)) >= 0
        answer = engine.ask(dict(op='placements', field=case['field'], piece=case['piece']))
        offered = (x, 'URDL'[r]) in {(p['x'], p['r']) for p in answer['placements']}
        entry = stats.setdefault(kind, dict(cases=0, still_offered=0, library_routable=0, examples=[]))
        entry['cases'] += 1
        entry['still_offered'] += offered
        entry['library_routable'] += routable
        if offered and len(entry['examples']) < 3:
            entry['examples'].append(dict(piece=case['piece'], move=case['move'], occurrences=case['occurrences'],
                                          match=(case.get('first') or {}).get('match_id')))
    engine.close()
    failed = [k for k in kinds if stats.get(k, {}).get('still_offered')]
    return dict(fixture=str(fixture), engine=str(engine_path), kinds=stats, failed_kinds=failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    e = sub.add_parser('extract'); e.add_argument('log'); e.add_argument('--output', required=True)
    c = sub.add_parser('check'); c.add_argument('fixture')
    c.add_argument('--engine', default=str(ROOT / 'bin/fever_battle/fever_battle.exe'))
    c.add_argument('--dll', default=None)
    c.add_argument('--fail-on', default='triple', help='comma list of piece kinds that must no longer be offered')
    args = parser.parse_args()
    if args.command == 'check':
        args.engine = str(Path(args.engine).resolve())
        args.fixture = str(Path(args.fixture).resolve())
        args.dll = str(Path(args.dll).resolve()) if args.dll else None
    if args.command == 'extract':
        print(len(extract(args.log, args.output)['cases']), 'distinct failed placements ->', args.output)
    else:
        dll = args.dll or str(Path(args.engine).with_name('operations.dll'))
        result = check(args.fixture, args.engine, dll, tuple(k for k in args.fail_on.split(',') if k))
        print(json.dumps(result, ensure_ascii=False, indent=1))
        sys.exit(1 if result['failed_kinds'] else 0)


if __name__ == '__main__':
    main()
