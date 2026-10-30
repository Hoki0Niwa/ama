"""Normal board under threat, decided by the worker's single search (op tactics).

Stacking until a drop is due, the smallest offset, firing the main chain and
taking a drop are placements of one search with one value; see
fever_battle/tactics.cpp. The weights are prototype values of
data/fever/battle_policy.json, not tuned in battle.
"""
from dataclasses import dataclass
from .timing import ChainTiming
from .nuisance import Trays
from .strategy import opening_all_clear_possible, profile as strategy_profile

# Replies of the search when nothing threatens (quiet): 'tactics_all_clear' clears the board within the
# visible pieces, 'tactics_disrupt' sends a small packet at an opponent in Fever, 'tactics_fire' and
# 'tactics_harass' send where what lands can kill.
KINDS = {
    'stack': 'tactics_stack',            # pops nothing, nothing falls on this placement
    'take': 'tactics_take_drop',         # pops nothing and takes the drop
    'offset': 'tactics_offset',          # pops and offsets pending nuisance
    'clear': 'tactics_clear',            # pops without offsetting anything
}


def popped(choice):
    return sum(sum(link['groups']) for link in choice['links'])


def least_entry(result):
    """The choice, or when it enters Fever the entering candidate that pops the fewest puyos.

    The board goes into storage with the entry and is what the next entry is built on: of the moves that surely
    enter and survive, the one that spends the least of it is played, however the values of the search rank the
    rest (a 2-chain of 10 puyos was played where one four-puyo link entered, 2026-10-25). It costs no search:
    the candidates are already evaluated. A choice that does not enter Fever is left alone."""
    choice = result['choice']
    if not choice.get('enters_fever') or choice.get('all_clear'):
        return choice               # clearing the board whole earns a seed of its own (2026-10-08): not a waste
    entering = [c for c in result.get('candidates', []) if c.get('enters_fever') and c['survives']
                and c.get('current_survives', c['survives'])]
    best = min(entering, key=lambda c: (popped(c), -c['value']), default=choice)
    return best if popped(best) < popped(choice) else choice


def ready_main(result, builder, builder_fire):
    """Keep the builder's ready main when it safely covers the known exchange.

    Resource-saving Fever entry is for an unfavorable exchange, not a reason to
    discard the main/second that construction has already chosen to fire.
    """
    if builder is None or not builder_fire:
        return None
    return next((c for c in result.get('candidates', [])
        if (c['x'],c['r']) == tuple(builder) and c.get('attack_kind') == 'main'
        and c.get('survives') and c.get('current_survives')
        and c.get('projected_sufficient_return') and c.get('current_defense_commitment')
        and c.get('current_exchange_pending') == 0), None)


def kind(choice):
    if choice['chain']:
        return 'offset' if choice['cancelled'] else 'clear'
    return 'take' if choice['dropped'] else 'stack'


@dataclass
class Decision:
    status: str                         # build, defense, unresolved, unavailable
    reply: dict | None = None
    forecast: dict | None = None


