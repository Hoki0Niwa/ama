"""Read an existing operation log and measure offline construction reuse.

No controller or memory reader is used. The opponent is a public synthetic
eight-link board; the own board/visible queue come from a saved log line.
"""
import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from test_fever_mode import NATIVE, SOLO, request, side
from fever_battle.mode_engine import ModeBattleEngine


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log', type=Path, default=ROOT.parent/'ama-memory-bridge/observations/input-session.log')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    raw = args.log.read_bytes()
    encoding = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
    rows = []
    for line in raw.decode(encoding, errors='replace').splitlines():
        try: rows.append(json.loads(line))
        except ValueError: pass
    planning = [r for r in rows if r.get('auto') == 'planning']
    modes = {}
    for mode in ('normal', 'fever'):
        choices = [r for r in planning if r.get('mode') == mode and r.get('cache') in ('miss', 'prefetched')]
        waits = [r.get('wait_ms', 0) for r in choices if r['cache'] == 'miss']
        modes[mode] = dict(cache_counts=dict(collections.Counter(r['cache'] for r in choices)),
            miss_mean_wait_ms=statistics.mean(waits) if waits else None, miss_max_wait_ms=max(waits, default=0))
    source = max((r for r in planning if r.get('mode') == 'normal' and r.get('cache') == 'miss'
                  and r.get('nuisance') == [0, 0] and len(r.get('queue', [])) == 3), key=lambda r:r.get('search_ms', 0))
    own = side('normal', source['field'].split('/'), source['queue'])
    own.update(character='arle', dropset_index=source['decision_identity']['dropset_index'],
               moves_since_chain=None, moves_since_chain_status='unknown')
    refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
    ref = next(s for s in refs['seeds'] if s['id'] == 'hirazumi-8')
    engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    trials = []
    try:
        placements = []
        for a in 'RYGB':
            for b in 'RYGB':
                placements += engine.native.ask(dict(op='placements', field=ref['field'], piece=f'2:{a}{b}'))['placements']
        trigger = next(c['locked_field'] for c in placements if len(c['links']) == 8)
        enemy = side('fever', ref['field']); enemy.update(seed_chain=8, seed_base=8)
        req = request(own, enemy)
        req['solo_options'] = dict(beam_width=250, beam_depth=8)
        req['enemy_chain'] = dict(trigger_field=trigger, elapsed=0, scored_links=0, mode_generation=1, seed_id=1)
        for _ in range(5):
            engine.normal_build_cache = None
            ahead = copy.deepcopy(req); ahead.update(op='prepare_observed')
            preparation = engine.answer(ahead)
            with patch.object(engine.solo, 'ask', wraps=engine.solo.ask) as build:
                start = time.perf_counter(); cached = engine.answer(req)
                cached_ms = (time.perf_counter()-start)*1000; cached_calls = build.call_count
            engine.normal_build_cache = None
            with patch.object(engine.solo, 'ask', wraps=engine.solo.ask) as build:
                start = time.perf_counter(); fresh = engine.answer(req)
                fresh_ms = (time.perf_counter()-start)*1000; fresh_calls = build.call_count
            assert preparation.get('normal_build_prepared') and cached_calls == 0 and fresh_calls == 1
            trials.append(dict(prepare=preparation, cached_ms=cached_ms, fresh_ms=fresh_ms,
                cached_builder_calls=cached_calls, fresh_builder_calls=fresh_calls,
                cached_reply=cached, fresh_reply=fresh))
    finally:
        engine.close()
    report = dict(status='offline_log_board_synthetic_enemy_not_live_acceptance',
        log_bytes=len(raw), log_sha256=hashlib.sha256(raw).hexdigest(),
        fixture_character='arle_shape_compatible_not_identified_from_log',
        prepare_refusals=dict(collections.Counter(r.get('reason') for r in planning if r.get('cache') == 'prepare' and not r.get('prepared'))),
        modes=modes, source=source, request=req, trials=trials,
        cached_median_ms=statistics.median(t['cached_ms'] for t in trials),
        fresh_median_ms=statistics.median(t['fresh_ms'] for t in trials),
        native_sha256=hashlib.sha256(NATIVE.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('prepare_refusals', 'modes', 'cached_median_ms', 'fresh_median_ms')}))


if __name__ == '__main__': main()
