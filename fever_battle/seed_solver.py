"""Bounded observed-seed search using only current piece and NEXT2."""
from .model import drop_garbage, integer
from .timing import ChainTiming


class SeedSolver:
    def __init__(self, native, scoring):
        self.native, self.scoring = native, scoring
        self.value_model = None     # constants of the value measure; None leaves the worker's defaults

    @staticmethod
    def validate_options(options):
        allowed = {'width', 'max_nodes', 'budget_ms', 'safety_frames', 'placement_frames'}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError('unknown seed solver option')
        bounds = dict(width=(1,1000), max_nodes=(1,100000), budget_ms=(1,1000),
                      safety_frames=(0,600), placement_frames=(1,10000))
        for key, value in options.items():
            if key in bounds:
                integer(value, key, *bounds[key])

    def solve(self, side, rate, count_chain_frames, options=None, match_id=None, allowed=None,
              enemy_events=None, enemy=None, maximum_frames=1800, margin=None,
              quiet_carry_limit=None):
        options = options or {}
        if type(count_chain_frames) is not bool:
            raise ValueError('explicit count_chain_frames policy required')
        self.validate_options(options)
        budget = integer(options.get('budget_ms', 50), 'seed budget_ms', 1, 1000)
        timing = ChainTiming.for_mode('fever', placement_frames=integer(options.get('placement_frames', 14),
                                                                      'placement_frames', 1, 10000))
        result = self.native.ask(dict(op='seed_search', field=side['field'], queue=side['queue'],
            enemy_events=enemy_events or [],
            rate_events=(margin or {}).get('rate_events', []),
            enemy_rate_events=(margin or {}).get('enemy_rate_events', []),
            enemy_confirmed=(enemy or {}).get('confirmed', 0) + ((enemy or {}).get('normal_confirmed', 0) if (enemy or {}).get('mode')=='fever' else 0),
            enemy_unconfirmed=(enemy or {}).get('unconfirmed', 0) + ((enemy or {}).get('normal_unconfirmed', 0) if (enemy or {}).get('mode')=='fever' else 0),
            enemy_remainder=(enemy or {}).get('remainder', 0),
            confirmed=side['fever_confirmed'], unconfirmed=side['fever_unconfirmed'],
            held_pending=side['normal_confirmed'] + side['normal_unconfirmed'],
            remainder=side['remainder'], garbage_phase=side['garbage_phase'] or 0,
            unknown_garbage_phase=side['garbage_phase'] is None,
            target_point=rate, remaining_frames=side['remaining_frames'], seed_chain=side['seed_chain'],
            maximum_frames=integer(maximum_frames, 'maximum_frames', 1800, 1860),
            count_chain_frames=count_chain_frames,
            width=integer(options.get('width', 64), 'seed width', 1, 1000),
            max_nodes=integer(options.get('max_nodes', 8000), 'seed max_nodes', 1, 100000),
            budget_ms=budget, safety_frames=integer(options.get('safety_frames', 8), 'safety_frames', 0, 600),
            timing=timing.native(), powers=self.scoring.data['characters'][side['character']]['fever'],
            bonuses=self.scoring.data['bonuses'], **({'allowed': allowed} if allowed is not None else {}),
            **({'value_model': self.value_model} if self.value_model is not None else {}),
            **({} if quiet_carry_limit is None else dict(
                quiet_carry_limit=integer(quiet_carry_limit, 'quiet_carry_limit', 0, 10**9)))),
            timeout=max(2, budget / 1000 + 1))
        result['timing_status'] = timing.effective_status
        result['timing_constants'] = timing.native()
        result['seed_exchange_status'] = 'measured_range_with_estimated_budget_not_universal_bound'
        if side['garbage_phase'] is None:
            result['garbage_phase_status'] = ('unknown_all_remainder_column_subsets' if side['confirmed']
                else 'unknown_no_confirmed_drop_forecast')
            if not result['choice']['post_drop_field_known']:
                result.update(uncertainty='unknown_nuisance_columns', searched_visible=1)
        return result


def verify(native, scoring, own, result):
    """Check a solver line against the worker's own transitions: boards, points and drops."""
    field = own['field']
    for depth, step in enumerate(result['path']):
        actual = native.ask(dict(op='transition', field=field, piece=own['queue'][depth],
                                x=step['x'], r=step['r']))
        assert actual['locked_field'] == step['locked_field']
        assert scoring.chain(own['character'], actual['links'], 'fever') == step['link_points']
        assert not step['chain'] or depth == len(result['path']) - 1
        if not step['dropped']:
            assert actual['field'] == step['field']
        elif step.get('post_drop_field_known', True):
            if step['garbage_phase'] is None:
                assert step['dropped'] % 6 == 0  # full rows do not depend on remainder order
                before_phase = 0
            else:
                before_phase = (step['garbage_phase'] - step['dropped']) % 6
            dropped, _ = drop_garbage(actual['field'], step['dropped'], before_phase)
            assert dropped == step['field']
        field = step['field']
    if result['solved']:
        assert result['path'][-1]['chain'] >= own['seed_chain']