def evaluate(native, scoring, own, rate, gain, policy, enemy_events=None, enemy=None, margin=None,
           allowed=None, builder=None, defense=None, upcoming='', harass=False, pace=None, quiet=False, fever=None, enemy_hold=None,
           invite_fever=False, avoid_own_fever=False, builder_fire=False):
    """Keep a builder decision distinct from an unavailable tactical search."""
    opponent, margin = enemy or {}, margin or {}
    # Generic normal harassment must not bypass the Fever turnover window.
    if fever and fever.get('enemy_fever'):
        harass = False
    request = dict(op='tactics', field=own['field'],
        queue=own['queue'][:1] if policy.get('opening_all_clear_immediate') else own['queue'],
        confirmed=own['confirmed'], unconfirmed=own['unconfirmed'], remainder=own['remainder'],
        garbage_phase=own['garbage_phase'] or 0, unknown_garbage_phase=own['garbage_phase'] is None,
        gauge=own['gauge'], gain=gain, target_point=rate,
        opening_piece=own['piece_id'],
        opening_all_clear=policy.get('opening_all_clear',True) and opening_all_clear_possible(own),
        rate_events=margin.get('rate_events', []), enemy_rate_events=margin.get('enemy_rate_events', []),
        enemy_events=enemy_events or [],
        **Trays(opponent).native(),
        enemy_remainder=opponent.get('remainder', 0), upcoming=upcoming, harass=harass, quiet=quiet, finish_buried=bool(policy.get('finish_buried',False)),
        invite_fever=invite_fever, avoid_own_fever=avoid_own_fever, **(fever or {}),
        **({} if enemy_hold is None else dict(enemy_hold=enemy_hold)),
        **({} if defense is None else dict(enemy_defense=defense)), **({} if pace is None else dict(pace_frames=pace)),
        timing=ChainTiming().native(), powers=scoring.data['characters'][own['character']]['normal'],
        bonuses=scoring.data['bonuses'], weights=policy['weights'],
        width=policy.get('width', 12), max_nodes=policy.get('max_nodes', 1500),
        budget_ms=policy.get('budget_ms', 100), margin=policy.get('margin', 1),
        main_trigger_points=policy.get('main_trigger_points',
            40 * sum(max(1, p) for p in scoring.data['characters'][own['character']]['normal'][:14])))
    new_attack = policy.get('pressure', {}).get('enabled', False) or policy.get('finish', {}).get('enabled', False)
    if new_attack:
        # Replace the older invite/buried-opponent bonuses so they cannot bypass the new gates.
        request.update(harass=False, finish_buried=False)
        harass = False
        request['normal_pressure'] = {k: policy[k] for k in ('pressure', 'finish', 'counter_read')}
        rows = opponent['field']
        request['normal_pressure_enemy'] = dict(
            available=opponent.get('mode') == 'normal' and opponent.get('phase') in (('controllable', 'placing') if policy.get('pressure',{}).get('send_weight',0)>0 else ('controllable',))
                and not enemy_events and not (fever and fever.get('enemy_fever')),
            mode=opponent['mode'], field=rows, queue=opponent['queue'],
            powers=scoring.data['characters'][opponent['character']]['normal'],
            gauge=opponent['gauge'], gain=gain, remainder=opponent['remainder'],
            pending=opponent['confirmed'] + opponent['unconfirmed'],
            experienced=opponent.get('mode_generation', 0) > 0,
            seed_chain=opponent.get('seed_chain', 19),
            third_height=sum(row[2] != '.' for row in rows))
    if allowed is not None:
        request['allowed'] = allowed
    if builder is not None:
        request['builder'] = dict(x=builder[0], r=builder[1], fire=builder_fire)
    try:
        result = native.ask(request)
    except ValueError as error:
        if str(error) not in ('no conservative legal placement', 'already dead field'):
            raise
        return Decision('unavailable')
    pressure_style=strategy_profile({'normal_tactics':{'strategy':policy.get('strategy','mainline')}})['pressure_style']
    main = ready_main(result,builder,builder_fire) if pressure_style else None
    result['choice'] = choice = main or least_entry(result)
    reason = KINDS[kind(choice)]
    if quiet:
        # Nothing threatens: the builder places this piece unless the search sends something
        # (a clear beside the main chain, or the chain itself where it kills), or turns the
        # builder's own small clear into an attack within the visible pieces.
        whole = choice.get('attack_kind') == 'main'
        disrupt = choice['projected_sent'] > 0 and choice['projected_disrupt'] >= 0.5
        useful_harass = harass and choice.get('projected_harass', False)
        attack = choice.get('projected_normal_attack', {})
        pressure = attack.get('pressure', False)
        finish = attack.get('finish', False)
        if builder is not None and (choice['x'], choice['r']) == tuple(builder) and not (
                disrupt or pressure or finish or choice['projected_all_clear']):
            return Decision('build', forecast=result)
        if result.get('held_main_for_counter'):
            reason = 'tactics_hold_for_fever_counter'
        elif finish:
            reason = 'tactics_finish' if choice['chain'] else 'tactics_prepare_finish'
        elif pressure:
            reason = 'tactics_pressure'
        elif choice['projected_all_clear']:
            reason = 'tactics_all_clear'
        elif disrupt:
            reason = 'tactics_disrupt'
        elif choice['chain'] and choice['sent'] and useful_harass:
            reason = 'tactics_fire' if whole else 'tactics_harass'
        elif useful_harass and not choice['chain'] and choice['projected_sent'] > 0:
            reason = 'tactics_harass'      # the placement that sets the attack up
        else:
            return Decision('build', forecast=result)
    elif choice.get('projected_normal_attack', {}).get('pressure', False):
        reason = 'tactics_pressure'
    points = choice['link_points']
    reply = dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0], reason=reason,
        decision_kind=kind(choice), fire=bool(points), chain=choice['chain'], next_chain=choice['chain'],
        next_score=sum(points), link_points=points,
        next_field=choice['field'] if choice['post_drop_field_known'] else None,
        next_all_clear=choice['all_clear'], selected_move_loses=not choice.get('current_survives', choice['survives']),
        decision_dependencies=['self', 'enemy'] if enemy_events or quiet or new_attack else ['self'],
        searched_visible=result['completed_depth'] or 1, tactics_forecast=result)
    status = 'defense' if choice['survives'] and choice['defense_commitment'] else 'unresolved'
    reply['normal_decision_status'] = status
    return Decision(status, reply, result)


def choose(*args, **kwargs):
    """Compatibility API for callers interested only in tactical overrides."""
    return evaluate(*args, **kwargs).reply
