"""Normal board under threat, decided by the worker's single search (op tactics).

Stacking until a drop is due, the smallest offset, firing the main chain and
taking a drop are placements of one search with one value; see
fever_battle/tactics.cpp. The weights are prototype values of
data/fever/battle_policy.json, not tuned in battle.
"""
from .timing import ChainTiming

KINDS = {
    'stack': 'tactics_stack',            # pops nothing, nothing falls on this placement
    'take': 'tactics_take_drop',         # pops nothing and takes the drop
    'offset': 'tactics_offset',          # pops and offsets pending nuisance
    'clear': 'tactics_clear',            # pops without offsetting anything
}


def kind(choice):
    if choice['chain']:
        return 'offset' if choice['cancelled'] else 'clear'
    return 'take' if choice['dropped'] else 'stack'


def choose(native, scoring, own, rate, gain, policy, enemy_events=None, enemy=None, margin=None,
           allowed=None, builder=None):
    """The reply for this piece, or None when no placement can be played at all."""
    opponent, margin = enemy or {}, margin or {}
    held = opponent.get('mode') == 'fever'
    request = dict(op='tactics', field=own['field'], queue=own['queue'],
        confirmed=own['confirmed'], unconfirmed=own['unconfirmed'], remainder=own['remainder'],
        garbage_phase=own['garbage_phase'] or 0, unknown_garbage_phase=own['garbage_phase'] is None,
        gauge=own['gauge'], gain=gain, target_point=rate,
        rate_events=margin.get('rate_events', []), enemy_rate_events=margin.get('enemy_rate_events', []),
        enemy_events=enemy_events or [],
        enemy_confirmed=opponent.get('confirmed', 0) + (opponent.get('normal_confirmed', 0) if held else 0),
        enemy_unconfirmed=opponent.get('unconfirmed', 0) + (opponent.get('normal_unconfirmed', 0) if held else 0),
        enemy_remainder=opponent.get('remainder', 0),
        timing=ChainTiming().native(), powers=scoring.data['characters'][own['character']]['normal'],
        bonuses=scoring.data['bonuses'], weights=policy['weights'],
        width=policy.get('width', 12), max_nodes=policy.get('max_nodes', 6000),
        budget_ms=policy.get('budget_ms', 100))
    if allowed is not None:
        request['allowed'] = allowed
    if builder is not None:
        request['builder'] = dict(x=builder[0], r=builder[1])
    try:
        result = native.ask(request)
    except ValueError:
        return None
    choice = result['choice']
    points = choice['link_points']
    return dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0], reason=KINDS[kind(choice)],
        decision_kind=kind(choice), fire=bool(points), chain=choice['chain'], next_chain=choice['chain'],
        next_score=sum(points), link_points=points,
        next_field=choice['field'] if choice['post_drop_field_known'] else None,
        next_all_clear=choice['all_clear'], selected_move_loses=not choice['survives'],
        decision_dependencies=['self', 'enemy'] if enemy_events else ['self'],
        searched_visible=result['completed_depth'] or 1, tactics_forecast=result)
