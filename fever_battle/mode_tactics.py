"""Shared conservative policies motivated by Namoko's original strategy notes.

Thresholds are prototype heuristics, not a claim of an optimal battle policy.
Only visible pieces are used when estimating an opponent's immediate attack.
"""
from .model import convert


def offset_gauge(points, pending, remainder, rate, gauge, gain, maximum=7):
    cancelled, offsets = 0, 0
    for point in points:
        amount, remainder, _ = convert(point, remainder, rate, pending)
        taken = min(pending, amount)
        pending -= taken
        cancelled += taken
        offsets += bool(taken)
    return dict(gauge_after=min(maximum, gauge + gain * offsets), offset_links=offsets,
                cancelled=cancelled, remaining_pending=pending)


def seed_strategy(own, enemy, enemy_possible_score):
    # Avoid extension when incoming active-side garbage or a short deadline
    # makes another nonclearing placement dangerous.
    if own['fever_confirmed'] + own['fever_unconfirmed']:
        return 'quick', 'active_fever_nuisance'
    if own['remaining_frames'] <= 300:
        return 'quick', 'short_remaining_time'
    if enemy['mode'] == 'normal' and enemy['phase'] == 'controllable' and enemy_possible_score == 0:
        # This is only a visible-one-piece estimate of a distant mainline.
        return 'quick', 'no_immediate_visible_enemy_fire'
    if enemy['mode'] == 'fever' and enemy['normal_confirmed'] + enemy['normal_unconfirmed']:
        # Maintaining pressure while the opponent also has held nuisance is
        # a generalization of Namoko's immediate first-seed examples.
        return 'quick', 'enemy_has_held_nuisance'
    return 'extend', 'seek_visible_extension_or_all_clear'
