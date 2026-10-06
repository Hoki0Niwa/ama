"""Protect normal-board trigger colors without changing battle safety priorities."""
def inspect(native, own):
    return native.ask(dict(op='normal_colors', field=own['field'], queue=own['queue'],
                           confirmed=own['confirmed']))


def apply(native, scoring, own, rate, reply, analysis=None, preserve_choice=False, allowed=None):
    if reply.get('normal_color_needs') is not None and reply.get('reason') in (
            'fever_wait_conserve', 'garbage_state_search'):
        return reply
    analysis = analysis or inspect(native, own)
    reply['normal_color_needs'] = analysis['needs']
    lookup = {(c['x'], c['r']): c for c in analysis['candidates']}
    selected = lookup.get((reply['x'], reply['r']))
    if selected is None:
        return reply
    reply['needed_color_consumed'] = selected['needed_color_consumed']
    before = analysis['needs']['mainline_chain']
    pending = own['confirmed'] + own['unconfirmed']
    if (own['confirmed'] and reply['fire'] and 0 < reply['chain'] < before and
            selected['remaining_chain'] >= before and
            not any(c['survives'] and c['chain'] >= before for c in analysis['candidates'])):
        reply.update(intentional_small_clear=True, hold_nuisance_for_missing_color=True)
    # Preserve proven survival/offset forecasts and completed mainline fires.
    # Gauge waiting and scheduled garbage search evaluate colors internally.
    if (preserve_choice or before < 2 or reply.get('selected_move_loses') or reply['next_all_clear'] or
            reply['chain'] >= before or reply.get('reason') not in
            ('normal_build_or_fire', 'unknown_nuisance_one_move_then_reobserve', 'observed_reachable_recovery')):
        return reply
    candidates = [c for c in analysis['candidates'] if c['survives']]
    if allowed is not None:
        candidates = [c for c in candidates if (c['x'], c['r']) in allowed]
    # A small clear can hold confirmed garbage while the mainline's trigger
    # color is missing. Keep it when replacing it would release a drop.
    if pending and reply['fire']:
        candidates = [c for c in candidates if c['chain'] > 0]
    elif not pending:
        candidates = [c for c in candidates if c['chain'] == 0]
    candidates = [c for c in candidates if c['remaining_chain'] >= before and
                  c['remaining_color_quality'] >= selected['remaining_color_quality'] + 80]
    if not candidates:
        return reply
    choice = max(candidates, key=lambda c:(c['remaining_color_quality'],
                         -c['needed_color_consumed'], -c['popped']))
    transition = native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                x=choice['x'], r=choice['r']))
    points = scoring.chain(own['character'], transition['links'])
    previous = dict(x=reply['x'], r=reply['r'], reason=reply['reason'])
    holding = bool(points) and bool(own['confirmed'])
    reply.update(x=choice['x'], r=choice['r'], fire=bool(points), chain=len(points),
        next_chain=len(points), next_score=sum(points), link_points=points,
        next_field=transition['field'] if points or not own['confirmed'] else None,
        next_all_clear=transition['all_clear'], searched_visible=len(own['queue']),
        needed_color_consumed=choice['needed_color_consumed'], decision_dependencies=['self'],
        reason='normal_color_hold_nuisance' if holding else 'normal_preserve_needed_colors',
        color_choice_previous=previous, intentional_small_clear=holding,
        normal_color_forecast=choice)
    return reply
