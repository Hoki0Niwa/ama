"""Visible-queue search whose states include deterministic nuisance landings."""
from __future__ import annotations

import json
from pathlib import Path
from .model import ROOT, Scoring, integer, settled_field
from .timing import ChainTiming


class GarbageSearch:
    def __init__(self, native, config):
        self.native = native
        self.weights = json.loads(Path(config).read_text(encoding='utf-8'))['fever']
        self.scoring = Scoring()

    def search(self, character, rows, queue, confirmed, unconfirmed, remainder, rate, garbage_phase, width=80,
               enemy_events=None, enemy_confirmed=0, enemy_unconfirmed=0, enemy_remainder=0, timing=None):
        if character not in self.scoring.data['characters']:
            raise ValueError('observed character ID required for offset scoring')
        result = self.native.ask(dict(op='garbage_search', field=settled_field(rows), queue=queue,
            confirmed=integer(confirmed, 'confirmed', 0, 10**9),
            unconfirmed=integer(unconfirmed, 'unconfirmed', 0, 10**9),
            remainder=integer(remainder, 'remainder', 0, 10**9),
            target_point=integer(rate, 'target_point', 1, 100000),
            garbage_phase=integer(garbage_phase, 'garbage_phase', 0, 5),
            enemy_events=enemy_events or [], enemy_confirmed=enemy_confirmed,
            enemy_unconfirmed=enemy_unconfirmed, enemy_remainder=enemy_remainder,
            timing=(timing or ChainTiming()).native(),
            width=integer(width, 'width', 1, 1000), weights=self.weights,
            powers=self.scoring.data['characters'][character]['normal'],
            bonuses=self.scoring.data['bonuses']), timeout=10)
        result['timing_status'] = (timing or ChainTiming()).effective_status
        return result

    @staticmethod
    def reply(result, shape):
        first = result['choice']
        points = first['link_points']
        reply = dict(x=first['x'], r=first['r'], shape=shape, reason='garbage_state_search',
            fire=bool(points), fire_moves=1 if points else 0, chain=len(points),
            next_chain=len(points), next_score=sum(points), link_points=points,
            next_field=first['field'], placement_field=first['placement_field'],
            next_all_clear=first['all_clear_requires_observed_seed'],
            all_clear_requires_observed_seed=first['all_clear_requires_observed_seed'],
            nuisance_forecast=result, timing_calibrated=False,
            chain_timing_calibrated=result.get('timing_status','').startswith('steam_15209927'),
            model_status='prototype_unverified_on_local_steam')
        if shape == '0':
            reply['color'] = 'RYGB'['URDL'.index(first['r'])]
        return reply
