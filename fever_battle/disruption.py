"""Shared absolute deadline for a timed jab, including early bridge replies.

Firepower attacks have no turnover deadline. No score/chain search runs here.
"""


def contract(request, reply, target):
    # An offset or all-clear has its own reason to fire. Expiring an incidental
    # jab reward must not cancel such a placement and restart steering.
    if reply.get('tactics_forecast') and reply.get('reason') != 'tactics_disrupt':
        return None
    forecast = reply.get('tactics_forecast') or reply.get('seed_forecast') or {}
    choice = forecast.get('choice', {})
    if choice.get('disruption_kind') == 'extension_pressure' and reply.get('fire'):
        enemy=request['enemy']
        return dict(kind='extension_pressure',enemy_generation=enemy['mode_generation'],
                    enemy_seed=enemy['seed_id'],enemy_level=enemy['seed_chain'])
    if choice.get('disruption_kind') != 'jab' or not reply.get('fire'):
        return None
    end = target.get('their_end')
    if end is None:
        return None
    enemy = request['enemy']
    entering = enemy['mode'] == 'normal'
    return dict(kind='jab', target_frame=request['frame'] + end,
                deadline_frame=request['frame'] + end + target.get('disrupt_window', 26),
                duration=choice.get('attack_end', choice.get('end_at', 0)),
                enemy_generation=enemy['mode_generation'], enemy_seed=enemy['seed_id'],
                entering=entering, next_seed=bool(request.get('enemy_chain')))


def valid(reply, latest):
    guard = reply.get('disruption_timing')
    if not guard:
        return True
    enemy = latest['enemy']
    if guard['kind']=='extension_pressure':
        return (enemy['mode']=='fever' and enemy['mode_generation']==guard['enemy_generation']
                and enemy['seed_id']==guard['enemy_seed'] and enemy['seed_chain']==guard['enemy_level']
                and enemy.get('phase')!='chain' and not latest.get('enemy_chain'))
    generation = guard['enemy_generation']
    if guard['entering']:
        if enemy['mode_generation'] not in (generation, generation + 1):
            return False
    elif enemy['mode'] != 'fever' or enemy['mode_generation'] != generation:
        return False
    if enemy['seed_id'] not in (guard['enemy_seed'], guard['enemy_seed'] + int(guard['next_seed'] or guard['entering'])):
        return False
    finish = latest['frame'] + guard['duration']
    return guard['target_frame'] <= finish <= guard['deadline_frame']
