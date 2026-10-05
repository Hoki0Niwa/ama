"""Normal-board battle JSON protocol, built around the unchanged solo engine.

Run python -m fever_battle.engine --native ... --solo ... --config ... .
This is a separate prototype entry point, not a replacement for live sessions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .model import ROOT, Referee, Scoring, convert, dead, drop_garbage, integer, settled_field
from .worker import JsonProcess
from .observation import coherent
from .forecast import GarbageSearch
from .timing import predict_chain
from .threat import enemy_events

SOLO_OPTIONS = {'trigger', 'stretch', 'panic_count', 'panic_chain', 'panic_step', 'shave_chain',
                'margin', 'patience', 'patience_step', 'beam_width', 'beam_depth'}


class BattleEngine:
    def __init__(self, native, solo, config):
        self.native = JsonProcess([native], cwd=ROOT)
        try:
            self.solo = JsonProcess([solo, config], cwd=ROOT)
        except Exception:
            self.native.close()
            raise
        self.scoring = Scoring()
        self.garbage_search = GarbageSearch(self.native, config)
        self.policy = json.loads((ROOT / 'data/fever/battle_policy.json').read_text(encoding='utf-8'))
        self.patterns = {c['id']: c['pattern'] for c in
                         json.loads((ROOT / 'data/fever/dropsets.json').read_text(encoding='utf-8'))['characters']}

    def close(self):
        self.native.close()
        self.solo.close()

    def side(self, side):
        character = side['character']
        if character not in self.patterns:
            raise ValueError('unknown character; a character ID cannot be inferred solely from its cycle')
        if side.get('mode') != 'normal' or type(side.get('gauge')) is not int or side['gauge'] != 0:
            raise ValueError('this prototype requires observed normal mode and gauge=0 for both players')
        index = integer(side['dropset_index'], 'dropset_index')
        queue = side['queue']
        if not isinstance(queue, list) or not 1 <= len(queue) <= 3:
            raise ValueError('only current piece plus NEXT2 may be passed')
        for k, text in enumerate(queue):
            if not isinstance(text, str) or text[:1] != self.patterns[character][(index + k) % 16]:
                raise ValueError('visible piece does not match dropset position')
        rows = settled_field(side['field'])
        self.native.ask({'op': 'validate', 'field': rows})
        # Native parser validates colors and orientation as well as geometry.
        self.native.ask({'op': 'placements', 'field': rows, 'piece': queue[0]})
        for text in queue[1:]:
            self.native.ask({'op': 'placements', 'field': ['......'] * 14, 'piece': text})
        integer(side['confirmed'], 'confirmed nuisance')
        integer(side['unconfirmed'], 'unconfirmed nuisance')
        integer(side['remainder'], 'unconverted points')
        integer(side['piece_id'], 'piece_id')
        integer(side['moves_since_chain'], 'moves_since_chain')
        integer(side['garbage_phase'], 'garbage_phase', 0, 5)
        return side

    def answer(self, request):
        op = request.get('op', 'think')
        if op == 'score':
            points = self.scoring.chain(request['character'], request['links'])
            return {'points': points, 'total': sum(points), 'provenance': self.scoring.provenance}
        if op == 'predict_chain':
            return predict_chain(self.native, self.scoring, request['character'], request['trigger_field'])
        if op == 'referee':
            referee = Referee(request['characters'], request.get('target_point', 120),
                              request.get('gauge_gain_on_offset', 0))
            for event in request['events']:
                referee.apply(event)
            return {**referee.snapshot(), 'log': referee.log}
        if op != 'think':
            raise ValueError('unsupported operation')
        if request.get('protocol_version') != 2 or request.get('rule') != 'fever_normal_battle':
            raise ValueError('requires protocol_version=2 and rule=fever_normal_battle')
        if type(request.get('gauge_gain_on_offset')) is not int or request['gauge_gain_on_offset'] != 0:
            raise ValueError('requires explicit gauge_gain_on_offset=0')
        if not isinstance(request.get('match_id'), str) or not request['match_id']:
            raise ValueError('match_id required')
        integer(request['frame'], 'frame')
        coherent(request)
        rate = integer(request['target_point'], 'target_point', 1, 100000)
        own = self.side(request['self'])
        enemy = self.side(request['enemy'])
        overrides = request.get('solo_options', {})
        if not isinstance(overrides, dict) or set(overrides) - SOLO_OPTIONS:
            raise ValueError('unknown solo option')
        options = {**self.policy['solo_options'], **overrides, 'moves': own['moves_since_chain']}
        if request.get('self', {}).get('awaiting_seed', False):
            raise ValueError('observed all-clear seed must be loaded before deciding a new move')
        started = time.monotonic()
        placements = self.native.ask({'op': 'placements', 'field': own['field'], 'piece': own['queue'][0]})['placements']
        safe = [p for p in placements if not p['dead']]
        if not safe:
            raise ValueError('no surviving conservative placement')
        pending = own['confirmed'] + own['unconfirmed']
        scheduled = []
        chain_prediction = request.get('enemy_chain')
        if chain_prediction is not None:
            # This board was captured at the chain's clearing lock, before the first pop.
            prediction = predict_chain(self.native, self.scoring, enemy['character'], chain_prediction['trigger_field'])
            scheduled = enemy_events(prediction, integer(chain_prediction['elapsed'], 'elapsed'),
                                     integer(chain_prediction['scored_links'], 'scored_links', 0, len(prediction['links'])))
        # Immediate exact threats from the opponent's visible first piece. This
        # is a possibility, not a confirmed scheduled attack.
        enemy_moves = (self.native.ask({'op': 'placements', 'field': enemy['field'],
                                      'piece': enemy['queue'][0]})['placements']
                       if enemy['phase'] == 'controllable' else [])
        potential = max((sum(self.scoring.chain(enemy['character'], p['links'])) for p in enemy_moves if not p['dead']), default=0)
        chosen, reason, forecast = None, None, None
        if pending or scheduled:
            forecast = self.garbage_search.search(own['character'], own['field'], own['queue'],
                own['confirmed'], own['unconfirmed'], own['remainder'], rate, own['garbage_phase'],
                min(1000, options.get('beam_width', 80)), enemy_events=scheduled,
                enemy_confirmed=enemy['confirmed'], enemy_unconfirmed=enemy['unconfirmed'],
                enemy_remainder=enemy['remainder'])
            first = forecast['choice']
            chosen = next(p for p in safe if p['x'] == first['x'] and p['r'] == first['r'])
            reason = 'garbage_state_search'
        if chosen is None:
            solo_request = dict(rule='fever', character=own['character'], dropset_index=own['dropset_index'],
                                solo=True, self={'field': own['field'], 'queue': own['queue']},
                                plain_pairs=True, include_next=True, **options)
            result = self.solo.ask(solo_request, timeout=10)
            chosen = next((p for p in safe if p['x'] == result['x'] and p['r'] == result['r']), None)
            reason = 'build_or_solo_fire'
            if chosen is None:
                chosen = safe[0]
                reason = 'conservative_route_fallback'
        points = self.scoring.chain(own['character'], chosen['links'])
        reply = {'x': chosen['x'], 'r': chosen['r'], 'shape': own['queue'][0][0], 'reason': reason,
                 'fire': bool(points), 'fire_moves': 1 if points else 0, 'chain': len(points),
                 'next_chain': len(points), 'next_score': sum(points), 'next_field': chosen['field'],
                 'link_points': points, 'next_all_clear': chosen['all_clear'],
                 'all_clear_requires_observed_seed': chosen['all_clear'],
                 'enemy_possible_score_now': potential, 'enemy_possible_is_confirmed': False,
                 'enemy_current_piece_controllable': enemy['phase'] == 'controllable',
                 'decision_identity': {'match_id': request['match_id'], 'frame': request['frame'],
                                       'piece_id': own['piece_id'], 'dropset_index': own['dropset_index']},
                 'model_status': 'prototype_unverified_on_local_steam', 'provenance': self.scoring.provenance,
                 'timing_calibrated': False, 'search_ms': (time.monotonic() - started) * 1000}
        if reply['shape'] == '0':
            reply['color'] = 'RYGB'['URDL'.index(reply['r'])]
        if forecast is not None:
            reply.update(GarbageSearch.reply(forecast, reply['shape']))
        return reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT / 'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--solo', type=Path, default=ROOT / 'bin/fever/fever.exe')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    args = parser.parse_args()
    engine = BattleEngine(args.native, args.solo, args.config)
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                reply = engine.answer(json.loads(line))
            except (ValueError, KeyError, TypeError, TimeoutError, RuntimeError) as error:
                reply = {'error': str(error)}
            print(json.dumps(reply, ensure_ascii=False), flush=True)
    finally:
        engine.close()


if __name__ == '__main__':
    main()
