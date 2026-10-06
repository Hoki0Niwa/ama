"""Offline normal counters against a resolved public eight-link reference.

The solo builder's firing move is fixed to reproduce its former unconditional
override. Placements, scoring and opponent timing use the real engines.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from test_fever_mode import NATIVE, SOLO, request, side, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.uncertainty import choose
from fever_battle.gauge_wait import choose as wait_move


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
    ref = next(s for s in refs['seeds'] if s['id'] == 'hirazumi-8')
    engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    cases = []
    try:
        placements = []
        for a in 'RYGB':
            for b in 'RYGB':
                placements += engine.native.ask(dict(op='placements', field=ref['field'], piece=f'2:{a}{b}'))['placements']
        trigger = next(c['locked_field'] for c in placements if len(c['links']) == 8)
        for pending, gauge, big, enemy_pending in ((20, 0, True, 0), (1, 0, True, 0),
                (1, 0, False, 0), (200, 6, True, 0), (1, 0, True, 1000)):
            own = side('normal', seed_with_small_green(), ['2:GY'])
            own.update(unconfirmed=pending, normal_unconfirmed=pending, gauge=gauge)
            enemy = side('normal', ref['field'] if big else ['......']*13+['RRR...'])
            enemy.update(confirmed=enemy_pending, normal_confirmed=enemy_pending)
            req = request(own, enemy)
            req['enemy_chain'] = dict(trigger_field=trigger if big else ['......']*13+['RRRR..'],
                elapsed=0, scored_links=0, mode_generation=0, seed_id=1)
            events = engine._enemy_events(req, enemy)
            projected = choose(engine.native, engine.scoring, own, 120,
                               enemy_events=events, enemy=enemy)['candidates']
            previous = next(c for c in projected if (c['x'], c['r']) == (1, 'U'))
            with patch.object(engine.solo, 'ask', return_value=dict(x=1, r='U')):
                start = time.perf_counter(); reply = engine.answer(req)
                cost = (time.perf_counter()-start)*1000
            cases.append(dict(request=req, enemy_events=events,
                fixed_solo_proposal=dict(x=1, r='U', chain=3),
                mainline_projection=previous, reply=reply, search_ms=cost))
        seed7 = next(s for s in refs['seeds'] if s['id'] == 'hirazumi-7')
        rows = list(seed7['field']); rows[4:7] = ['Y.....']*3
        for pending in (1000, 90):
            own = side('normal', rows, ['2:YR'])
            own.update(confirmed=pending, normal_confirmed=pending)
            req = request(own)
            waiting = wait_move(engine.native, engine.scoring, own, 120, 1)
            projected = choose(engine.native, engine.scoring, own, 120)['candidates']
            previous = next(c for c in projected if (c['x'], c['r']) == (waiting['x'], waiting['r']))
            start = time.perf_counter(); reply = engine.answer(req)
            cost = (time.perf_counter()-start)*1000
            cases.append(dict(request=req, enemy_events=[], former_gauge_wait_choice=waiting,
                mainline_projection=previous, reply=reply, search_ms=cost))
    finally:
        engine.close()
    report = dict(status='controlled_builder_move_public_seed_model_not_live_acceptance',
        native_sha256=hashlib.sha256(NATIVE.read_bytes()).hexdigest(), cases=cases)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps([dict(incoming=c['request']['self']['unconfirmed']+c['request']['self']['confirmed'],
        enemy_links=sum(e['type']=='link' for e in c['enemy_events']),
        enemy_pending=c['request']['enemy']['confirmed'],
        mainline_residual=c['mainline_projection']['pending_after_observed_chains'],
        chain=c['reply']['chain'], reason=c['reply']['reason'], ms=c['search_ms']) for c in cases]))


if __name__ == '__main__':
    main()
