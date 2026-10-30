"""Shared absolute deadline for transient pressure, including early replies.

Pressure surviving a next-seed return has no turnover deadline.
No score/chain search runs here.
"""


def coming(request):
    """What is on its way back at us: attacks in flight, their counter objects, and what already waits."""
    side = request['self']
    flights = request.get('observation', {}).get('in_flight', {})
    return (flights.get('self', {}).get('incoming_in_flight', 0)
            + sum(f['amount'] for f in flights.get('enemy', {}).get('attacks_in_flight', []) if f.get('counter') and f.get('amount'))
            + side['confirmed'] + side['unconfirmed'])


def contract(request, reply, target):
    enemy = request['enemy']
    if reply.get('reason') == 'normal_lethal_followup':
        return dict(kind='buried_followup', enemy_generation=enemy['mode_generation'],
            enemy_field=enemy['field'], gauge_limit=reply['followup_forecast']['gauge_limit'],
            need=reply['followup_forecast']['need'])
    if reply.get('reason') == 'normal_capacity_conversion':
        forecast = reply['capacity_conversion']
        context = forecast['enemy_context']
        if context['kind'] == 'normal_opening':
            return dict(kind='conversion_opening', first_main_chain=context['first_main_chain'])
        if context['kind'] == 'fever_extending':
            return dict(kind='extension_pressure', enemy_generation=enemy['mode_generation'],
                enemy_seed=enemy['seed_id'], enemy_level=enemy['seed_chain'],
                duration=forecast['attack_end'], conversion=True)
        return dict(kind='jab', target_frame=request['frame']+context['their_end'],
            deadline_frame=request['frame']+context['their_end']+context['window'],
            duration=forecast['attack_end'], enemy_generation=enemy['mode_generation'],
            enemy_seed=enemy['seed_id'], entering=False, next_seed=True)
    if reply.get('entry_fire'):
        shot = reply['entry_fire']
        return dict(kind='entry', enemy_generation=enemy['mode_generation'], enemy_seed=enemy['seed_id'],
            first_link_frame=request['frame'] + shot['first_link'], end_frame=request['frame'] + shot['end'],
            coming=coming(request),
            deadline_frame=request['frame'] + shot['latest_end'] if shot['kind'] == 'jab' else None)
    if reply.get('reason') == 'normal_final_seed_fire':
        shot = reply['final_seed_fire']
        return dict(kind='jab', target_frame=request['frame'] + shot['earliest_end'],
            deadline_frame=request['frame'] + shot['latest_end'], duration=shot['end'],
            enemy_generation=enemy['mode_generation'], enemy_seed=enemy['seed_id'],
            entering=False, next_seed=True)
    # An offset or all-clear has its own reason to fire. Expiring an incidental
    # jab reward must not cancel such a placement and restart steering.
    forecast = reply.get('tactics_forecast') or reply.get('seed_forecast') or {}
    choice = forecast.get('choice', {})
    if reply.get('tactics_forecast') and (choice.get('defensive_fire') or reply.get('reason') in
            ('tactics_offset', 'tactics_all_clear')):
        return None
    if choice.get('disruption_kind') == 'extension_pressure' and reply.get('fire'):
        enemy=request['enemy']
        return dict(kind='extension_pressure',enemy_generation=enemy['mode_generation'],
                    enemy_seed=enemy['seed_id'],enemy_level=enemy['seed_chain'])
    timed_return = choice.get('disruption_requires_timing', False)
    if not (choice.get('disruption_kind') == 'jab' or timed_return) or not reply.get('fire'):
        return None
    end = target.get('their_end')
    if end is None:
        return None
    enemy = request['enemy']
    entering = enemy['mode'] == 'normal'
    current_attack = timed_return and choice.get('disruption_kind') != 'jab'
    return dict(kind='current_attack' if current_attack else 'jab',
                target_frame=request['frame'] if current_attack else request['frame'] + end,
                deadline_frame=request['frame'] + end + target.get('disrupt_window', 26),
                duration=choice.get('attack_end', choice.get('end_at', 0)),
                enemy_generation=enemy['mode_generation'], enemy_seed=enemy['seed_id'],
                entering=entering, next_seed=bool(request.get('enemy_chain')))


def valid(reply, latest):
    guard = reply.get('disruption_timing')
    if not guard:
        return True
    enemy = latest['enemy']
    if guard['kind'] == 'entry':
        # Still entering from the same normal board, and the entry no later than the first link planned for it.
        known = enemy.get('fever_destination_frame')
        if coming(latest) > guard['coming']:
            return False        # something came back at us since: the piece is not held for a jab any more
        return (enemy['mode_generation'] in (guard['enemy_generation'], guard['enemy_generation'] + 1)
                and (known is None or guard['first_link_frame'] >= known)
                and (guard['deadline_frame'] is None or guard['end_frame'] <= guard['deadline_frame']))
    if guard['kind'] == 'buried_followup':
        return (enemy['mode'] == 'normal' and enemy['mode_generation'] == guard['enemy_generation']
                and enemy['field'] == guard['enemy_field'] and enemy['gauge'] <= guard['gauge_limit']
                and enemy['confirmed'] + enemy['unconfirmed'] < guard['need']
                and enemy.get('phase') in ('controllable', 'placing') and not latest.get('enemy_chain'))
    if guard['kind'] == 'conversion_opening':
        main = enemy.get('normal_chain_max')
        return (enemy['mode'] == 'normal' and enemy['mode_generation'] == 0 and enemy['gauge'] < 7
                and type(main) is int and main < guard['first_main_chain'] and not latest.get('enemy_chain')
                and enemy.get('phase') != 'chain')
    if guard['kind']=='extension_pressure':
        return (enemy['mode']=='fever' and enemy['mode_generation']==guard['enemy_generation']
                and enemy['seed_id']==guard['enemy_seed'] and enemy['seed_chain']==guard['enemy_level']
                and enemy.get('phase')!='chain' and not latest.get('enemy_chain')
                and (not guard.get('conversion') or
                     (enemy.get('phase') in ('controllable','placing') and not enemy.get('awaiting_seed')
                      and enemy['remaining_frames'] > 0
                      and any(c not in '.#' for row in enemy['field'] for c in row)))
                and (not guard.get('duration') or (not enemy['clock_running'] or
                     enemy['remaining_frames'] > guard['duration'])))
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
