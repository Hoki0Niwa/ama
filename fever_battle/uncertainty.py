"""One observed move when the next nuisance columns are unknown.

Enumerate every remainder-column subset, not just six cyclic permutations.
Do not continue a search on a guessed post-drop board.
"""
from itertools import combinations

from .model import convert, dead, integer
from .timing import ChainTiming
from .margin import rate_at


def outcomes(rows, count):
    integer(count, 'garbage count', 0, 30)
    whole, extra = divmod(count, 6)
    for columns in combinations(range(6), extra):
        board = [list(row) for row in rows]
        for x in range(6):
            height = sum(row[x] != '.' for row in rows[1:])
            amount = whole + (x in columns)
            for y in range(height, min(13, height + amount)):
                board[13-y][x] = '#'
        result = [''.join(row) for row in board]
        # Nuisance above row 13 vanishes; a full side column is no loss.
        yield result, dead(result)


def choose(native, scoring, side, rate, options=None, allowed_placements=None,
           enemy_events=None, enemy=None, margin=None, small_clears=False):
    """Rank real current-piece placements and reobserve after any actual drop.

    small_clears (normal board, offsets earn gauge): a clear ranks above a
    plain placement only when it stops a drop or offsets something, and the
    shortest such clear is preferred to the longest.
    """
    options = options or {}
    timing = ChainTiming.for_mode(side['mode'], placement_frames=integer(options.get('placement_frames', 14), 'placement_frames', 1, 10000))
    candidates = native.ask(dict(op='placements', field=side['field'], piece=side['queue'][0]))['placements']
    ranked = []
    for candidate in candidates:
        if allowed_placements is not None and (candidate['x'], candidate['r']) not in allowed_placements:
            continue
        points = scoring.chain(side['character'], candidate['links'], side['mode'])
        fire_at = timing.placement_frames + timing.split_extra_frames[max(candidate['split_distances'], default=0)] + (timing.first_link_frames if points else 0)
        check_at = fire_at + (0 if points else timing.nuisance_check_frames)
        fixed, flying, remainder = side['confirmed'], side['unconfirmed'], side['remainder']
        opponent = enemy or {}
        efixed, eflying = opponent.get('confirmed', 0), opponent.get('unconfirmed', 0)
        if opponent.get('mode') == 'fever':
            efixed += opponent.get('normal_confirmed', 0)
            eflying += opponent.get('normal_unconfirmed', 0)
        eremainder, cursor, cancelled, sent = opponent.get('remainder', 0), 0, 0, 0
        offset_links = 0
        events = enemy_events or []
        def advance(until):
            nonlocal cursor, fixed, flying, efixed, eflying, eremainder
            while cursor < len(events) and events[cursor]['frame'] <= until:
                event = events[cursor]; cursor += 1
                if event['type'] == 'end':
                    fixed += flying; flying = 0
                else:
                    active_rate = rate_at(rate, (margin or {}).get('enemy_rate_events'), event['frame'])
                    amount, eremainder, _ = convert(event['points'], eremainder, active_rate, efixed+eflying)
                    taken = min(efixed, amount); efixed -= taken; amount -= taken
                    taken = min(eflying, amount); eflying -= taken; amount -= taken
                    flying += amount
        advance(check_at)
        due = min(30, fixed)        # what falls on this placement unless it clears
        count = due if not points else 0
        fixed -= count
        cases = list(outcomes(candidate['field'], count))
        survives = not candidate['dead'] and all(not losing for _, losing in cases)
        chain = len(points)
        success = side['mode'] == 'fever' and chain >= side['seed_chain']
        heights = [sum(row[x] != '.' for row in candidate['field']) for x in range(6)]
        safety = integer(options.get('safety_frames', 8), 'safety_frames', 0, 600)
        in_time = side['mode'] == 'normal' or fire_at + safety < side['remaining_frames']
        # Clearing suppresses this placement's garbage drop, regardless of its columns.
        tier = (5 if survives and success and in_time else 4 if survives and chain and in_time
                else 3 if survives and in_time else 2 if survives else 1)
        rank = (tier, chain, -max(heights[2:4]), -sum(h*h for h in heights))
        end_at = fire_at + sum(timing.duration(distance, features, terminal=i == chain-1)
            for i, (distance, features) in enumerate(zip(candidate['fall_distances'], candidate['fall_features'])))
        held = side['normal_confirmed']+side['normal_unconfirmed'] if side['mode']=='fever' else 0
        onset = fire_at
        for i, point in enumerate(points):
            advance(onset)
            active_rate = rate_at(rate, (margin or {}).get('rate_events'), onset)
            amount, remainder, _ = convert(point, remainder, active_rate, fixed+flying+held)
            cancelled_before = cancelled
            taken = min(fixed, amount); fixed -= taken; amount -= taken; cancelled += taken
            taken = min(flying, amount); flying -= taken; amount -= taken; cancelled += taken
            taken = min(held, amount); held -= taken; amount -= taken; cancelled += taken
            offset_links += cancelled > cancelled_before
            sent += amount; eflying += amount
            onset += timing.duration(candidate['fall_distances'][i], candidate['fall_features'][i], terminal=i==chain-1)
        # A counter is judged against the entire observed attack, including
        # links that occur after our chain finishes. Our outgoing points must
        # first offset the enemy's pending packets before its tail reaches us.
        exchange_at = max(end_at, max((e['frame'] for e in events), default=0))
        advance(exchange_at)
        if small_clears and side['mode'] == 'normal':
            useful = bool(chain) and bool(due or cancelled)
            rank = (4 if survives and useful else 3 if survives else 1, -chain,
                    -max(heights[2:4]), -sum(h*h for h in heights))
        first = dict(x=candidate['x'], r=candidate['r'], field=candidate['field'],
            locked_field=candidate['locked_field'], chain=chain, link_points=points,
            all_clear=candidate['all_clear'], fire_at=fire_at, end_at=end_at, in_time=in_time,
            dead=not survives, dropped=count, cancelled=cancelled, sent=sent,
            offset_links=offset_links, pending_after_observed_chains=fixed+flying+held,
            exchange_at=exchange_at,
            garbage_phase=None, post_drop_field_known=count == 0,
            possible_drop_boards=len(cases), uncertainty='all_remainder_column_subsets')
        first['nuisance_check_at'] = check_at if not points else None
        ranked.append((rank, first))
    if not ranked:
        raise ValueError('no conservative legal placement')
    first = max(ranked, key=lambda item: item[0])[1]
    return dict(choice=first, path=[first], candidates=[item[1] for item in ranked], solved=side['mode'] == 'fever' and not first['dead'] and
        first['in_time'] and first['chain'] >= side['seed_chain'],
        searched_visible=1, requires_new_seed_after_clear=bool(first['chain']),
        strategy='observed_one_move_then_reobserve', uncertainty='unknown_nuisance_columns')
