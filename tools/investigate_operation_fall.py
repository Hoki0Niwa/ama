"""Compare logged pair placements against two operation libraries, offline.

This does not replay AI decisions or prove that new placements work in Steam.
It measures which previously chosen placements lose their spawn route.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path

from analyze_fever_arrival import records


class Press(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('dx', 'turn', 'x', 'y', 'r', 'armed', 'quick', 'frames')]


class Routes:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.dll = C.CDLL(str(self.path))
        assert self.dll.ama_operation_version() == 1 and self.dll.ama_operation_rule() == 1
        self.dll.ama_operation_route.argtypes = [C.POINTER(C.c_int)] + [C.c_int] * 9 + [C.POINTER(Press), C.c_int]

    def accepts(self, h, x, r):
        out = (Press * 1024)()
        return self.dll.ama_operation_route((C.c_int * 6)(*h), 2, 2, 0, 0, 0,
                                             x, r, 0, 1, out, len(out)) >= 0


def compare(path, before, after):
    boards, pairs, changes = {}, 0, []
    main_fires, changed_main_fires = 0, 0
    for item in records(path) or []:
        ai = item.get('ai')
        if item.get('auto') == 'planning' and 'field' in item:
            boards[ai] = item
        if item.get('auto') not in ('locked', 'fire') or not item.get('piece', '').startswith('2:'):
            continue
        planning = boards.get(ai)
        if not planning or planning['pair'] != item['pair']:
            continue
        pairs += 1
        board = planning['field'].split('/')
        h = tuple(sum(row[x] != '.' for row in board[1:]) for x in range(6))
        x, r = item['target']
        old = before.accepts(h, x, r)
        new = after.accepts(h, x, r)
        main = item.get('chain', 0) >= 12
        main_fires += main
        changed_main_fires += main and old and not new
        if old and not new:
            changes.append(dict(ai=ai, pair=item['pair'], heights=h, piece=item['piece'],
                target=item['target'], on_target=item.get('on_target'), chain=item.get('chain'),
                match=planning.get('decision_identity', {}).get('match_id')))
    return dict(log=str(path), log_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                before_dll_sha256=before.sha256, after_dll_sha256=after.sha256,
                pairs=pairs, removed_chosen_routes=len(changes),
                main_fires=main_fires, removed_main_fire_routes=changed_main_fires, changes=changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', nargs='+', type=Path)
    parser.add_argument('--before-dll', required=True)
    parser.add_argument('--after-dll', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    before, after = Routes(args.before_dll), Routes(args.after_dll)
    report = [compare(path, before, after) for path in args.logs]
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for row in report:
        print(json.dumps({k: v for k, v in row.items() if k != 'changes'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
