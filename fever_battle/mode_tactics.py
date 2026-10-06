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


QUICK_FRAMES = 300   # at or below this much Fever time the seed is fired, not extended


def seed_strategy(own, enemy, enemy_possible_score):
    # Pressure alone must not dismantle a seed with a small counter-chain.
    # The solver checks survival after confirmed drops for each build route.
    if own['remaining_frames'] <= QUICK_FRAMES:
        return 'quick', 'short_remaining_time'
    return 'extend', 'build_chain_for_next_fever_entry'
