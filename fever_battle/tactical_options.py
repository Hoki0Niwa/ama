"""Request-local protocol-3 tactical controls; never mutate the shared policy."""
from copy import deepcopy
from .model import integer
from . import normal_pressure_options, strategy

WEIGHTS = {
    name: (0, 1000000) for name in (
        'entry', 'gauge', 'stock', 'color', 'drop', 'consume', 'mainline',
        'height', 'early', 'builder', 'step', 'exposed', 'pending',
        'uncountered', 'fever_reach', 'harass', 'all_clear', 'disrupt', 'entry_consume')
}
WEIGHTS.update(mainline_min=(1, 19), arrival_pieces=(0, 100))
LIMITS = dict(harass_min_count=(0, 84), harass_max_count=(0, 85),
              harass_min_height=(0, 14), harass_columns=(1, 6))
WINDOW = dict(hold=(1, 19), min_pieces=(1, 100), fire_pieces=(0, 100), beam_width=(1, 10000))


def object_keys(value, allowed, name):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'{name} must be an object with known keys')


def validate(request):
    value = request.get('normal_tactics', {})
    if not isinstance(value, dict):
        raise ValueError('normal_tactics must be an object')
    strategy.name(request)
    object_keys(value, {'strategy', 'invite_fever', 'avoid_own_fever', 'harass', 'weights', 'window_build', 'final_seed_fire', 'entry_fire', 'gauge_wait', *normal_pressure_options.DEFAULTS} | LIMITS.keys(), 'normal_tactics')
    normal_pressure_options.validate(value)
    for key in ('invite_fever', 'avoid_own_fever', 'harass', 'final_seed_fire', 'entry_fire', 'gauge_wait'):
        if key in value and type(value[key]) is not bool:
            raise ValueError(f'normal_tactics.{key} must be a boolean')
    for key, bounds in LIMITS.items():
        if key in value:
            integer(value[key], f'normal_tactics.{key}', *bounds)
    if value.get('harass_min_count', 24) > value.get('harass_max_count', 52):
        raise ValueError('normal_tactics.harass_min_count must be <= harass_max_count')
    for section, limits in (('weights', WEIGHTS), ('window_build', WINDOW)):
        if section not in value:
            continue
        cfg = value[section]
        object_keys(cfg, set(limits) | ({'enabled'} if section == 'window_build' else set()), f'normal_tactics.{section}')
        for key, item in cfg.items():
            if key == 'enabled':
                if type(item) is not bool:
                    raise ValueError('normal_tactics.window_build.enabled must be a boolean')
            else:
                integer(item, f'normal_tactics.{section}.{key}', *limits[key])


def resolve(policy, request, own, enemy):
    validate(request)
    overrides = strategy.controls(request, own, enemy)
    effective = deepcopy(policy)
    first = own['mode'] == enemy['mode'] == 'normal' and own['mode_generation'] == enemy['mode_generation'] == 0
    effective.update(invite_fever=first, avoid_own_fever=first, harass=True,
                     harass_min_count=24, harass_max_count=52, harass_min_height=4, harass_columns=3)
    effective.update({k: v for k, v in overrides.items() if k not in ('weights', 'window_build', 'final_seed_fire', 'entry_fire', 'gauge_wait', *normal_pressure_options.DEFAULTS)})
    scale=policy.get('opening_all_clear_scale',{}).get(strategy.name(request),100)
    effective['weights']['all_clear']=min(1000000,effective['weights'].get('all_clear',5000)*scale//100)
    effective['weights'].update(overrides.get('weights', {}))
    effective['window_build'] = resolve_window(policy, dict(request, normal_tactics=overrides))
    effective.update(normal_pressure_options.resolve(overrides))
    effective['opening_all_clear']=strategy.opening_all_clear_possible(own) and effective['weights']['all_clear']>0
    if effective['opening_all_clear']:
        # Use the shared opening frontier, comparing all-clears independently
        # of pressure's remaining-main gates. Keep explicit attacks available.
        effective['harass']=False
        # A pressure shot clears at least four cells. Do not build an opponent
        # reply tree when even all visible pieces cannot leave the required stock.
        pressure=effective['pressure']
        colors=sum(c not in '.#' for row in own['field'] for c in row)
        colors+=sum(4 if q.startswith('0:') else len(q.split(':',1)[1]) for q in own['queue'][:3])
        reserve=max(pressure['min_remaining'],4*pressure['min_remaining_chain']-2)
        if colors<reserve+4:
            pressure['enabled']=False
    else:
        selected=strategy.profile(request)
        if selected['tactical_nodes'] is not None:
            effective['max_nodes'] = min(effective.get('max_nodes', 3000),selected['tactical_nodes'])
        if selected['tactical_width'] is not None:
            effective['width'] = min(effective.get('width', 12),selected['tactical_width'])
    if strategy.profile(request)['pressure_style']:
        effective['counter_read']['max_nodes'] = min(effective['counter_read']['max_nodes'], 96)
        effective['counter_read']['depth'] = 1
    return effective


def resolve_window(policy, request):
    window = policy.get('window_build') or {}
    effective = dict(hold=10, min_pieces=3, fire_pieces=0, beam_width=30, enabled=bool(window))
    effective.update(window)
    if not strategy.profile(request)['window_build']:
        effective['enabled'] = False
    effective.update(request.get('normal_tactics', {}).get('window_build', {}))
    return effective


def harass_enabled(policy, own, enemy, quiet, second, finish, fever):
    count = sum(c != '.' for row in own['field'] for c in row)
    heights = [sum(row[x] != '.' for row in own['field']) for x in range(policy['harass_columns'])]
    eligible = (quiet and fever is None and policy['weights'].get('harass', 0) > 0
                and policy['harass_min_count'] <= count < policy['harass_max_count']
                and all(h >= policy['harass_min_height'] for h in heights))
    return bool(policy['harass'] and enemy['mode'] != 'fever' and (quiet and second and finish or eligible))


def report(policy, reply, evaluated):
    choice = reply.get('tactics_forecast', {}).get('choice', {})
    effective = {k: deepcopy(policy[k]) for k in (
        'invite_fever', 'avoid_own_fever', 'harass', *LIMITS, 'window_build', *normal_pressure_options.DEFAULTS)}
    effective['weights'] = {k: policy['weights'][k] for k in WEIGHTS if k in policy['weights']}
    return dict(selected=reply['reason'], evaluated_switches=evaluated,
                disruption_kind=choice.get('disruption_kind', 'none'), effective=effective,
                normal_attack=deepcopy(choice.get('normal_attack') if choice.get('chain')
                    else choice.get('projected_normal_attack')))


def has_overrides(request):
    value = request.get("normal_tactics", {})
    return bool({k: v for k, v in value.items() if k != "strategy"} or strategy.uses_pressure(request))


def common_quiet_objectives(policy, request, own, fever):
    """Shared goals are independent of how many strategy profiles exist."""
    asked=request.get('normal_tactics',{})
    return bool(policy.get('opening_all_clear') or fever is not None
        or (policy.get('harass') and sum(c!='.' for r in own['field'] for c in r)>=policy.get('harass_min_count',24))
        or set(asked).intersection(('weights','invite_fever','avoid_own_fever','harass')))
