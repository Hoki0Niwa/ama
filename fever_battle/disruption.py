"""Shared absolute deadline for transient pressure, including early replies.

Pressure surviving a next-seed return has no turnover deadline.
No score/chain search runs here.
"""
from .chain_to_us import LAUNCH_FRAMES
from .timing import ChainTiming, fever_turnover_check_delay


def coming(request):
    """What is on its way back at us: attacks in flight, their counter objects, and what already waits."""
    side = request['self']
    flights = request.get('observation', {}).get('in_flight', {})
    return (flights.get('self', {}).get('incoming_in_flight', 0)
            + sum(f['amount'] for f in flights.get('enemy', {}).get('attacks_in_flight', []) if f.get('counter') and f.get('amount'))
            + side['confirmed'] + side['unconfirmed'])


def score_rebuild_safe(request, own):
    enemy = request.get('enemy', {})
    flights = request.get('observation', {}).get('in_flight', {}).get('self', {})
    return ((own.get('moves_since_chain') or 0) >= 12 and enemy.get('mode') == 'normal'
            and enemy.get('phase') in ('controllable', 'placing') and not request.get('enemy_chain')
            and not own.get('confirmed') and not own.get('unconfirmed')
            and not flights.get('incoming_in_flight') and not flights.get('counter_in_flight')
            and sum(cell in 'RYGB' for row in enemy.get('field', ()) for cell in row) < 52)


def jab_hold(request, reply, placement, their_end, level, margin, fall_config):
    """Time the last link so it survives the opponent's running chain."""
    timing = ChainTiming.for_mode('normal')
    split = timing.split_extra_frames[max(placement['split_distances'], default=0)]
    points = reply['link_points']
    trajectory = timing.timeline(points, placement['fall_distances'], placement.get('fall_features'),
                                 start_offset=split + timing.first_link_frames)
    last_launch = trajectory['links'][-1]['score_at_min'] + LAUNCH_FRAMES['normal']
    frame = request['frame']
    target = their_end + margin
    hold_until = target - last_launch
    check_delay = fever_turnover_check_delay(level)
    deadline = their_end + check_delay
    rows = max(0, fall_config['spawn_height'] - placement['contact_height'])
    # Steering can happen during the hold. Budget a full soft drop from spawn on release.
    duration = trajectory['end_frame_max'] + 2 * rows + fall_config['fast_lock_frames']
    room = int(rows * fall_config['fall_frames_per_row'] + fall_config['lock_limit_frames']
               - fall_config['safety_frames'])
    if not (0 < hold_until - frame <= room and hold_until + duration < deadline):
        return None
    return dict(hold_frames=hold_until - frame, hold_down_until_frame=hold_until,
                jab_hold=dict(enemy_end_frame=their_end, target_launch_frame=target,
                              end_frame=hold_until + duration, deadline_frame=deadline,
                              check_delay=check_delay, duration=duration,
                              late_nuisance=points[-1] // request['target_point']))


def contract(request, reply, target):
    enemy = request['enemy']
    if 'jab_hold' in reply:
        shot = reply['jab_hold']
        chain = request['enemy_chain']
        return dict(kind='jab_hold', target_frame=shot['target_launch_frame'],
                    deadline_frame=shot['deadline_frame'], duration=shot['duration'],
                    check_delay=shot['check_delay'], hold_until_frame=reply['hold_down_until_frame'],
                    enemy_generation=enemy['mode_generation'], enemy_seed=enemy['seed_id'],
                    enemy_start=chain.get('start_frame', request['frame'] - chain['elapsed']),
                    entering=False, next_seed=True)
    if reply.get('reason') == 'normal_lethal_followup':
        return dict(kind='buried_followup', enemy_generation=enemy['mode_generation'],
            enemy_field=enemy['field'], gauge_limit=reply['followup_forecast']['gauge_limit'],
            need=reply['followup_forecast']['need'])
    if reply.get('score_rebuild'):
        return dict(kind='score_rebuild')
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
    if guard['kind'] == 'score_rebuild':
        return score_rebuild_safe(latest, latest['self'])
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
    if guard['kind'] == 'jab_hold':
        chain = latest.get('enemy_chain')
        if not enemy['remaining_frames'] or coming(latest) or (chain and (enemy['seed_id'] != guard['enemy_seed'] or
                chain.get('start_frame', latest['frame'] - chain['elapsed']) != guard['enemy_start'])):
            return False
        deadline = guard['deadline_frame']
        observed_end = enemy.get('fever_chain_end_frame') if not chain else None
        if observed_end is not None and observed_end >= guard['enemy_start']:
            deadline = min(deadline, observed_end + guard['check_delay'])
        return max(latest['frame'], guard['hold_until_frame']) + guard['duration'] < deadline
    finish = latest['frame'] + guard['duration']
    return guard['target_frame'] <= finish <= guard['deadline_frame']
