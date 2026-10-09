"""Normal board under threat, decided by the worker's single search (op tactics).

Stacking until a drop is due, the smallest offset, firing the main chain and
taking a drop are placements of one search with one value; see
fever_battle/tactics.cpp. The weights are prototype values of
data/fever/battle_policy.json, not tuned in battle.
"""
from .timing import ChainTiming
from .nuisance import Trays

# Replies of the search when nothing threatens (quiet): 'tactics_all_clear' clears the board within the
# visible pieces, 'tactics_disrupt' sends a small packet at an opponent in Fever, 'tactics_fire' and
# 'tactics_harass' send where what lands can kill.
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
           allowed=None, builder=None, defense=None, upcoming='', harass=False, pace=None, quiet=False, fever=None, enemy_hold=None,
           invite_fever=False, avoid_own_fever=False, builder_fire=False):
    """The reply for this piece, or None when no placement can be played at all."""
    opponent, margin = enemy or {}, margin or {}
    # Generic normal harassment must not bypass the Fever turnover window.
    if fever and fever.get('enemy_fever'):
        harass = False
    request = dict(op='tactics', field=own['field'], queue=own['queue'],
        confirmed=own['confirmed'], unconfirmed=own['unconfirmed'], remainder=own['remainder'],
        garbage_phase=own['garbage_phase'] or 0, unknown_garbage_phase=own['garbage_phase'] is None,
        gauge=own['gauge'], gain=gain, target_point=rate,
        rate_events=margin.get('rate_events', []), enemy_rate_events=margin.get('enemy_rate_events', []),
        enemy_events=enemy_events or [],
        **Trays(opponent).native(),
        enemy_remainder=opponent.get('remainder', 0), upcoming=upcoming, harass=harass, quiet=quiet,
        invite_fever=invite_fever, avoid_own_fever=avoid_own_fever, **(fever or {}),
        **({} if enemy_hold is None else dict(enemy_hold=enemy_hold)),
        **({} if defense is None else dict(enemy_defense=defense)), **({} if pace is None else dict(pace_frames=pace)),
        timing=ChainTiming().native(), powers=scoring.data['characters'][own['character']]['normal'],
        bonuses=scoring.data['bonuses'], weights=policy['weights'],
        width=policy.get('width', 12), max_nodes=policy.get('max_nodes', 1500),
        budget_ms=policy.get('budget_ms', 100), margin=policy.get('margin', 1),
        main_trigger_points=policy.get('main_trigger_points', 85000))
    if allowed is not None:
        request['allowed'] = allowed
    if builder is not None:
        request['builder'] = dict(x=builder[0], r=builder[1], fire=builder_fire)
    try:
        result = native.ask(request)
    except ValueError:
        return None
    choice = result['choice']
    reason = KINDS[kind(choice)]
    if quiet:
        # Nothing threatens: the builder places this piece unless the search sends something
        # (a clear beside the main chain, or the chain itself where it kills), or turns the
        # builder's own small clear into an attack within the visible pieces.
        whole = choice.get('attack_kind') == 'main'
        disrupt = choice['projected_sent'] > 0 and choice['projected_disrupt'] >= 0.5
        useful_harass = harass and choice.get('projected_harass', False)
        if builder is not None and (choice['x'], choice['r']) == tuple(builder) and not disrupt:
            return None
        if result.get('held_main_for_counter'):
            reason = 'tactics_hold_for_fever_counter'
        elif choice['projected_all_clear']:
            reason = 'tactics_all_clear'
        elif disrupt:
            reason = 'tactics_disrupt'
        elif choice['chain'] and choice['sent'] and useful_harass:
            reason = 'tactics_fire' if whole else 'tactics_harass'
        elif useful_harass and not choice['chain'] and choice['projected_sent'] > 0:
            reason = 'tactics_harass'      # the placement that sets the attack up
        else:
            return None
    points = choice['link_points']
    return dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0], reason=reason,
        decision_kind=kind(choice), fire=bool(points), chain=choice['chain'], next_chain=choice['chain'],
        next_score=sum(points), link_points=points,
        next_field=choice['field'] if choice['post_drop_field_known'] else None,
        next_all_clear=choice['all_clear'], selected_move_loses=not choice['survives'],
        decision_dependencies=['self', 'enemy'] if enemy_events or quiet else ['self'],
        searched_visible=result['completed_depth'] or 1, tactics_forecast=result)
