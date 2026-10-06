"""Normal-mode offset waiting with visible NEXT and color conservation."""
from .mode_tactics import offset_gauge


def choose(native, scoring, own, rate, gain, allowed=None, budget_ms=12):
    if own['mode'] != 'normal' or gain <= 0 or own['gauge'] >= 7 or not (own['confirmed']+own['unconfirmed']):
        return None
    request = dict(op='gauge_wait', field=own['field'], queue=own['queue'],
        confirmed=own['confirmed'], unconfirmed=own['unconfirmed'], gauge=own['gauge'],
        remainder=own['remainder'], gain=gain, target_point=rate, width=8, budget_ms=budget_ms,
        powers=scoring.data['characters'][own['character']]['normal'], bonuses=scoring.data['bonuses'])
    if allowed is not None:
        request['allowed'] = allowed
    forecast = native.ask(request)
    safe = [c for c in forecast['candidates'] if c['survives'] and c['projected_gauge'] > own['gauge']]
    if not safe:
        return None
    # Entering Fever comes first. Short of that, a link of the main chain is
    # worth more than the gauge step it would buy: singles earn the same steps.
    choice = max(safe, key=lambda c:(c['projected_gauge'] >= 7, -c['projected_needed_color_consumed'],
        c['projected_gauge'], -c['projected_popped'],
        -c['steps'], -c['popped'], -c['central_height'], -c['roughness']))
    current = native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                              x=choice['x'], r=choice['r']))
    points = scoring.chain(own['character'], current['links'])
    gauge = offset_gauge(points, own['confirmed']+own['unconfirmed'], own['remainder'], rate, own['gauge'], gain)
    return dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0], reason='fever_wait_conserve',
        fire=bool(points), chain=len(points), next_chain=len(points), next_score=sum(points),
        next_field=current['field'] if points or not own['confirmed'] else None,
        link_points=points, next_all_clear=current['all_clear'], selected_move_loses=False,
        decision_dependencies=['self'], gauge_forecast=gauge, entry_pending_after_chain=gauge['gauge_after']==7,
        wait_forecast={**forecast, 'choice':choice}, consumed_puyos=choice['popped'],
        normal_color_needs=forecast['color_needs'], needed_color_consumed=choice['needed_color_consumed'],
        searched_visible=forecast['completed_depth'])
