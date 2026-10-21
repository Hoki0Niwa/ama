"""Request-local protocol-3 tactical controls; never mutate the shared policy."""
from copy import deepcopy
from .model import integer

WEIGHTS = {
    name: (0, 1000000) for name in (
        'entry', 'gauge', 'stock', 'color', 'drop', 'consume', 'mainline',
        'height', 'early', 'builder', 'step', 'exposed', 'pending',
        'uncountered', 'fever_reach', 'harass', 'all_clear', 'disrupt')
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
    object_keys(value, {'invite_fever', 'avoid_own_fever', 'harass', 'weights', 'window_build'} | LIMITS.keys(), 'normal_tactics')
    for key in ('invite_fever', 'avoid_own_fever', 'harass'):
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
    overrides = request.get('normal_tactics', {})
    effective = deepcopy(policy)
    first = own['mode'] == enemy['mode'] == 'normal' and own['mode_generation'] == enemy['mode_generation'] == 0
    effective.update(invite_fever=first, avoid_own_fever=first, harass=True,
                     harass_min_count=24, harass_max_count=52, harass_min_height=4, harass_columns=3)
    effective.update({k: v for k, v in overrides.items() if k not in ('weights', 'window_build')})
    effective['weights'].update(overrides.get('weights', {}))
    effective['window_build'] = resolve_window(policy, request)
    return effective


def resolve_window(policy, request):
    window = policy.get('window_build') or {}
    effective = dict(hold=10, min_pieces=3, fire_pieces=0, beam_width=30, enabled=bool(window))
    effective.update(window)
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
        'invite_fever', 'avoid_own_fever', 'harass', *LIMITS, 'window_build')}
    effective['weights'] = {k: policy['weights'][k] for k in WEIGHTS if k in policy['weights']}
    return dict(selected=reply['reason'], evaluated_switches=evaluated,
                disruption_kind=choice.get('disruption_kind', 'none'), effective=effective)
