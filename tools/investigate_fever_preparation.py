"""Read bridge logs and reproduce replacement of a full preparation by a cold one.

No game input; the probe uses prototype colour queues and the current native worker.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'test'))
from fever_battle.mode_engine import ModeBattleEngine
from fever_fixtures import request, side


def summarize(path):
    data = path.read_bytes()
    encoding = 'utf-16' if data[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
    try:
        contents = data.decode(encoding)
    except UnicodeDecodeError:
        contents = data.decode('cp932', errors='replace')
    rows = []
    for line in contents.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    decisions = [r for r in rows if r.get('auto') == 'planning'
                 and r.get('mode') == 'normal' and 'pair' in r and 'cache' in r]
    prepares = [r for r in rows if r.get('auto') == 'planning'
                and r.get('mode') == 'normal' and r.get('cache') == 'prepare']
    settings = next((r for r in rows if r.get('auto') == 'battle settings'), {})
    keys = ('t', 'ai', 'pair', 'cache', 'observed', 'prepared', 'searched_visible',
            'normal_build_width', 'cold_spawn', 'search_ms')
    return dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(),
                settings=settings, decisions=len(decisions),
                cold=sum(bool(r.get('cold_spawn')) for r in decisions),
                widths=dict(Counter(str(r.get('normal_build_width')) for r in decisions)),
                visible=dict(Counter(str(r.get('searched_visible')) for r in decisions)),
                caches=dict(Counter(r['cache'] for r in decisions)),
                preparations=[dict(observed=k[0], visible=k[1], prepared=k[2], count=v)
                              for k, v in Counter((r.get('observed'), r.get('searched_visible'),
                                                   r.get('prepared')) for r in prepares).items()],
                first_events=[{k: r[k] for k in keys if k in r} for r in rows
                              if r.get('auto') == 'planning' and r.get('ai') == 1][:16])


def probe(native):
    engine = ModeBattleEngine(native, ROOT / 'bin/fever/fever.exe', ROOT / 'config.json')
    try:
        queue = engine.native.ask(dict(op='queue', character='rafisol', seed=2, count=8))['queue']
        own = side(queue=queue[:3])
        own['character'] = 'rafisol'
        original = request(own)
        original['solo_options'] = dict(beam_width=250, beam_depth=16)
        first = engine.answer(original)
        preparing = deepcopy(original)
        preparing['self']['queue'] = queue[:4]
        preparing.update(op='prepare', placement=dict(x=first['x'], r=first['r']))
        full = engine.answer(preparing)
        full_reply = deepcopy(engine.prepared[2])
        observed = deepcopy(original)
        observed['self'] = deepcopy(engine.execution_request['self'])
        observed['self']['observed_frame'] = observed['frame']
        observed['self']['queue'] = queue[1:4]
        observed.update(op='prepare_observed', cold_spawn=True)
        narrow = engine.answer(observed)
        narrow_reply = deepcopy(engine.prepared[2])
        def describe(reply):
            return {k: reply.get(k) for k in ('x', 'r', 'normal_build_width', 'cold_spawn', 'reason')}
        return dict(queue=queue[:4], first=describe(first),
                    full=dict(visible=full['searched_visible'], **describe(full_reply)),
                    replacement=dict(visible=narrow['searched_visible'], **describe(narrow_reply)),
                    same_board=full['plan']['field'] == narrow['plan']['field'],
                    same_piece=full['plan']['piece_id'] == narrow['plan']['piece_id'],
                    placement_changed=(full_reply['x'], full_reply['r']) !=
                                      (narrow_reply['x'], narrow_reply['r']))
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', nargs='*', type=Path)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--native', type=Path, default=ROOT / 'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = dict(logs=[summarize(p) for p in args.logs])
    if args.probe:
        report['native_sha256'] = hashlib.sha256(args.native.read_bytes()).hexdigest()
        report['probe'] = probe(args.native)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
