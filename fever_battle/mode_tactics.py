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


QUICK_FRAMES = 300   # short-clock region: only visible executable continuations
