"""Bounded observed-seed search using only current piece and NEXT2."""
from .model import integer
from .timing import ChainTiming


class SeedSolver:
    def __init__(self, native, scoring):
        self.native, self.scoring = native, scoring
        self.seed_origin = None

    @staticmethod
    def validate_options(options):
        allowed = {'width', 'max_nodes', 'budget_ms', 'safety_frames', 'placement_frames', 'strategy'}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError('unknown seed solver option')
        bounds = dict(width=(1,1000), max_nodes=(1,100000), budget_ms=(1,1000),
                      safety_frames=(0,600), placement_frames=(1,10000))
        for key, value in options.items():
            if key in bounds:
                integer(value, key, *bounds[key])
        if options.get('strategy', 'quick') not in ('quick', 'extend'):
            raise ValueError('unknown seed strategy')

    def solve(self, side, rate, count_chain_frames, options=None, match_id=None, allowed=None):
        options = options or {}
        if type(count_chain_frames) is not bool:
            raise ValueError('explicit count_chain_frames policy required')
        self.validate_options(options)
        budget = integer(options.get('budget_ms', 50), 'seed budget_ms', 1, 1000)
        timing = ChainTiming(placement_frames=integer(options.get('placement_frames', 14),
                                                     'placement_frames', 1, 10000))
        strategy = options.get('strategy', 'quick')
        if strategy not in ('quick', 'extend'):
            raise ValueError('unknown seed strategy')
        has_history = all(key in side for key in ('mode_generation', 'seed_id', 'piece_id'))
        if has_history:
            key = (match_id, side['mode_generation'], side['seed_id'], side['character'])
            if self.seed_origin is None or self.seed_origin[0] != key or side['piece_id'] < self.seed_origin[1]:
                self.seed_origin = (key, side['piece_id'])
            extension_moves = side['piece_id'] - self.seed_origin[1]
        else:
            extension_moves = 0  # Offline geometry checks have no live history.
        result = self.native.ask(dict(op='seed_search', field=side['field'], queue=side['queue'],
            confirmed=side['fever_confirmed'], unconfirmed=side['fever_unconfirmed'],
            held_pending=side['normal_confirmed'] + side['normal_unconfirmed'],
            remainder=side['remainder'], garbage_phase=side['garbage_phase'] or 0,
            unknown_garbage_phase=side['garbage_phase'] is None,
            target_point=rate, remaining_frames=side['remaining_frames'], seed_chain=side['seed_chain'],
            count_chain_frames=count_chain_frames,
            strategy=strategy,
            extension_moves=extension_moves,
            width=integer(options.get('width', 64), 'seed width', 1, 1000),
            max_nodes=integer(options.get('max_nodes', 8000), 'seed max_nodes', 1, 100000),
            budget_ms=budget, safety_frames=integer(options.get('safety_frames', 8), 'safety_frames', 0, 600),
            timing=timing.native(), powers=self.scoring.data['characters'][side['character']]['fever'],
            bonuses=self.scoring.data['bonuses'], **({'allowed': allowed} if allowed is not None else {})),
            timeout=max(2, budget / 1000 + 1))
        result['extension_history_status'] = ('placements_since_first_observed_seed' if has_history
                                              else 'unavailable_offline_single_seed')
        if side['garbage_phase'] is None:
            result['garbage_phase_status'] = ('unknown_all_remainder_column_subsets' if side['confirmed']
                else 'unknown_no_confirmed_drop_forecast')
            if not result['choice']['post_drop_field_known']:
                result.update(uncertainty='unknown_nuisance_columns', searched_visible=1)
        return result
