"""A Tsu-style lethal follow-up against buried normal opponents, with Fever gates."""
import json
from .timing import ChainTiming


class NormalFollowup:
    def __init__(self, native, scoring):
        self.native, self.scoring, self.cached = native, scoring, None

    def covered(self, request, own, enemy, config):
        """Existing lethal nuisance calls for construction, never another small shot."""
        pending = enemy.get('confirmed', 0) + enemy.get('unconfirmed', 0)
        if not config.get('enabled') or enemy['mode'] != 'normal' or not pending or request.get('enemy_chain'):
            return None
        incoming = request.get('observation', {}).get('in_flight', {}).get('self', {})
        if own['confirmed'] or own['unconfirmed'] or incoming.get('incoming_in_flight', 0) or incoming.get('counter_in_flight', 0):
            return None
        forecast = self.native.ask(dict(op='normal_followup', status_only=True,
            field=own['field'], target_point=request['target_point'], remainder=own['remainder'],
            powers=self.scoring.data['characters'][own['character']][own['mode']],
            bonuses=self.scoring.data['bonuses'],
            enemy=dict(field=enemy['field'], gauge=enemy['gauge'], remainder=enemy['remainder'],
                pending=pending, powers=self.scoring.data['characters'][enemy['character']]['normal']),
            options={k:v for k,v in config.items() if k!='enabled'}))
        return forecast if forecast.get('lethal_pending') else None

    def choose(self, request, own, enemy, baseline, config, margin, pace=None):
        if (not config.get('enabled', False) or enemy['mode'] != 'normal' or enemy['gauge'] >= 4
                or baseline.get('reason') not in ('normal_build_or_fire', 'fever_seed_search')
                or enemy.get('phase') not in ('controllable', 'placing')
                or request.get('enemy_chain') or own['confirmed'] or own['unconfirmed']
                or baseline.get('selected_move_loses')
                or any(margin.get(k) for k in ('rate_events', 'enemy_rate_events'))):
            return None
        incoming = request.get('observation', {}).get('in_flight', {}).get('self', {})
        if incoming.get('incoming_in_flight', 0) or incoming.get('counter_in_flight', 0):
            return None
        if sum(r.count('#') for r in enemy['field']) < config['min_garbage']:
            return None
        options = {k: v for k, v in config.items() if k != 'enabled'}
        query = dict(op='normal_followup', field=own['field'], queue=own['queue'],
            remainder=own['remainder'], target_point=request['target_point'],
            enemy=dict(field=enemy['field'], gauge=enemy['gauge'], remainder=enemy['remainder'],
                pending=enemy['confirmed']+enemy['unconfirmed'],
                powers=self.scoring.data['characters'][enemy['character']]['normal']),
            powers=self.scoring.data['characters'][own['character']][own['mode']],
            bonuses=self.scoring.data['bonuses'], gain=request['gauge_gain_on_offset'],
            timing=ChainTiming.for_mode(own['mode']).native(), pace_frames=int(pace or 0),
            maximum_lock=own['remaining_frames'] if own['mode']=='fever' else 1000000,
            options=options)
        key = json.dumps(query, sort_keys=True)
        if self.cached is None or self.cached[0] != key:
            self.cached = key, self.native.ask(query)
        forecast = self.cached[1]
        if not forecast['found']:
            return None
        first = forecast['choice']
        actual = self.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                     x=first['x'], r=first['r']))
        if actual['dead']:
            return None
        points = self.scoring.chain(own['character'], actual['links'], own['mode'])
        reply = dict(x=first['x'], r=first['r'], shape=own['queue'][0][0], reason='normal_lethal_followup',
            fire=bool(points), chain=len(points), next_chain=len(points), next_score=sum(points),
            next_field=actual['field'], next_all_clear=actual['all_clear'], link_points=points,
            searched_visible=len(own['queue']), followup_forecast=forecast)
        if own['mode'] == 'fever':
            # Seed preparation/clock guards consume the solver's original
            # geometry forecast. This override is restricted to an immediate fire.
            if not points or len(forecast['path']) != 1:
                return None
            fire_at = first['lock_frame'] + ChainTiming.for_mode('fever').first_link_frames
            step = dict(x=first['x'], r=first['r'], field=actual['field'], chain=len(points),
                link_points=points, fire_at=fire_at, end_at=forecast['attack_end'],
                all_clear=actual['all_clear'], dead=False, dropped=0, post_drop_field_known=True)
            reply['seed_forecast'] = dict(choice=step, path=[step], searched_visible=len(own['queue']))
            reply['input_required_frames'] = fire_at + request.get('seed_options',{}).get('safety_frames',8)
            if reply['input_required_frames'] >= own['remaining_frames']:
                return None
            reply['replaces_seed_on_clear'] = True
        reply['decision_dependencies'] = ['self', 'enemy']
        return reply
