"""One observed move when the next nuisance columns are unknown.

Enumerate every remainder-column subset, not just six cyclic permutations.
Do not continue a search on a guessed post-drop board.
"""
from itertools import combinations

from .model import convert, dead, integer
from .timing import ChainTiming


def outcomes(rows, count):
    integer(count, 'garbage count', 0, 30)
    whole, extra = divmod(count, 6)
    for columns in combinations(range(6), extra):
        board = [list(row) for row in rows]
        overflow = False
        for x in range(6):
            height = sum(row[x] != '.' for row in rows[1:])
            amount = whole + (x in columns)
            overflow |= height + amount > 13
            for y in range(height, min(13, height + amount)):
                board[13-y][x] = '#'
        result = [''.join(row) for row in board]
        yield result, overflow or dead(result)


def choose(native, scoring, side, rate, options=None, allowed_placements=None):
    """Rank real current-piece placements and reobserve after any actual drop."""
    options = options or {}
    timing = ChainTiming(placement_frames=integer(options.get('placement_frames', 14), 'placement_frames', 1, 10000))
    candidates = native.ask(dict(op='placements', field=side['field'], piece=side['queue'][0]))['placements']
    ranked = []
    for candidate in candidates:
        if allowed_placements is not None and (candidate['x'], candidate['r']) not in allowed_placements:
            continue
        points = scoring.chain(side['character'], candidate['links'], side['mode'])
        count = min(30, side['confirmed']) if not points else 0
        cases = list(outcomes(candidate['field'], count))
        survives = not candidate['dead'] and all(not losing for _, losing in cases)
        chain = len(points)
        success = side['mode'] == 'fever' and chain >= side['seed_chain']
        heights = [sum(row[x] != '.' for row in candidate['field']) for x in range(6)]
        fire_at = timing.placement_frames + timing.split_extra_frames[max(candidate['split_distances'], default=0)] + (15 if chain else 0)
        safety = integer(options.get('safety_frames', 8), 'safety_frames', 0, 600)
        in_time = side['mode'] == 'normal' or fire_at + safety < side['remaining_frames']
        # Clearing suppresses this placement's garbage drop, regardless of its columns.
        tier = (5 if survives and success and in_time else 4 if survives and chain and in_time
                else 3 if survives and in_time else 2 if survives else 1)
        rank = (tier, chain, -max(heights[2:4]), -sum(h*h for h in heights))
        end_at = fire_at + sum(timing.duration(distance, features, terminal=i == chain-1)
            for i, (distance, features) in enumerate(zip(candidate['fall_distances'], candidate['fall_features'])))
        sent, cancelled, pending, remainder = 0, 0, side['confirmed']+side['unconfirmed'], side['remainder']
        if side['mode'] == 'fever':
            pending += side['normal_confirmed'] + side['normal_unconfirmed']
        for point in points:
            amount, remainder, _ = convert(point, remainder, rate, pending)
            taken = min(pending, amount); pending -= taken
            cancelled += taken; sent += amount-taken
        first = dict(x=candidate['x'], r=candidate['r'], field=candidate['field'],
            locked_field=candidate['locked_field'], chain=chain, link_points=points,
            all_clear=candidate['all_clear'], fire_at=fire_at, end_at=end_at, in_time=in_time,
            dead=not survives, dropped=count, cancelled=cancelled, sent=sent,
            garbage_phase=None, post_drop_field_known=count == 0,
            possible_drop_boards=len(cases), uncertainty='all_remainder_column_subsets')
        ranked.append((rank, first))
    if not ranked:
        raise ValueError('no conservative legal placement')
    first = max(ranked, key=lambda item: item[0])[1]
    return dict(choice=first, path=[first], solved=side['mode'] == 'fever' and not first['dead'] and
        first['in_time'] and first['chain'] >= side['seed_chain'],
        searched_visible=1, requires_new_seed_after_clear=bool(first['chain']),
        strategy='observed_one_move_then_reobserve', uncertainty='unknown_nuisance_columns')
