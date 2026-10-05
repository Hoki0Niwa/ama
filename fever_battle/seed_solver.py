"""Bounded observed-seed search using only current piece and NEXT2."""
from .model import integer
from .timing import ChainTiming


class SeedSolver:
    def __init__(self, native, scoring):
        self.native, self.scoring = native, scoring

    def solve(self, side, rate, count_chain_frames, options=None):
        options = options or {}
        if type(count_chain_frames) is not bool:
            raise ValueError('explicit count_chain_frames policy required')
        allowed = {'width', 'max_nodes', 'budget_ms', 'safety_frames', 'placement_frames', 'strategy'}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError('unknown seed solver option')
        budget = integer(options.get('budget_ms', 50), 'seed budget_ms', 1, 1000)
        timing = ChainTiming(placement_frames=integer(options.get('placement_frames', 14),
                                                     'placement_frames', 1, 10000))
        strategy = options.get('strategy', 'quick')
        if strategy not in ('quick', 'extend'):
            raise ValueError('unknown seed strategy')
        return self.native.ask(dict(op='seed_search', field=side['field'], queue=side['queue'],
            confirmed=side['fever_confirmed'], unconfirmed=side['fever_unconfirmed'],
            held_pending=side['normal_confirmed'] + side['normal_unconfirmed'],
            remainder=side['remainder'], garbage_phase=side['garbage_phase'],
            target_point=rate, remaining_frames=side['remaining_frames'], seed_chain=side['seed_chain'],
            count_chain_frames=count_chain_frames,
            strategy=strategy,
            width=integer(options.get('width', 64), 'seed width', 1, 1000),
            max_nodes=integer(options.get('max_nodes', 8000), 'seed max_nodes', 1, 100000),
            budget_ms=budget, safety_frames=integer(options.get('safety_frames', 8), 'safety_frames', 0, 600),
            timing=timing.native(), powers=self.scoring.data['characters'][side['character']]['fever'],
            bonuses=self.scoring.data['bonuses']), timeout=max(2, budget / 1000 + 1))
