"""Fast closure only after every rescue in the three visible pieces fails.

Unknown nuisance columns are enumerated, never reused as an observed field.
Any possible surviving clear, or surviving second drop, keeps ordinary play.
"""
from .timing import ChainTiming


def placement_frames(candidate, x=2, r='U'):
    """Estimated soft fall / simultaneous input, then lock and measured split."""
    turn = abs('URDL'.index(candidate['r']) - 'URDL'.index(r))
    move = 3 * (abs(candidate['x'] - x) + min(turn, 4 - turn))
    fall = 2 * max(0, 11 - candidate['contact_height'])
    split = ChainTiming().split_extra_frames[max(candidate['split_distances'], default=0)]
    return max(move, fall) + 14 + split


def choose(native, side, budget_ms=12):
    """Prove visible loss, then offer only placements ending within <=2 drops.

    Time exhaustion is inconclusive, not proof of loss. Unconfirmed packets
    are excluded, since they can still be offset by the other player.
    """
    if side['mode'] != 'normal' or side['confirmed'] <= 0:
        return None
    probe = dict(op='finish_probe', field=side['field'], piece=side['queue'][0],
                 confirmed=side['confirmed'], budget_ms=budget_ms)
    if len(side['queue']) > 1:
        probe['next_piece'] = side['queue'][1]
    if len(side['queue']) > 2:
        probe['last_piece'] = side['queue'][2]
    result = native.ask(probe)
    if not result['proved']:
        return None
    candidates = result['placements']
    finish = []
    for c in candidates:
        finish.append(dict(x=c['x'], r=c['r'], estimated_frames=placement_frames(c),
            contact_height=c['contact_height'], pivot_height=c['pivot_height'],
            split_distances=c['split_distances'], finish_after_drops=c['finish_after_drops'],
            links=c['links'], all_clear=c['all_clear']))
    best = min(finish, key=lambda c: (c['estimated_frames'], c['finish_after_drops'], abs(c['x']-2)))
    selected = next(c for c in candidates if (c['x'], c['r']) == (best['x'], best['r']))
    return dict(candidate=selected, candidates=finish, selected=best,
                proof='no_surviving_clear_or_escape_in_visible_queue',
                timing_status='input_estimated_split_calibrated')
