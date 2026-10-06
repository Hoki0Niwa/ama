"""Normal-board answer to incoming nuisance under the Fever rule.

An offset of any size stops the drop and earns one gauge step per link, so the
Tsu habit of answering an attack with the longest chain at hand only spends
the main chain. While nothing can actually fall on this placement, stack
without clearing and keep small triggers ready; when a drop is due, hand over
to the smallest offsets (gauge_wait). Thresholds are prototype heuristics.
"""
from .gauge_wait import choose as wait_move
from .model import dead
from .normal_colors import inspect
from .uncertainty import choose as ranked_moves, outcomes

HOARD_REASON = 'fever_wait_hoard_until_drop'
PRESERVE_REASON = 'fever_small_offset_preserve_mainline'


def _heights(rows):
    return [sum(row[x] != '.' for row in rows) for x in range(6)]


def _stands(rows, count):
    """Every column subset of a drop leaves the board alive (a full side column is no loss)."""
    return all(not losing for _, losing in outcomes(rows, count))


def choose(native, scoring, own, rate, gain, policy=None, allowed=None,
           enemy_events=None, enemy=None, margin=None, offset_search=True, build=None):
    """A hoarding or minimal-offset reply, or None to keep the ordinary search.

    build() is the chain builder's own (x, r) for this piece. Keep its stacking
    move while nothing falls, but accept its clear only when the observed
    exchange can be countered. Otherwise preserve the mainline for Fever.
    """
    pending = own['confirmed'] + own['unconfirmed']
    events = enemy_events or []
    if own['mode'] != 'normal' or gain <= 0 or own['gauge'] >= 7 or not (pending or events):
        return None
    policy = policy or {}
    moves = None if allowed is None else {(m['x'], m['r']) for m in allowed}
    try:
        candidates = ranked_moves(native, scoring, own, rate, allowed_placements=moves,
            enemy_events=events, enemy=enemy, margin=margin)['candidates']
    except ValueError:
        return None
    alive = [c for c in candidates if not c['dead']]
    # One more offset already enters Fever: nothing is gained by stocking up.
    stocking = own['gauge'] + gain < 7
    quiet = [c for c in alive if not c['chain'] and not c['dropped']] if stocking else []
    dependencies = ['self', 'enemy'] if events else ['self']
    built = None
    rejected = None
    def explain(reply):
        if rejected is not None:
            reply['mainline_counter_forecast'] = dict(
                rejected_move=dict(x=rejected['x'], r=rejected['r'], chain=rejected['chain']),
                cancelled=rejected['cancelled'], sent=rejected['sent'],
                pending_after_observed_chains=rejected['pending_after_observed_chains'],
                gauge_after=min(7, own['gauge']+gain*rejected['offset_links']),
                exchange_at=rejected['exchange_at'],
                status='insufficient_counter_preserve_mainline_until_offset_needed')
        return reply
    def offset_reply(choice, count, reason='fever_small_offset'):
        return explain(dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0], reason=reason,
            fire=True, chain=choice['chain'], next_chain=choice['chain'], next_score=sum(choice['link_points']),
            link_points=choice['link_points'], next_field=choice['field'], next_all_clear=choice['all_clear'],
            selected_move_loses=False, decision_dependencies=dependencies,
            searched_visible=1, offset_forecast=dict(cancelled=choice['cancelled'], sent=choice['sent'],
                pending_after_observed_chains=choice['pending_after_observed_chains'], candidates=count)))
    if quiet and build is not None:
        move = build()
        built = next((c for c in alive if (c['x'], c['r']) == move), None)
    if built is not None and built['chain'] and built['pending_after_observed_chains']:
        # The solo builder does not see the opponent's attack. Spending the
        # main chain on a partial counter is worse than keeping it and small
        # offsets for Fever entry. If no safe stock move remains, the offset
        # search below can still select a necessary emergency clear.
        rejected, built = built, None
    if built is not None and built['chain']:
        return dict(x=built['x'], r=built['r'], shape=own['queue'][0][0], reason='fever_wait_builder_clear',
            fire=True, chain=built['chain'], next_chain=built['chain'], next_score=sum(built['link_points']),
            link_points=built['link_points'], next_field=built['field'], next_all_clear=built['all_clear'],
            selected_move_loses=False, decision_dependencies=dependencies, searched_visible=len(own['queue']))
    if quiet:
        # Unscheduled packets may be confirmed while this piece falls: the
        # board must also stand the largest drop that could follow.
        incoming = max(c['pending_after_observed_chains'] for c in quiet)
        limit = policy.get('hoard_max_central_height', 8)
        roomy = [c for c in quiet if max(_heights(c['field'])[2:4]) <= limit and
                 _stands(c['field'], min(30, incoming))]
        if not roomy and not pending:
            # Nothing is in the tray yet and no clear can offset anything: a
            # chain fired now only spends the board. Keep stacking.
            roomy = quiet
        # The height limit is for the stock heuristic; the builder's move only has to stand the drop.
        if built is not None and (any(c is built for c in roomy) or _stands(built['field'], min(30, incoming))):
            return explain(dict(x=built['x'], r=built['r'], shape=own['queue'][0][0], reason=HOARD_REASON,
                fire=False, chain=0, next_chain=0, next_score=0, link_points=[],
                next_field=built['field'], next_all_clear=False, selected_move_loses=False,
                decision_dependencies=dependencies, searched_visible=len(own['queue']),
                hoard_forecast=dict(source='chain_builder', incoming_estimate=incoming,
                    nuisance_check_at=built['nuisance_check_at'], candidates=len(roomy),
                    status='no_drop_predicted_on_this_placement_reobserve_next_piece')))
        quiet = roomy
    if quiet:
        before = inspect(native, own)['needs']
        queue = own['queue'][1:] or own['queue']
        ranked = []
        for c in quiet:
            needs = inspect(native, {**own, 'field': c['field'], 'queue': queue, 'confirmed': 0})['needs']
            ports = needs['mainline'] + [p for p in needs['offsets'] if p['chain'] != needs['mainline_chain']]
            ready = {p['x'] for p in ports if p['needed_cells'] == 1}
            heights = _heights(c['field'])
            ranked.append(((needs['mainline_chain'] >= before['mainline_chain'],
                any(not p['missing_visible_cells'] for p in ports), len(ready), needs['quality'],
                -max(heights[2:4]), -sum(h*h for h in heights)), c, needs, len(ready)))
        _, choice, needs, ready = max(ranked, key=lambda item: item[0])
        return explain(dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0], reason=HOARD_REASON,
            fire=False, chain=0, next_chain=0, next_score=0, link_points=[],
            next_field=choice['field'], next_all_clear=False, selected_move_loses=False,
            decision_dependencies=['self', 'enemy'] if events else ['self'],
            normal_color_needs=before, needed_color_consumed=0, searched_visible=1,
            hoard_forecast=dict(source='stock_heuristic_builder_move_unavailable', ready_triggers=ready, mainline_chain=needs['mainline_chain'],
                incoming_estimate=incoming, nuisance_check_at=choice['nuisance_check_at'],
                candidates=len(quiet), status='no_drop_predicted_on_this_placement_reobserve_next_piece')))
    waiting = wait_move(native, scoring, own, rate, gain, allowed) if offset_search else None
    if waiting is not None:
        chosen = next((c for c in alive if (c['x'], c['r']) == (waiting['x'], waiting['r'])), None)
        if chosen and chosen['chain'] > 1 and chosen['pending_after_observed_chains']:
            # Immediate gauge completion must not spend an insufficient main
            # chain if a real smaller offset preserves that chain and stops
            # this drop. Unknown next pieces are reobserved, not promised.
            colors = inspect(native, own)
            mainline = colors['needs']['mainline_chain']
            lookup = {(c['x'], c['r']): c for c in colors['candidates']}
            small = [c for c in alive if 0 < c['chain'] < mainline <= chosen['chain'] and c['cancelled'] and
                     lookup[(c['x'], c['r'])]['remaining_chain'] >= mainline]
            if small:
                rejected = chosen
                choice = min(small, key=lambda c: (c['chain'],
                    lookup[(c['x'], c['r'])]['needed_color_consumed'], sum(c['link_points'])))
                reply = offset_reply(choice, len(small), PRESERVE_REASON)
                reply['preserved_mainline_chain'] = mainline
                return reply
        return explain(waiting)
    # The packets arrive while this piece falls (an observed chain): the offset
    # search does not see them. Stop the drop with the shortest clear that
    # offsets, never with the longest chain on the board.
    useful = [c for c in alive if c['chain'] and c['cancelled']]
    if not useful:
        return None
    choice = min(useful, key=lambda c: (c['chain'], sum(c['link_points']), max(_heights(c['field'])[2:4])))
    return offset_reply(choice, len(useful))
