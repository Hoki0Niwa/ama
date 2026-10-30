"""Cheap request-local strategy selection; never launches a search."""
from copy import deepcopy
from collections import Counter

BASE_PROFILE = dict(pressure_style=False, min_remaining=16,
                    tactical_nodes=None, tactical_width=None, window_build=True)
PROFILES = {
    'mainline': {},
    'brawl': dict(pressure_style=True,min_remaining=12,tactical_nodes=512,tactical_width=6,window_build=False),
    'hybrid': dict(pressure_style=True,tactical_nodes=512,tactical_width=6,window_build=False),
}
NAMES = tuple(PROFILES)


def profile(request):
    """New strategies inherit the complete common baseline; only differences belong here."""
    return {**BASE_PROFILE, **PROFILES[name(request)]}


def opening_all_clear_possible(own):
    """Cheap necessary color test for the shared, visible opening objective.

    The actual placements and safety are still decided by the existing tactics
    search. Big puyos can change color, so each is a flexible four-cell group.
    """
    if (own.get('mode')!='normal' or own.get('mode_generation',0)!=0
            or (own.get('normal_chain_max') or 0)>=4 or not 0<=own.get('piece_id',8)<8):
        return False
    counts=Counter(c for row in own['field'] for c in row if c not in '.#')
    total=sum(c!='.' for row in own['field'] for c in row)
    flexible=0
    for step,text in enumerate(own['queue'][:3],1):
        if own['piece_id']+step>8:
            break
        if text.startswith('0:'):
            total+=4;flexible+=1
        else:
            colors=text.split(':',1)[1]
            total+=len(colors);counts.update(colors)
        if total>16:
            break
        if sum(0<n<4 for n in counts.values())<=flexible:
            return True
    return False


def name(request):
    value = request.get('normal_tactics', {}).get('strategy', 'mainline')
    if not isinstance(value, str) or value not in PROFILES:
        raise ValueError('normal_tactics.strategy must be one of '+', '.join(PROFILES))
    return value


def margin_pressure(request):
    """Whether an ordinary four-puyo single already sends at least one row."""
    rate=request.get('target_point',120)
    if type(rate) is not int or rate<=0:
        return False
    own=request.get('self',{})
    powers=own.get('powers') or {}
    normal=powers.get('normal',[]) if isinstance(powers,dict) else []
    power=max(1,min(999,normal[0])) if normal else 1
    return (40*power+own.get('remainder',0))//rate>=6


def uses_pressure(request):
    return profile(request)['pressure_style'] or (bool(request.get('_preparing_strategy')) and margin_pressure(request))


def pressure_context(request, own=None, enemy=None):
    own=own or request.get('self',{})
    enemy=enemy or request.get('enemy',{})
    if own.get('mode')!='normal' or enemy.get('mode')!='normal' or request.get('enemy_chain'):
        return False
    if enemy.get('phase')=='chain' or own.get('gauge',0)>=7 or enemy.get('gauge',0)>=7:
        return False
    for side in (own,enemy):
        if any(side.get(k,0) for k in ('confirmed','unconfirmed','normal_confirmed',
            'normal_unconfirmed','fever_confirmed','fever_unconfirmed')):
            return False
    flights=request.get('observation',{}).get('in_flight',{})
    for side in flights.values():
        if any(side.get(k,0) for k in ('incoming_in_flight','outgoing_in_flight','counter_in_flight')):
            return False
        if any(f.get('amount',0)>0 for f in side.get('attacks_in_flight',[])):
            return False
    return True


def controls(request, own, enemy):
    asked = deepcopy(request.get('normal_tactics', {}))
    selected = profile(request)
    pressure_style=selected['pressure_style']
    if not uses_pressure(request):
        return asked
    # One bounded reply tree in the existing tactical search, never a second search.
    defaults = dict(harass=False, invite_fever=True,
        avoid_own_fever=False, counter_read=dict(depth=1, max_nodes=96),
        pressure=dict(enabled=pressure_context(request,own,enemy), max_chain=4 if pressure_style else 1,
            min_send=6 if margin_pressure(request) else 12, max_send=1000000,
            min_remaining=selected['min_remaining'],
            min_heights=[0]*6, max_main_loss=1 if pressure_style else 0,
            protect_main_chain=0, min_remaining_chain=5 if pressure_style else 0,
            chain_reserve_step=8 if pressure_style else 0,
            weight=800, gauge_weight=6, gauge_gain_weight=4, send_weight=1,
            time_scale=1000 if pressure_style else 0,
            block_seed_chain=19, max_attacks=0, fever_pressure=False),
        window_build=dict(enabled=False))
    if pressure_style and not pressure_context(request,own,enemy):
        defaults['weights']=dict(disrupt=0,harass=0)
    if not pressure_style:
        defaults.pop('avoid_own_fever')
        defaults.pop('window_build')
    for key, value in defaults.items():
        if isinstance(value, dict):
            asked[key] = {**value, **asked.get(key, {})}
        else:
            asked.setdefault(key, value)
    if pressure_style and not pressure_context(request,own,enemy):
        asked['pressure']['enabled']=False
        asked['pressure']['fever_pressure']=False
    return asked


def phase(request, own, enemy):
    pressure_style = profile(request)['pressure_style']
    if own['mode'] == 'fever':
        return 'seed'
    incoming = own['confirmed'] + own['unconfirmed'] > 0 or bool(request.get('enemy_chain'))
    if pressure_style and not pressure_context(request,own,enemy):
        return 'counter_main' if request.get('enemy_chain') or enemy['mode']=='fever' else 'defense'
    return 'pressure' if pressure_style else 'mainline'
