"""Protocol 3: normal/Fever observations, seed solver and explicit mode events.

Run python -m fever_battle.mode_engine. This API does not control the game.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

from .engine import BattleEngine, SOLO_OPTIONS
from .forecast import GarbageSearch
from .mode import ModeReferee, rules
from .model import ROOT, integer, settled_field
from .observation import coherent
from .seed_solver import SeedSolver
from .timing import ChainTiming
from .threat import enemy_events
from .mode_tactics import offset_gauge, seed_strategy


def identity(request):
    own = request['self']
    return dict(match_id=request['match_id'], frame=request['frame'], piece_id=own['piece_id'],
                dropset_index=own['dropset_index'], mode_generation=own['mode_generation'], seed_id=own['seed_id'])


def authorize_mode_reply(request, reply, latest):
    coherent(request)
    coherent(latest)
    if reply.get('action') != 'place' or reply.get('decision_identity') != identity(request):
        raise ValueError('only a matching placement reply may authorize input')
    elapsed = latest['frame'] - request['frame']
    if elapsed < 0:
        raise ValueError('latest capture predates decision')
    for key in ('protocol_version', 'rule', 'match_id', 'target_point', 'gauge_gain_on_offset', 'clock_policy'):
        if request[key] != latest[key]:
            raise ValueError(f'{key} changed; discard decision')
    for name in ('self', 'enemy'):
        old, new = deepcopy(request[name]), deepcopy(latest[name])
        old.pop('observed_frame'); new.pop('observed_frame')
        if old['mode'] == 'fever':
            expected = max(0, old['remaining_frames'] - (elapsed if old['clock_running'] else 0))
            if new['remaining_frames'] != expected:
                raise ValueError('observed clock changed unexpectedly; replan')
            old['remaining_frames'] = expected
            if name == 'self':
                # Input must still fit the first move's estimated onset and margin.
                needed = reply.get('input_required_frames', 0)
                if expected <= needed:
                    raise ValueError('decision no longer fits the Fever deadline')
        if old != new:
            raise ValueError(f'{name} state changed; discard decision')
    return True


class ModeBattleEngine(BattleEngine):
    def __init__(self, native, solo, config):
        super().__init__(native, solo, config)
        self.mode_rules = rules()
        self.seed_solver = SeedSolver(self.native, self.scoring)

    def mode_side(self, side):
        if side['mode'] not in ('normal', 'fever'):
            raise ValueError('unsupported mode; transitions cannot request placements')
        integer(side['gauge'], 'gauge', 0, self.mode_rules['gauge_max'])
        integer(side['mode_generation'], 'mode_generation')
        integer(side['seed_id'], 'seed_id')
        integer(side['prepared_frames'], 'prepared_frames', 0, self.mode_rules['max_time_frames'])
        integer(side['remaining_frames'], 'remaining_frames', 0, self.mode_rules['max_time_frames'])
        integer(side['seed_base'], 'seed_base', 3, 15)
        integer(side['seed_chain'], 'seed_chain', 3, 15)
        if type(side['clock_running']) is not bool:
            raise ValueError('observed clock_running flag required')
        for key in ('normal_confirmed', 'normal_unconfirmed', 'fever_confirmed', 'fever_unconfirmed'):
            integer(side[key], key, 0, 10**9)
        if side['mode'] == 'normal':
            if side['stored_field'] is not None or side['remaining_frames'] or side['clock_running']:
                raise ValueError('normal mode cannot have stored board or running Fever timer')
            if side['fever_confirmed'] or side['fever_unconfirmed']:
                raise ValueError('Fever nuisance must be merged on normal return')
        else:
            settled_field(side['stored_field'])
        if (side['confirmed'], side['unconfirmed']) != (side[side['mode'] + '_confirmed'],
                                                       side[side['mode'] + '_unconfirmed']):
            raise ValueError('active nuisance disagrees with observed mode')
        # Share character/visible-piece/board validation, without changing the
        # caller's gauge or treating the mode as a normal-mode observation.
        normal_view = {**side, 'mode': 'normal', 'gauge': 0}
        super().side(normal_view)
        if type(side.get('awaiting_seed', False)) is not bool:
            raise ValueError('awaiting_seed must be boolean')
        return side

    def _prediction(self, character, rows, mode):
        result = self.native.ask(dict(op='resolve', field=rows))
        points = self.scoring.chain(character, result['links'], mode)
        return dict(points=points, field=result['field'], mode_timing_status=(
                    'normal_calibrated' if mode == 'normal' else 'normal_geometry_reference_fever_unverified'),
                    **ChainTiming().timeline(points, result['fall_distances'], result['fall_features']))

    def _normal(self, request, own, enemy, rate):
        overrides = request.get('solo_options', {})
        if not isinstance(overrides, dict) or set(overrides) - SOLO_OPTIONS:
            raise ValueError('unknown solo option')
        options = {**self.policy['solo_options'], **overrides, 'moves': own['moves_since_chain']}
        scheduled = []
        if request.get('enemy_chain') is not None:
            chain = request['enemy_chain']
            if chain['mode_generation'] != enemy['mode_generation'] or chain['seed_id'] != enemy['seed_id']:
                raise ValueError('enemy prediction belongs to another mode or seed')
            prediction = self._prediction(enemy['character'], chain['trigger_field'], enemy['mode'])
            scheduled = enemy_events(prediction, integer(chain['elapsed'], 'elapsed'), chain['scored_links'])
        if own['confirmed'] + own['unconfirmed'] or scheduled:
            forecast = self.garbage_search.search(own['character'], own['field'], own['queue'],
                own['confirmed'], own['unconfirmed'], own['remainder'], rate, own['garbage_phase'],
                min(1000, options.get('beam_width', 80)), enemy_events=scheduled,
                enemy_confirmed=enemy['confirmed'] + (enemy['normal_confirmed'] if enemy['mode'] == 'fever' else 0),
                enemy_unconfirmed=enemy['unconfirmed'] + (enemy['normal_unconfirmed'] if enemy['mode'] == 'fever' else 0),
                enemy_remainder=enemy['remainder'])
            return GarbageSearch.reply(forecast, own['queue'][0][0])
        result = self.solo.ask(dict(rule='fever', solo=True, character=own['character'],
            dropset_index=own['dropset_index'], self={'field': own['field'], 'queue': own['queue']},
            plain_pairs=True, include_next=True, **options))
        placements = self.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
        safe = [p for p in placements if not p['dead']]
        if not safe:
            raise ValueError('no surviving conservative normal placement')
        choice = next((p for p in safe if (p['x'], p['r']) == (result['x'], result['r'])), safe[0])
        points = self.scoring.chain(own['character'], choice['links'])
        return dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0], reason='normal_build_or_fire',
                    fire=bool(points), chain=len(points), next_chain=len(points), next_score=sum(points),
                    next_field=choice['field'], link_points=points, next_all_clear=choice['all_clear'])

    def answer(self, request):
        if not isinstance(request, dict):
            raise ValueError('request must be a JSON object')
        if request.get('protocol_version') != 3 or request.get('rule') != 'fever_battle':
            raise ValueError('requires protocol_version=3 and rule=fever_battle')
        op = request.get('op', 'think')
        if op == 'score':
            points = self.scoring.chain(request['character'], request['links'], request['mode'])
            return dict(points=points, total=sum(points), provenance=self.scoring.provenance)
        if op == 'referee':
            ref = ModeReferee(request['characters'], request['target_point'], request['gauge_gain_on_offset'])
            for event in request['events']:
                ref.apply(event)
            return {**ref.snapshot(), 'log': ref.log}
        if op == 'predict_chain':
            return self._prediction(request['character'], request['trigger_field'], request['mode'])
        if op != 'think':
            raise ValueError('unsupported operation')
        integer(request['gauge_gain_on_offset'], 'gauge_gain_on_offset', 0, 7)
        if not isinstance(request.get('match_id'), str) or not request['match_id']:
            raise ValueError('match_id required')
        coherent(request)
        rate = integer(request['target_point'], 'target_point', 1, 100000)
        own, enemy = self.mode_side(request['self']), self.mode_side(request['enemy'])
        policy = request['clock_policy']
        if not isinstance(policy, dict) or type(policy.get('count_chain_frames')) is not bool:
            raise ValueError('explicit clock_policy.count_chain_frames required')
        started = time.monotonic()
        if own.get('awaiting_seed') or (own['mode'] == 'fever' and own['remaining_frames'] == 0) or (
            own['mode'] == 'normal' and own['gauge'] == self.mode_rules['gauge_max']):
            return dict(action='wait', reason='await_observed_mode_or_seed', decision_identity=identity(request))
        if own['mode'] == 'fever':
            enemy_moves = self.native.ask(dict(op='placements', field=enemy['field'],
                piece=enemy['queue'][0]))['placements'] if enemy['phase'] == 'controllable' else []
            potential = max((sum(self.scoring.chain(enemy['character'], p['links'], enemy['mode']))
                             for p in enemy_moves if not p['dead']), default=0)
            options = request.get('seed_options', {})
            if not isinstance(options, dict):
                raise ValueError('seed_options must be an object')
            strategy, strategy_reason = seed_strategy(own, enemy, potential)
            if 'strategy' in options:
                strategy, strategy_reason = options['strategy'], 'explicit_common_strategy'
            result = self.seed_solver.solve(own, rate, policy['count_chain_frames'], {**options, 'strategy': strategy})
            first = result['choice']
            points = first['link_points']
            safety = request.get('seed_options', {}).get('safety_frames', 8)
            reply = dict(x=first['x'], r=first['r'], shape=own['queue'][0][0], reason='fever_seed_search',
                fire=bool(points), chain=first['chain'], next_chain=first['chain'], next_score=sum(points),
                next_field=first['field'], link_points=points, next_all_clear=first['all_clear'],
                seed_forecast=result, replaces_seed_on_clear=bool(points),
                seed_strategy_reason=strategy_reason, enemy_possible_score_now=potential,
                enemy_possible_is_confirmed=False,
                input_required_frames=first['fire_at'] + safety,
                selected_move_loses=first['dead'])
            if first['fire_at'] + safety >= own['remaining_frames']:
                return dict(action='wait', reason='await_timeout_no_input_fits', decision_identity=identity(request),
                            seed_forecast=result)
        else:
            reply = self._normal(request, own, enemy, rate)
            gauge = offset_gauge(reply['link_points'], own['confirmed'] + own['unconfirmed'],
                                 own['remainder'], rate, own['gauge'], request['gauge_gain_on_offset'])
            central_height = max(sum(row[x] != '.' for row in own['field']) for x in (2, 3))
            if (own['confirmed'] >= 30 or central_height >= 9) and gauge['gauge_after'] < 7:
                # Preserve normal construction as the default. Under a large
                # confirmed threat, compare clearing routes that can fill the
                # gauge without another nonclearing garbage drop.
                candidates = self.native.ask(dict(op='placements', field=own['field'],
                                                   piece=own['queue'][0]))['placements']
                entries = []
                for candidate in candidates:
                    if candidate['dead']:
                        continue
                    points = self.scoring.chain(own['character'], candidate['links'])
                    estimate = offset_gauge(points, own['confirmed'] + own['unconfirmed'], own['remainder'],
                                            rate, own['gauge'], request['gauge_gain_on_offset'])
                    if estimate['gauge_after'] == 7:
                        entries.append((candidate, points, estimate))
                if entries:
                    chosen, points, gauge = min(entries, key=lambda e: (len(e[1]), -sum(e[1])))
                    reply = dict(x=chosen['x'], r=chosen['r'], shape=own['queue'][0][0],
                                 reason='offset_to_enter_fever_under_threat', fire=bool(points),
                                 chain=len(points), next_chain=len(points), next_score=sum(points),
                                 link_points=points, next_field=chosen['field'], next_all_clear=chosen['all_clear'])
            reply.update(gauge_forecast=gauge, entry_pending_after_chain=gauge['gauge_after'] == 7)
        reply.update(action='place', protocol_version=3, rule='fever_battle', mode=own['mode'],
                     decision_identity=identity(request), model_status='prototype_unverified_on_local_steam',
                     provenance=self.scoring.provenance, search_ms=(time.monotonic() - started) * 1000)
        reply['mode_timing_status'] = ('normal_calibrated_input_estimated' if own['mode'] == 'normal'
                                       else 'normal_geometry_reference_fever_unverified')
        if reply['shape'] == '0':
            reply['color'] = 'RYGB'['URDL'.index(reply['r'])]
        return reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT / 'bin/t14/fever_battle.exe')
    parser.add_argument('--solo', type=Path, default=ROOT / 'bin/fever/fever.exe')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    args = parser.parse_args()
    engine = ModeBattleEngine(args.native, args.solo, args.config)
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                reply = engine.answer(json.loads(line))
            except (ValueError, KeyError, TypeError, TimeoutError, RuntimeError) as error:
                reply = {'error': str(error)}
            print(json.dumps(reply, ensure_ascii=False), flush=True)
    finally:
        engine.close()


if __name__ == '__main__':
    main()
