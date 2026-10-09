"""Protocol 3: normal/Fever observations, seed solver and explicit mode events.

Run python -m fever_battle.mode_engine. This API does not control the game.
"""
import argparse
from copy import deepcopy
import json
import statistics
from pathlib import Path
import sys
import time

from .engine import BattleEngine, SOLO_OPTIONS
from .forecast import GarbageSearch
from .mode import ModeReferee, rules, next_seed
from .model import ROOT, integer, settled_field
from .observation import coherent
from .seed_solver import SeedSolver
from .timing import ChainTiming
from .nuisance import Trays
from .threat import enemy_events
from .mode_tactics import QUICK_FRAMES, offset_gauge
from .normal_colors import report as report_colors
from .uncertainty import choose as uncertain_move
from .finish import choose as fast_finish
from . import tactics
from .uncertainty import outcomes
from .margin import MarginForecast
from . import disruption
from .seed_defense import SeedDefenses


def identity(request):
    own = request['self']
    return dict(match_id=request['match_id'], frame=request['frame'], piece_id=own['piece_id'],
                dropset_index=own['dropset_index'], mode_generation=own['mode_generation'], seed_id=own['seed_id'])


def clock_limit(policy):
    """Keep the referee's displayed-time model distinct from Steam's raw timer.

    Build 15209927 initializes FeverGauge at 960 and caps it at 1860 frames.
    The UI starts at 15 seconds. Live captures may pass the internal timer as-is;
    subtracting 60 would shorten the actual input deadline.
    """
    domain = policy.get('frame_domain', 'model')
    if domain == 'model':
        return rules()['max_time_frames']
    if domain == 'pc_15209927_internal':
        return 1860
    raise ValueError('unsupported Fever clock frame domain')


def authorize_mode_reply(request, reply, latest):
    coherent(request)
    coherent(latest)
    if request.get('margin_policy') != latest.get('margin_policy'):
        raise ValueError('margin policy changed; discard decision')
    if reply.get('action') != 'place' or reply.get('decision_identity') != identity(request):
        raise ValueError('only a matching placement reply may authorize input')
    elapsed = latest['frame'] - request['frame']
    if elapsed < 0:
        raise ValueError('latest capture predates decision')
    if not disruption.valid(reply, latest):
        raise ValueError('Fever jab deadline or target expired; discard decision')
    for key in ('protocol_version', 'rule', 'match_id', 'target_point', 'gauge_gain_on_offset', 'clock_policy'):
        if request[key] != latest[key]:
            raise ValueError(f'{key} changed; discard decision')
    # The opponent's side is not compared. A move decided on what they showed
    # when it was asked for is carried out; what they have done since is read
    # into the next decision. Discarding the move and searching again left the
    # piece falling unsteered. Our own board, queue, delivered nuisance, mode,
    # seed and clock stay strict.
    for name in ('self',):
        old, new = deepcopy(request[name]), deepcopy(latest[name])
        old.pop('observed_frame'); new.pop('observed_frame')
        # Bookkeeping can settle after the board is already controllable. It
        # changes the next search's scoring, not this piece's input geometry.
        for key in ('remainder', 'prepared_frames', 'prepared_frames_status'):
            old.pop(key, None); new.pop(key, None)
        if old['mode'] == new['mode'] == 'normal' and max(old['gauge'], new['gauge']) < 7:
            # Late accounting of the preceding clear cannot change this piece's geometry.
            for key in ('gauge', 'normal_chain_max', 'moves_since_chain'):
                old.pop(key, None); new.pop(key, None)
        # A repeated fresh fixed board has a newer timestamp but identical contents.
        if old.get('board_status') == new.get('board_status') == 'observed_fixed':
            old.pop('board_observed_frame', None); new.pop('board_observed_frame', None)
        if old['mode'] == 'fever':
            expected = max(0, old['remaining_frames'] - (elapsed if old['clock_running'] else 0))
            if new['remaining_frames'] != expected:
                raise ValueError('observed clock changed unexpectedly; replan')
            old['remaining_frames'] = expected
            # The clock controls awards/seed exchange. The observed active
            # piece remains playable until its phase or identity changes.
            # Held normal packets cannot change this seed's input geometry.
            for key in ('normal_confirmed', 'normal_unconfirmed'):
                old.pop(key, None); new.pop(key, None)
        # A flying packet does not fall yet. Carry out the chosen placement
        # rather than restarting steering on every opponent scoring link.
        # A proven clear suppresses this placement's drop even if the packet
        # becomes confirmed before input. Nonclearing deliveries stay strict.
        for key in ('unconfirmed', old['mode']+'_unconfirmed'):
            old.pop(key, None); new.pop(key, None)
        if reply.get('fire') and reply.get('chain', 0) > 0:
            for key in ('confirmed', old['mode']+'_confirmed'):
                old.pop(key, None); new.pop(key, None)
        if old != new:
            changed = sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key))
            raise ValueError(f'{name} state changed; discard decision ({", ".join(changed)})')
    return True


class ModeBattleEngine(BattleEngine):
    def __init__(self, native, solo, config):
        super().__init__(native, solo, config)
        self.mode_rules = rules()
        self.seed_solver = SeedSolver(self.native, self.scoring)
        self.seed_solver.value_model = self.policy.get('fever_seed', {}).get('value_model')
        self.prepared = None
        self.pace, self.pace_state, self.pace_samples = None, {}, {}
        self.margin_forecast = MarginForecast()
        self.margin = {}
        self.normal_build_cache = None
        self.normal_build_reused = False
        self.normal_build_used = False
        self.build_match = None
        self.chain_predictions = {}
        self.enemy_seed_predictions = {}
        self.seed_defenses = SeedDefenses(self.native,self.scoring)
        self.enemy_analysis = None

    def mode_side(self, side, max_time_frames=None):
        if side['mode'] not in ('normal', 'fever'):
            raise ValueError('unsupported mode; transitions cannot request placements')
        if side.get('nuisance_destination', side['mode']) not in ('normal', 'fever'):
            raise ValueError('invalid nuisance destination')
        for key in ('fever_entry_frame', 'fever_destination_frame'):
            if side.get(key) is not None:
                integer(side[key], key, 0)
        integer(side['gauge'], 'gauge', 0, self.mode_rules['gauge_max'])
        integer(side['mode_generation'], 'mode_generation')
        integer(side['seed_id'], 'seed_id')
        if 'normal_chain_max' in side:
            integer(side['normal_chain_max'], 'normal_chain_max', 0, 19)
        limit = self.mode_rules['max_time_frames'] if max_time_frames is None else max_time_frames
        if side['prepared_frames'] is None:
            if side.get('prepared_frames_status') != 'unknown' or side['mode'] != 'fever':
                raise ValueError('missing preparation timer requires explicit unknown Fever history')
        else:
            integer(side['prepared_frames'], 'prepared_frames', 0, limit)
        integer(side['remaining_frames'], 'remaining_frames', 0, limit)
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
        # A live blocked spawn can still receive DOWN even when the normal
        # search's death threshold has been reached.
        self.observed_side(side, unknown_history=True, blocked_spawn=True)
        if type(side.get('awaiting_seed', False)) is not bool:
            raise ValueError('awaiting_seed must be boolean')
        return side

    def _prediction(self, character, rows, mode):
        key = (character, mode, tuple(rows))
        if key in self.chain_predictions:
            return self.chain_predictions[key]
        result = self.native.ask(dict(op='resolve', field=rows))
        points = self.scoring.chain(character, result['links'], mode)
        clock = ChainTiming.for_mode(mode)
        prediction = dict(points=points, field=result['field'], mode_timing_status=clock.effective_status,
                          **clock.timeline(points, result['fall_distances'], result['fall_features']))
        if len(self.chain_predictions) >= 32:
            self.chain_predictions.clear()
        self.chain_predictions[key] = prediction
        return prediction

    def _observe_enemy_fever(self, request, enemy):
        """Keep the opponent model until entry, a new seed, or firing.

        Later link observations only retire scored links. They cannot move the
        absolute chain end/delivery frame or refresh geometry/queue strategy.
        """
        active = enemy['mode'] == 'fever' or enemy['gauge'] >= self.mode_rules['gauge_max']
        if not active:
            self.enemy_analysis = None
            return None
        seed = (request['match_id'], enemy['character'], enemy['mode_generation'], enemy['seed_id'])
        old = self.enemy_analysis
        chain = request.get('enemy_chain')
        firing = None if not chain else (chain['mode_generation'], chain['seed_id'],
            chain.get('start_frame', request['frame'] - chain['elapsed']))
        event = None
        if old is None or tuple(old['seed']) != seed:
            event = 'seed' if enemy['mode'] == 'fever' and not enemy.get('awaiting_seed') else 'entry'
        elif old['enemy']['mode'] != enemy['mode'] or (
                old['enemy'].get('awaiting_seed') and not enemy.get('awaiting_seed')):
            event = 'seed'
        if firing is not None and (old is None or old.get('firing') != list(firing)):
            event = 'fire'
        if event is None:
            return old
        model = dict(seed=list(seed), event=event, observed_frame=request['frame'],
            enemy=deepcopy(enemy), firing=list(firing) if firing else None,
            events=[], strategy=None)
        if chain:
            remaining = self._live_enemy_events(request, enemy)
            model['events'] = [{**e, 'frame': request['frame'] + e['frame']} for e in remaining]
            model['scored_at_fire'] = chain['scored_links']
            model['chain_end_frame'] = next((e['frame'] for e in model['events'] if e['type'] == 'end'), None)
            # Chain end confirms the packet; the actual board drop is evaluated
            # against our next nonclearing lock, not claimed to be at chain end.
            model['packet_confirm_frame'] = model['chain_end_frame']
        self.enemy_analysis = model
        return model

    def _enemy_events(self, request, enemy):
        model = self._observe_enemy_fever(request, enemy)
        if model is None:
            return self._live_enemy_events(request, enemy)
        chain = request.get('enemy_chain')
        scored = max(0, (chain['scored_links'] if chain else model.get('scored_at_fire', 0))
                     - model.get('scored_at_fire', 0))
        links = 0
        result = []
        for event in model['events']:
            if event['type'] == 'link':
                links += 1
                if links <= scored or (chain is None and event['frame'] < request['frame']):
                    continue
            result.append({**event, 'frame': max(0, event['frame'] - request['frame'])})
        return result

    def _live_enemy_events(self, request, enemy):
        chain = request.get('enemy_chain')
        if chain is None:
            return []
        if chain['mode_generation'] != enemy['mode_generation'] or chain['seed_id'] != enemy['seed_id']:
            raise ValueError('enemy prediction belongs to another mode or seed')
        if chain.get('ended'):
            # Observed to have ended: what it sent and is still unconfirmed is confirmed now.
            return [dict(type='end', frame=0)]
        prediction = self._prediction(enemy['character'], chain['trigger_field'], enemy['mode'])
        if not prediction['points'] or ('first_link_points' in chain and chain['first_link_points'] != prediction['points'][0]):
            return []  # Drawn board/score did not prove this chain; keep arrival unknown.
        if enemy['mode'] == 'fever':
            key = (enemy['character'], enemy['mode_generation'], enemy['seed_id'])
            self.enemy_seed_predictions[key] = next_seed(enemy['seed_base'], len(prediction['points']),
                all(row == '......' for row in prediction['field']), displayed=enemy['seed_chain'])
        scored = integer(chain['scored_links'], 'scored_links', 0, len(prediction['links']))
        elapsed = integer(chain['elapsed'], 'elapsed')
        if 'observed_link_frame' in chain:
            onset = integer(chain['observed_link_frame'], 'observed_link_frame', 0, request['frame'])
            anchor = integer(chain.get('observed_link', scored), 'observed_link', 1, len(prediction['links']))
            elapsed = prediction['links'][anchor-1]['score_at'] + request['frame']-onset
        return enemy_events(prediction, elapsed, scored)

    def _normal_options(self, request, own):
        overrides = request.get('solo_options', {})
        if not isinstance(overrides, dict) or set(overrides) - SOLO_OPTIONS:
            raise ValueError('unknown solo option')
        options = {**self.policy['solo_options'], **overrides}
        if request.get('second_target_chain') is not None:
            integer(request['second_target_chain'], 'second_target_chain', 2, 19)
        if own['moves_since_chain'] is not None:
            options['moves'] = own['moves_since_chain']
        else:
            options.pop('patience', None)  # no history-based impatience threshold
        options.setdefault('beam_width', 50)
        options.setdefault('beam_depth', 8)
        if self._after_opening(own, options):
            # Build the second chain to the top just like the opening. Release
            # the chain-length requirement only once the board is filled.
            target = request.get('second_target_chain')
            target = max(4, options['trigger'] - 1) if 'second_target_chain' not in request else target
            ready = 1 if self._stack_full(own, options) else ((target or 19) if 'second_target_chain' in request else 19)
            target = target or 19
            options.update(build_chain=target, trigger=ready, panic_chain=ready,
                           panic_count=0, panic_step=0, patience=0)
        else:
            target = options['trigger']
            ready = 1 if self._stack_full(own, options) else target
            options.update(build_chain=target, trigger=ready, panic_chain=ready,
                           panic_count=0, panic_step=0, patience=0)
        options['preserve_build'] = True
        build = self.policy.get('normal_build', {})
        if (build.get('objective') == 'fever_aim' and request['enemy']['mode'] == 'fever' and request['gauge_gain_on_offset'] > 0
                and own['gauge'] < self.mode_rules['gauge_max']):
            # Fever aim: build what offsets link by link, not one long chain.
            # The builder ranks by its evaluation and fires nothing by length.
            aim = build['fever_aim']
            options.update(aim['solo_options'], aim=True, weight_set=aim['weight_set'],
                           stock_want=self.mode_rules['gauge_max'] - own['gauge'])
        self.last_normal_options = dict(options)
        return options

    def _after_opening(self, own, options=None):
        # Only observed history releases the target, never a proposed fire or
        # a speculative preparation. Mode generation survives normal return.
        target = (options or self.policy['solo_options'])['trigger']
        return (own['mode_generation'] > 0 or
                own.get('normal_chain_max', 0) >= max(4, target - 1))

    def _stack_full(self, own, options):
        margin = max(0, min(6, options.get('margin', 1)))
        # Twelve rows in the outer columns; keep the existing safety margin
        # below the death row in the two middle columns.
        capacity = 4 * 12 + 2 * (11 - margin)
        cells = {'2': 2, 'L': 3, 'J': 3, '4': 4, '0': 4}[own['queue'][0][0]]
        occupied = sum(c != '.' for row in own['field'] for c in row)
        if occupied + cells >= capacity or any(sum(row[x] != '.' for row in own['field']) > 11 for x in (2,3)):
            return True
        # An uneven board can run out of safe stacking moves sooner.
        moves = self.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
        return not any(not p['dead'] and not p['links'] and
            sum(c != '.' for row in p['field'] for c in row) >= occupied+cells and
            all(sum(row[x] != '.' for row in p['field']) <= 11-margin for x in (2,3)) for p in moves)

    def _solo_build(self, own, options):
        self.normal_build_used = True
        key = json.dumps(dict(match=self.build_match, character=own['character'],
            field=own['field'], piece_id=own['piece_id'], dropset_index=own['dropset_index'],
            mode_generation=own['mode_generation'], seed_id=own['seed_id'],
            options={k: v for k, v in options.items() if k != 'budget_ms'}), sort_keys=True)
        cached = self.normal_build_cache
        if cached and cached[0] == key and own['queue'][:len(cached[1])] == cached[1]:
            # A two-visible-piece prepare is deliberately reused with fresh
            # NEXT2. Nuisance is handled by the tactical layer, not this solo
            # search, whose inputs contain no opponent or packet counts.
            self.normal_build_reused = True
            return deepcopy(cached[2])
        build = {key: value for key, value in options.items() if key != 'weight_set'}
        result = self.solo.ask(dict(rule='fever', solo=True, character=own['character'],
            dropset_index=own['dropset_index'], self={'field': own['field'], 'queue': own['queue']},
            plain_pairs=True, special_moves=True, include_next=True, **build), **(
                {'weight_set': options['weight_set']} if 'weight_set' in options else {}))
        self.normal_build_cache = (key, list(own['queue']), deepcopy(result))
        return result

    # What a side says that moves from frame to frame without changing a decision
    # made on it. The clock is weighed separately (see _clock_allows).
    VOLATILE = ('observed_frame', 'board_observed_frame', 'board_status', 'phase', 'remaining_frames',
                'remainder', 'prepared_frames', 'prepared_frames_status', 'clock_running',
                'observed_drop_count_cursor')
    # Held normal nuisance changes the final-failure policy; retain it in the
    # prepared-decision identity even though it cannot fall on this seed.
    FEVER_UNREAD = ()  # Flying nuisance now affects turnover vs next-entry growth.
    # Fever exception: frames the clock may have run past the prepared estimate
    # once time is short enough for the search to weigh it (a split or a long
    # fall takes more than the estimate). With more time than QUICK_FRAMES no
    # visible line reaches the deadline. The move's own deadline is always
    # checked on the observed clock.
    FEVER_PREPARED_SLACK = 30
    OBSERVED_SPAWN_FRAMES = 14      # from the board standing between two pieces to the next piece

    def _signature(self, request, own, final_exchange=False):
        """Everything a decision for this side rests on, for the first two visible pieces."""
        side = {key: value for key, value in own.items() if key not in self.VOLATILE}
        side['queue'] = own['queue'][:2]
        options = request.get('solo_options', {})
        if own['mode'] == 'fever':
            for key in self.FEVER_UNREAD:
                side.pop(key, None)
            options = self._seed_options(request, own, None)[0]
        chain = request.get('enemy_chain')
        enemy = request['enemy'] if chain else None
        if chain:
            # The same observed attack advances with the capture clock. That
            # alone must not discard the seed search done before spawn.
            chain = {k: v for k, v in chain.items() if k != 'elapsed'}
            chain['started_frame'] = request['frame'] - request['enemy_chain']['elapsed']
            enemy = {k: v for k, v in enemy.items() if k not in self.VOLATILE}
            if final_exchange:
                # For a nonclear before delivery, scoring only transfers the
                # same known packet from future links into the current tray.
                # Keep confirmation, held normal nuisance and the absolute
                # delivery frame: those can change this placement's outcome.
                events = self._enemy_events(request, request['enemy'])
                trays = Trays(enemy)
                flying, remainder = own['unconfirmed'], request['enemy']['remainder']
                for event in events:
                    if event['type'] != 'link':
                        continue
                    amount, remainder = divmod(event['points'] + remainder, request['target_point'])
                    if trays.pending() and amount == 0:
                        amount = 1
                    flying += trays.offset(amount)
                side['unconfirmed'] = flying
                side[own['mode'] + '_unconfirmed'] = flying
                for key in ('field', 'confirmed', 'unconfirmed', 'normal_confirmed',
                            'normal_unconfirmed', 'fever_confirmed', 'fever_unconfirmed', 'remainder'):
                    enemy.pop(key, None)
                enemy.update(final_trays=trays.identity(), final_remainder=remainder)
                chain = {k: v for k, v in chain.items() if k not in
                         ('scored_links', 'observed_link', 'observed_link_frame')}
                chain['delivery_frame'] = request['frame'] + next(
                    (e['frame'] for e in events if e['type'] == 'end'), 0)
        return json.dumps(dict(match_id=request['match_id'], target_point=request['target_point'],
            gauge_gain_on_offset=request['gauge_gain_on_offset'], clock_policy=request['clock_policy'],
            margin={key: [{**e, 'frame': request['frame'] + e['frame']} for e in self.margin.get(key, [])]
                    for key in ('rate_events', 'enemy_rate_events')},
            options=options, second_target_chain=request.get('second_target_chain', 'legacy'), side=side,
            enemy_prediction=chain, enemy_state=enemy), sort_keys=True)

    def _prepared_delivery_stable(self, request, own, enemy, reply):
        """Do not reuse a nonclear across an attack now able to land on it."""
        forecast = reply.get('tactics_forecast', {})
        choice = forecast.get('choice', {})
        if not disruption.valid(reply, request):
            return False
        if reply.get('disruption_timing') and choice.get('disruption_kind') == 'jab':
            target = self._enemy_fever(enemy, self._enemy_events(request, enemy), request['target_point']) or {}
            end = target.get('their_end')
            if end is None or not end <= choice['attack_end'] <= end + target.get('disrupt_window', 26):
                return False
        if reply.get('fire') or not request.get('enemy_chain'):
            return True
        if own['mode'] == 'normal':
            timing = ChainTiming.for_mode('normal')
            transition = self.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                             x=reply['x'], r=reply['r']))
            check = (timing.placement_frames + timing.nuisance_check_frames +
                     timing.split_extra_frames[max(transition['split_distances'], default=0)])
            return not any(e['type'] == 'end' and e['frame'] <= check
                           for e in self._enemy_events(request, enemy))
        first = reply['seed_forecast']['choice']
        timing = ChainTiming.for_mode('fever')
        check = first['fire_at'] + timing.nuisance_check_frames
        return not any(e['type'] == 'end' and e['frame'] <= check
                       for e in self._enemy_events(request, enemy))

    def _attack_rate_stable(self, request, enemy):
        end = max((e['frame'] for e in self._enemy_events(request, enemy)), default=0)
        return not any(e['frame'] <= end for key in ('rate_events', 'enemy_rate_events')
                       for e in self.margin.get(key, []))

    def _clock_allows(self, own, estimate):
        return (own['mode'] != 'fever' or own['remaining_frames'] > QUICK_FRAMES
                or estimate - own['remaining_frames'] <= self.FEVER_PREPARED_SLACK)

    def _stacking_still_fits(self, own, reply):
        """A prepared placement that pops nothing is used only while the next piece can still appear."""
        if own['mode'] != 'fever' or reply.get('fire'):
            return True
        first = reply.get('seed_forecast', {}).get('choice')
        if first is None:
            return False
        timing = ChainTiming.for_mode('fever')
        fire_at = first.get('fire_at', 0)
        safety = max(0, reply.get('input_required_frames', fire_at+8)-fire_at)
        ready_delay = (timing.nuisance_ready_frames if first.get('dropped') else
                       max(0, timing.spawn_frames-timing.nuisance_check_frames))
        return own['remaining_frames'] > first['end_at'] + ready_delay + safety

    def _after_placement(self, request, own):
        """This side as its next piece will find it, or the reason it cannot be told.

        The same in both modes: a board is predicted only across a placement
        that clears nothing and lets nothing fall.
        """
        if own.get('awaiting_seed') or len(own['queue']) != 3:
            return 'cannot_predict_next_board'
        if own['confirmed']:
            return 'confirmed_nuisance_falls_on_unknown_columns'
        if own['mode'] == 'normal' and own['gauge'] == self.mode_rules['gauge_max']:
            return 'cannot_predict_next_board'        # normal exception: the next piece is a Fever seed's
        placement = request['placement']
        if not isinstance(placement, dict) or set(placement) != {'x', 'r'}:
            raise ValueError('prepare requires only placement x/r')
        result = self.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0], **placement))
        if result['dead'] or result['links']:
            return 'clear_or_mode_transition_requires_observation'
        if request.get('enemy_chain'):
            timing = ChainTiming.for_mode(own['mode'])
            check = timing.placement_frames + timing.split_extra_frames[max(result['split_distances'], default=0)] + timing.nuisance_check_frames
            if any(e['type'] == 'end' and e['frame'] <= check for e in self._enemy_events(request, request['enemy'])):
                return 'enemy_delivery_can_change_next_board'
        future = deepcopy(own)
        future.update(field=result['field'], queue=own['queue'][1:],
            piece_id=own['piece_id']+1, dropset_index=(own['dropset_index']+1)%16)
        if future['moves_since_chain'] is not None:
            future['moves_since_chain'] += 1
        if own['mode'] == 'fever' and own['clock_running']:
            # Fever exception: the clock runs on, by the solver's own estimate for one placement.
            timing = ChainTiming.for_mode('fever', placement_frames=request.get('seed_options', {}).get('placement_frames', 14))
            split = timing.split_extra_frames[max(result['split_distances'], default=0)]
            future['remaining_frames'] = max(0, own['remaining_frames'] - timing.placement_frames - timing.spawn_frames - split)
        return future

    def _prepare(self, request, own, enemy, rate, policy, observed):
        """Decide the next piece before it appears, exactly as `think` will.

        `prepare`: the side is the one the current piece was decided on, and
        `placement` where that piece goes. `prepare_observed`: the side already
        is the next piece's, read from the board standing between two pieces
        (after a chain, a delivery, a new seed). Only the two pieces visible by
        then are used. The decision is kept for one `think` that finds the side
        as predicted; that think then costs no search.

        An enemy chain or rate change makes the input plan speculative: DOWN
        waits for the spawn check. A Fever search can still be kept while the
        same attack advances, provided its signature, clock and delivery guard
        all fit then. Normal tactics and imminent rate changes are refreshed.
        """
        self.prepared = None
        refresh_margin = bool(self.margin.get('rate_events') or self.margin.get('enemy_rate_events'))
        speculative = bool(request.get('enemy_chain') or refresh_margin)
        if observed:
            if len(own['queue']) not in (2, 3):
                return dict(prepared=False, reason='cannot_predict_next_board')
            future = deepcopy(own)
            future['queue'] = own['queue'][:2]
            if own['mode'] == 'fever' and own['clock_running']:
                future['remaining_frames'] = max(0, own['remaining_frames'] - self.OBSERVED_SPAWN_FRAMES)
        else:
            future = self._after_placement(request, own)
            if isinstance(future, str):
                return dict(prepared=False, reason=future)
        ahead = {key: value for key, value in request.items() if key not in ('op', 'placement')}
        ahead['self'] = future
        started = time.monotonic()
        reply = self._think(ahead, future, enemy, rate, policy, 'think')
        if reply.get('action') != 'place' or reply.get('selected_move_loses'):
            return dict(prepared=False, reason=reply.get('reason'),
                        **({'normal_build_prepared': self.normal_build_used} if speculative else {}))
        kept = True  # Absolute rate schedules are part of the signature.
        if kept:
            self.prepared = (self._signature(ahead, future), future['remaining_frames'], reply,
                             self._signature(ahead, future, final_exchange=True))
        placement = dict(x=reply['x'], r=reply['r'])
        if 'color' in reply:
            placement['color'] = reply['color']
        active = ('confirmed',) if future['mode'] == 'fever' else ('confirmed', 'unconfirmed')
        plan = dict(match_id=request['match_id'], mode=future['mode'],
            character=future['character'], field=future['field'], queue=future['queue'],
            piece_id=future['piece_id'], dropset_index=future['dropset_index'],
            mode_generation=future['mode_generation'], seed_id=future['seed_id'],
            nuisance={key: future[key] for key in active}, reason=reply['reason'], placement=placement)
        if not observed:
            plan.update(source_queue=own['queue'], source_index=own['dropset_index'])
        if speculative:
            plan['speculative'] = True
            return dict(prepared=True, speculative=True, normal_build_prepared=self.normal_build_used,
                seed_search_prepared=kept and future['mode'] == 'fever',
                normal_search_prepared=kept and future['mode'] == 'normal',
                searched_visible=len(future['queue']), search_ms=(time.monotonic()-started)*1000,
                controller=False, plan=plan, reason='speculative_input_with_guarded_seed_cache' if kept and future['mode'] == 'fever'
                    else 'speculative_input_with_guarded_normal_cache' if kept
                    else 'speculative_plan_decided_again_on_spawn')
        return dict(prepared=True, searched_visible=len(future['queue']),
            search_ms=(time.monotonic()-started)*1000, controller=False, plan=plan)

    def _seed_options(self, request, own, enemy):
        options = request.get('seed_options', {})
        self.seed_solver.validate_options(options)
        # One measure ranks every line (seed_search.cpp); there is no strategy to choose.
        return dict(options), 'expected_points_by_the_end_of_this_fever'

    def _tactics(self, request, own, enemy, rate, build=None, allowed=None):
        """The single search's reply to a threat on the normal board, or None to leave it to the rest."""
        trigger = self.last_normal_options.get('trigger', 15) if hasattr(self, 'last_normal_options') else 15
        points = 40 * sum(max(1, p) for p in self.scoring.data['characters'][own['character']]['normal'][:trigger])
        policy = {**self.policy['normal_tactics'], 'main_trigger_points': points, 'margin': self.last_normal_options.get('margin', 1)
                  if hasattr(self, 'last_normal_options') else 1}
        events = self._enemy_events(request, enemy)
        threat = own['confirmed'] + own['unconfirmed'] or any(
            e['type'] == 'link' and e.get('points', 0) > 0 for e in events)
        # Offsets earn no gauge: the nuisance search of the gauge-free battle answers.
        # Without a threat only a recovery (allowed) has anything to decide here.
        if request['gauge_gain_on_offset'] <= 0 or own['gauge'] >= self.mode_rules['gauge_max']:
            return None
        # Nothing threatens: the builder places the piece, unless the same search finds something
        # worth sending at an opponent on a normal board (tactics.py, quiet).
        quiet = not threat and allowed is None
        fever = self._enemy_fever(enemy, events, rate, analyze=True)
        if quiet:
            # Worth a search where there is a main chain to send, an opponent in Fever to disrupt,
            # or a board small enough to clear whole within the visible pieces.
            puyos = sum(c not in '.#' for row in own['field'] for c in row)
            if not policy.get('quiet', False) or not (fever is not None or puyos <= policy.get('all_clear_puyos', 24)
                    or puyos >= 24):
                return None
        builder = None
        builder_fire = False
        if build is not None:
            try:
                built = build()
                if isinstance(built, dict):
                    builder = (built['x'], built['r'])
                    builder_fire = bool(built.get('fire'))
                else:
                    builder = built
            except ValueError:
                builder = None      # nothing the builder plays survives; the search decides alone
        harass = False
        if quiet and fever is None:
            # main's crush search is available beside a built field, independently
            # of whether the builder happened to choose a small clear itself.
            count = sum(c != '.' for row in own['field'] for c in row)
            heights = [sum(row[x] != '.' for row in own['field']) for x in range(6)]
            harass = policy['weights'].get('harass', 0) > 0 and 24 <= count < 52 and all(h > 3 for h in heights[:3])
        # Shapes of the pieces after the visible ones: the character's cycle is known, the colors are not.
        after = own['dropset_index'] + len(own['queue'])
        upcoming = ''.join(self.patterns[own['character']][(after + i) % 16] for i in range(16))
        defense = dict(self._enemy_defense(enemy, events, rate), offset_gain=request['gauge_gain_on_offset'])
        first_normal_battle = own['mode'] == enemy['mode'] == 'normal' and own['mode_generation'] == enemy['mode_generation'] == 0
        reply = tactics.choose(self.native, self.scoring, own, rate, request['gauge_gain_on_offset'],
            policy, events, enemy, self.margin, allowed, builder, defense, upcoming, harass, self.pace, quiet,
            fever, self._enemy_hold(enemy, events, rate),
            invite_fever=first_normal_battle, avoid_own_fever=first_normal_battle, builder_fire=builder_fire)
        # A position every placement loses belongs to the finish probe below.
        return None if reply is None or reply['selected_move_loses'] else reply

    def _board_hold(self, character, rows):
        """main gaze.main_q: maximum score of quiet(8, 3), using Fever normal powers."""
        if rows is None:
            return 0
        key = (character, tuple(rows))
        cache = getattr(self, 'board_holds', {})
        if key in cache:
            return cache[key]
        try:
            score = self.native.ask(dict(op='normal_gaze', field=rows,
                powers=self.scoring.data['characters'][character]['normal'],
                bonuses=self.scoring.data['bonuses']))['score']
            if len(cache) >= 64:
                cache.pop(next(iter(cache)))
            cache[key] = score
            self.board_holds = cache
            return score
        except ValueError:
            return 0

    def _enemy_hold(self, enemy, events, rate):
        """Nuisance the opponent can still send with what they hold, apart from a chain already observed.

        Normal: maximum quiet-search score of their board. Fever: the seeds their clock
        still lets them fire, each at its level as one group of four per link
        and one level up after it, and then the chain of the board they return
        to. A measure of boards and of the clock, not of their pieces; the
        seed model and its times are the estimates of the seed search.
        """
        if enemy['mode'] != 'fever':
            return 0 if events else self._board_hold(enemy['character'], enemy['field']) // rate
        timing = ChainTiming.for_mode('fever')
        level, clock, points = enemy['seed_chain'], enemy['remaining_frames'], 0
        if events:      # the seed in hand is the chain observed; the next one comes after it
            clock -= max(e['frame'] for e in events) + timing.chain_ready_frames
            level = min(15, level + 1)
        while clock > 0:
            seed = self.scoring.chain(enemy['character'], [dict(groups=[4], colors=1)] * level, 'fever')
            points += sum(seed)
            clock -= timing.placement_frames + timing.timeline(seed, [1] * level)['end_frame'] + timing.chain_ready_frames
            level = min(15, level + 1)
        return (points + self._board_hold(enemy['character'], enemy['stored_field'])) // rate

    def _seed_room(self, level):
        """Nuisance that fills a Fever board holding a fresh seed of this level: whole rows to the top of
        its middle columns, by the median height of the reference seeds of that level."""
        if not hasattr(self, 'seed_heights'):
            seeds = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))['seeds']
            heights = {}
            for seed in seeds:
                heights.setdefault(seed['seed_chain'], []).append(
                    max(sum(row[x] != '.' for row in seed['field']) for x in (2, 3)))
            self.seed_heights = {level: statistics.median(values) for level, values in heights.items()}
        known = sorted(self.seed_heights)
        height = self.seed_heights[min(known, key=lambda k: abs(k - level))]
        return 6 * max(0, 12 - int(height))

    def _enemy_defense(self, enemy, events, rate):
        """What the opponent has against nuisance sent to them (fever_battle/transition.h, Defense).

        On a normal board with no chain running: what their longest chain
        offsets, what fills the board (whole rows up to the top of its two
        middle columns), the links they can pop one trigger after another and
        the offsets their gauge still needs. With a chain running on a normal
        board nothing is taken to kill. In Fever no gauge saves them: what
        offsets is the seed in hand fired at its level (the next seed while a
        chain runs or a seed is about to come), and what fills the board is
        the room on it (of a fresh seed of that level in those two cases),
        counted only where a single drop fills it.
        """
        fever = self._enemy_fever(enemy, events, rate)
        if fever is not None:
            enemy = self.enemy_analysis['enemy'] if self.enemy_analysis else enemy
            level = fever['enemy_seed_level']
            seed = sum(self.scoring.chain(enemy['character'], [dict(groups=[4], colors=1)] * level, 'fever'))
            if enemy['mode'] == 'fever' and not events:
                room = 6 * max(0, 12 - max(sum(row[x] != '.' for row in enemy['field']) for x in (2, 3)))
            else:
                room = self._seed_room(level)
            # A Fever board is replaced with every seed fired, so nuisance does not pile up on it: only
            # one drop (thirty at most) that fills it kills. Short of that a packet disrupts the seed.
            return dict(hold=seed // rate, kill=room if room <= 30 else 0, links=0, need=self.mode_rules['gauge_max'])
        hold = self._enemy_hold(enemy, events, rate)
        if events:
            return dict(hold=hold, kill=0, links=0, need=1)
        rows = enemy['field']
        height = max(sum(row[x] != '.' for row in rows) for x in (2, 3))
        need = self.mode_rules['gauge_max'] - enemy['gauge']
        try:
            links = self.native.ask(dict(op='stock', field=rows, want=max(1, need)))['links']
        except ValueError:
            return dict(hold=hold, kill=0, links=0, need=1)
        # Actual visible first-piece replies, cached independently of their gauge.
        # A long potential chain does not imply that a small packet offsets on
        # every link: count only links while nuisance still remains.
        profiles = []
        if enemy['phase'] == 'controllable' and enemy['queue']:
            key = (enemy['character'], tuple(rows), enemy['queue'][0])
            cache = getattr(self, 'enemy_counter_profiles', {})
            if key not in cache:
                moves = self.native.ask(dict(op='placements', field=rows, piece=enemy['queue'][0]))['placements']
                if len(cache) >= 64:
                    cache.pop(next(iter(cache)))
                cache[key] = [self.scoring.chain(enemy['character'], m['links'], 'normal')
                              for m in moves if not m['dead'] and m['links']]
                self.enemy_counter_profiles = cache
            profiles = cache[key]
        return dict(hold=hold, kill=6 * max(0, 12 - height), links=links, need=need,
                    gauge=enemy['gauge'], counter_points=profiles,
                    rate=rate, remainder=enemy['remainder'])

    def _enemy_fever(self, enemy, events, rate=120, analyze=False):
        model = self.enemy_analysis
        if model is None:
            # Direct callers/tests without an observation retain the helper API.
            return self._calculate_enemy_fever(enemy, events, rate, analyze)
        if model['strategy'] is None:
            frozen = deepcopy(model['enemy'])
            base_events = [{**e, 'frame': max(0, e['frame']-model['observed_frame'])}
                           for e in model['events']] if model['events'] else deepcopy(events)
            target = self._calculate_enemy_fever(frozen, base_events, rate, True)
            if target is not None:
                target['analysis_event'] = model['event']
                target['analysis_frame'] = model['observed_frame']
                target['chain_end_frame'] = model.get('chain_end_frame')
                target['packet_confirm_frame'] = model.get('packet_confirm_frame')
                for name in ('their_end', 'enemy_fever_at'):
                    if name in target:
                        target[name] += model['observed_frame']
            model['strategy'] = target
        target = deepcopy(model['strategy'])
        if target is not None:
            for name in ('their_end', 'enemy_fever_at'):
                if name in target:
                    target[name] = max(0, target[name]-enemy['observed_frame'])
            if 'disrupt_window' in target and 'their_end' in model['strategy']:
                deadline = model['strategy']['their_end'] + model['strategy']['disrupt_window']
                target['disrupt_window'] = max(0, deadline-max(enemy['observed_frame'],model['strategy']['their_end']))
        return target

    def _calculate_enemy_fever(self, enemy, events, rate=120, analyze=False):
        """What the searches are told of an opponent in Fever, or None for one who is not.

        In Fever, or on a normal board with the gauge full (the seed is about to come).
        `their_end`: running seed-chain end, or the predicted normal-to-Fever
        destination switch. Entry includes the measured wait for first control;
        an unknown boundary is left absent. `enemy_seed_level` is the next seed.
        """
        entering = enemy['mode'] == 'normal' and enemy['gauge'] >= self.mode_rules['gauge_max']
        if enemy['mode'] != 'fever' and not entering:
            return None
        timing = self.policy['fever_entry_timing']
        entry_delay = timing['normal_chain_end_to_destination_frames']
        entry_window = timing['destination_to_first_control_frames'] + timing['disrupt_after_first_control_frames']
        destination = enemy.get('nuisance_destination', enemy['mode'])
        told = dict(enemy_fever=True, enemy_seed_level=enemy['seed_chain'])
        if destination == 'fever':
            told['enemy_fever_at'] = 0
        end = next((event['frame'] for event in events if event['type'] == 'end'), None)
        if enemy['mode'] == 'fever' and end is not None:
            key = (enemy['character'], enemy['mode_generation'], enemy['seed_id'])
            told.update(their_end=end, enemy_seed_level=self.enemy_seed_predictions.get(key, min(15, enemy['seed_chain'] + 1)))
        elif entering and (end is not None or enemy.get('fever_destination_frame') is not None):
            # Steam 15209927 measured sample: destination switches 16F after chain end.
            # Each outgoing link before that still belongs to the normal tray.
            at = (max(0, enemy['fever_destination_frame'] - enemy['observed_frame'])
                  if enemy.get('fever_destination_frame') is not None else end + entry_delay)
            told.update(enemy_fever_at=at, their_end=at,
                        disrupt_window=entry_window, enemy_entry_status=timing['status'])
        elif destination == 'fever' and enemy.get('fever_chain_end_frame') is not None:
            elapsed = max(0, enemy['observed_frame'] - enemy['fever_chain_end_frame'])
            if elapsed <= 26:
                told.update(their_end=0, disrupt_window=26-elapsed)
        elif destination == 'fever' and enemy.get('awaiting_seed'):
            entry = enemy.get('fever_entry_frame')
            elapsed = max(0, enemy['observed_frame'] - entry) if entry is not None else 0
            told.update(their_end=0, disrupt_window=max(0, entry_window - elapsed),
                        enemy_entry_status='observed_destination_switch')
        level = told['enemy_seed_level']
        seed = self.scoring.chain(enemy['character'], [dict(groups=[4], colors=1)] * level, 'fever')
        told['enemy_reply_nuisance'] = sum(seed) // rate
        # The next large piece can immediately return a jab, and this final
        # seed then returns to the normal board: there is no following Fever
        # seed to obstruct. This is an estimate, not a guaranteed solution.
        end = told.get('their_end', 0)
        clock = enemy['remaining_frames'] - end
        timing_model = ChainTiming.for_mode('fever')
        duration = timing_model.placement_frames + timing_model.timeline(seed, [1]*level)['end_frame'] + timing_model.chain_ready_frames
        next_piece = enemy['queue'][1 if events and len(enemy['queue']) > 1 else 0]
        told['enemy_skip_jab'] = enemy['mode'] == 'fever' and next_piece.startswith('0:') and clock <= duration
        fixed=enemy.get('board_status','observed_fixed')=='observed_fixed'
        extending=enemy['mode']=='fever' and not events and enemy.get('phase')!='chain' and fixed and any(c not in '.#' for row in enemy['field'] for c in row)
        if extending:
            # Current seed plus its regular successor can return a small shot
            # without losing the seed's growth. Geometry pressure is separate.
            successor=self.scoring.chain(enemy['character'],[dict(groups=[4],colors=1)]*min(15,level+1),'fever')
            told['enemy_reply_nuisance']=(sum(seed)+sum(successor))//rate
            budget=0
            profiles,diagnostic=self.seed_defenses.observe(enemy,analyze,budget)
            profiles=deepcopy(profiles)
            for profile in profiles:
                if profile.get('regular_after_drop'):
                    follow_level=min(15,profile.get('counter_chain',level)+1+(2 if profile.get('counter_all_clear') else 0))
                    follow=self.scoring.chain(enemy['character'],[dict(groups=[4],colors=1)]*follow_level,'fever')
                    profile['reply_nuisance']=(profile['counter_points']+sum(follow))//rate
            told.update(enemy_extending=True,enemy_seed_defense=profiles,enemy_seed_geometry=diagnostic)
        return told

    def _press(self, request, own, enemy, rate):
        """Whether this seed is fired at once instead of built on (seed_search.cpp), and why.

        The rule is to build. It is fired at once when what it sends at its level lands on the
        opponent's normal board (they have no chain running, and neither this side's own nuisance
        nor a chain of theirs takes it up), so that they get no time to build; and when both
        sides are in Fever and the opponent has nuisance held for their normal board. A normal
        board that already has as much pending as fills it gains nothing from a little more:
        there the seed is built on.
        """
        if enemy['mode'] == 'fever':
            enemy = self.enemy_analysis['enemy'] if self.enemy_analysis else enemy
            return 'opponent_in_fever_holds_nuisance' if enemy['normal_confirmed'] + enemy['normal_unconfirmed'] else None
        if request.get('enemy_chain'):
            return None
        rows = enemy['field']
        fills = 6 * max(0, 12 - max(sum(row[x] != '.' for row in rows) for x in (2, 3)))
        if enemy['confirmed'] + enemy['unconfirmed'] >= fills:
            return None
        seed = sum(self.scoring.chain(own['character'], [dict(groups=[4], colors=1)] * own['seed_chain'], 'fever'))
        mine = own['confirmed'] + own['unconfirmed'] + own['normal_confirmed'] + own['normal_unconfirmed']
        lands = seed // rate - mine - self._board_hold(enemy['character'], enemy['field']) // rate
        return 'lands_on_their_normal_board' if lands > 0 else None

    def _arrival(self, request, own, enemy):
        """What the decision took for the timing of nuisance, to be checked against what then happens.

        `chain_end_in`: frames until the observed opponent chain ends and what it sent is confirmed
        (None with no chain observed). `piece_frames`: what one piece of this side is taken to
        last (the measured pace, or the model's fastest piece). `pieces`: the pieces that can
        still fire before the drop, as the normal-board search counts them.
        """
        timing = ChainTiming.for_mode(own['mode'])
        piece = max(timing.placement_frames + timing.spawn_frames, self.pace or 0)
        end = next((event['frame'] for event in self._enemy_events(request, enemy) if event['type'] == 'end'), None)
        pieces = 1 if own['confirmed'] else None if end is None else 1 + end // piece
        return dict(chain_end_in=end, piece_frames=piece, measured_pace=self.pace, pieces=pieces)

    def _quiet_carry_limit(self, own):
        """Nuisance the stored normal board takes on return without harm, on every column subset."""
        for count in range(self.policy.get('fever_end', {}).get('harmless_carry', 5), 0, -1):
            if all(not losing for _, losing in outcomes(own['stored_field'], count)):
                return count
        return 0

    def _normal(self, request, own, enemy, rate):
        options = self._normal_options(request, own)
        board_dead = self.native.ask(dict(op='validate', field=own['field']))['dead']
        placements = [] if board_dead else self.native.ask(dict(op='placements',
            field=own['field'], piece=own['queue'][0]))['placements']
        if not placements:
            pose = request.get('active_placement')
            if not isinstance(pose, dict) or set(pose) != {'x', 'r'}:
                raise ValueError('blocked normal spawn needs its observed active placement')
            c = self.native.ask(dict(op='closing_transition', field=own['field'], piece=own['queue'][0], **pose))
            from .finish import placement_frames
            points = self.scoring.chain(own['character'], c['links'])
            return dict(x=c['x'], r=c['r'], shape=own['queue'][0][0],
                reason='no_rescue_fast_finish' if c['dead'] else 'observed_current_pose_drop',
                fire=bool(points), chain=len(points), next_chain=len(points), next_score=sum(points),
                next_field=c['field'], link_points=points, next_all_clear=c['all_clear'],
                selected_move_loses=c['dead'], finish_proof='blocked_spawn_observed_current_pose',
                finish_candidates=[dict(x=c['x'],r=c['r'],estimated_frames=placement_frames(c),
                    contact_height=c['contact_height'],pivot_height=c['pivot_height'],
                    split_distances=c['split_distances'],finish_after_drops=0,
                    link_points=points,all_clear=c['all_clear'])])
        def build():
            result = self._solo_build(own, options)
            return result
        answer = self._tactics(request, own, enemy, rate, build)
        if answer is not None:
            return answer
        finish = fast_finish(self.native, own)
        if finish is not None:
            choice = finish['candidate']
            points = self.scoring.chain(own['character'], choice['links'])
            for candidate in finish['candidates']:
                candidate['link_points'] = self.scoring.chain(own['character'], candidate.pop('links'))
            return dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0],
                reason='no_rescue_fast_finish', fire=bool(points), chain=len(points),
                next_chain=len(points), next_score=sum(points), next_field=None,
                link_points=points, next_all_clear=choice['all_clear'], selected_move_loses=True,
                finish_candidates=finish['candidates'], finish_proof=finish['proof'],
                finish_timing_status=finish['timing_status'])
        if own['garbage_phase'] is None and (own['confirmed'] + own['unconfirmed'] or request.get('enemy_chain') is not None):
            if request.get('enemy_chain') is not None:
                chain = request['enemy_chain']
                if chain['mode_generation'] != enemy['mode_generation'] or chain['seed_id'] != enemy['seed_id']:
                    raise ValueError('enemy prediction belongs to another mode or seed')
            result = uncertain_move(self.native, self.scoring, own, rate,
                enemy_events=self._enemy_events(request, enemy), enemy=enemy, margin=self.margin)['choice']
            return dict(x=result['x'], r=result['r'], shape=own['queue'][0][0],
                reason='unknown_nuisance_one_move_then_reobserve', fire=bool(result['chain']),
                chain=result['chain'], next_chain=result['chain'], next_score=sum(result['link_points']),
                next_field=result['field'] if result['post_drop_field_known'] else None,
                link_points=result['link_points'], next_all_clear=result['all_clear'],
                nuisance_uncertainty=result, selected_move_loses=result['dead'])
        scheduled = self._enemy_events(request, enemy)
        if own['confirmed'] + own['unconfirmed'] or any(
                e['type'] == 'link' and e.get('points', 0) > 0 for e in scheduled):
            try:
                forecast = self.garbage_search.search(own['character'], own['field'], own['queue'],
                    own['confirmed'], own['unconfirmed'], own['remainder'], rate, own['garbage_phase'],
                    min(1000, options.get('beam_width', 80)), enemy_events=scheduled,
                    enemy=enemy,
                    enemy_remainder=enemy['remainder'], margin=self.margin,
                    budget_ms=0)
            except ValueError as error:
                if str(error) != 'no placement survives observed confirmed garbage':
                    raise
                # A failed rescue is a game state, not an engine/session failure.
                result = uncertain_move(self.native, self.scoring, own, rate,
                    enemy_events=scheduled, enemy=enemy, margin=self.margin)
                first = result['choice']
                return dict(x=first['x'], r=first['r'], shape=own['queue'][0][0],
                    reason='no_surviving_garbage_reply', fire=bool(first['chain']),
                    chain=first['chain'], next_chain=first['chain'], next_score=sum(first['link_points']),
                    link_points=first['link_points'], next_field=None, next_all_clear=first['all_clear'],
                    selected_move_loses=first['dead'], nuisance_uncertainty=result)
            return GarbageSearch.reply(forecast, own['queue'][0][0])
        placements = self.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
        safe = [p for p in placements if not p['dead']]
        if not safe:
            if not placements:
                raise ValueError('no conservative reachable normal placement')
            from .finish import placement_frames
            choice = min(placements, key=placement_frames)
            points = self.scoring.chain(own['character'], choice['links'])
            return dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0],
                reason='no_rescue_fast_finish', fire=bool(points), chain=len(points),
                next_chain=len(points), next_score=sum(points), next_field=choice['field'],
                link_points=points, next_all_clear=choice['all_clear'], selected_move_loses=True,
                finish_proof='every_current_placement_dies_after_resolution',
                finish_candidates=[dict(x=p['x'], r=p['r'], estimated_frames=placement_frames(p),
                    contact_height=p['contact_height'], pivot_height=p['pivot_height'],
                    split_distances=p['split_distances'], finish_after_drops=0,
                    link_points=self.scoring.chain(own['character'],p['links']),
                    all_clear=p['all_clear']) for p in placements])
        result = self._solo_build(own, options)
        choice = next((p for p in safe if (p['x'], p['r']) == (result['x'], result['r'])), safe[0])
        points = self.scoring.chain(own['character'], choice['links'])
        return dict(x=choice['x'], r=choice['r'], shape=own['queue'][0][0], reason='normal_build_or_fire',
                    fire=bool(points), chain=len(points), next_chain=len(points), next_score=sum(points),
                    next_field=choice['field'], link_points=points, next_all_clear=choice['all_clear'],
                    normal_search_reused=False, searched_visible=len(own['queue']))

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
        if op not in ('think', 'prepare', 'prepare_normal', 'prepare_observed', 'recover_placement'):
            raise ValueError('unsupported operation')
        integer(request['gauge_gain_on_offset'], 'gauge_gain_on_offset', 0, 7)
        if not isinstance(request.get('match_id'), str) or not request['match_id']:
            raise ValueError('match_id required')
        coherent(request)
        rate = integer(request['target_point'], 'target_point', 1, 100000)
        self.margin = self.margin_forecast.observe(request)
        policy = request['clock_policy']
        if not isinstance(policy, dict) or type(policy.get('count_chain_frames')) is not bool:
            raise ValueError('explicit clock_policy.count_chain_frames required')
        limit = clock_limit(policy)
        own, enemy = self.mode_side(request['self'], limit), self.mode_side(request['enemy'], limit)
        if self.build_match != request['match_id']:
            self.enemy_seed_predictions.clear()
            self.seed_defenses.cache.clear()
            self.enemy_analysis = None
        self.build_match = request['match_id']
        incoming = request.get('enemy_analysis_state')
        if incoming and incoming['seed'][0] == request['match_id'] and (
                self.enemy_analysis is None or incoming['observed_frame'] > self.enemy_analysis['observed_frame']):
            self.enemy_analysis = deepcopy(incoming)
        self._observe_enemy_fever(request, enemy)
        transferred = request.get('prepared_state')
        if transferred and transferred['match_id'] == request['match_id']:
            self.prepared = transferred['prepared']
            self.normal_build_cache = transferred['normal_build_cache']
        self.normal_build_reused = False
        self.normal_build_used = False
        if op in ('prepare', 'prepare_normal', 'prepare_observed'):
            reply = self._prepare(request, own, enemy, rate, policy, op == 'prepare_observed')
            if reply.get('prepared'):
                reply['prepared_state'] = dict(match_id=request['match_id'],
                    prepared=self.prepared, normal_build_cache=self.normal_build_cache)
            reply['enemy_analysis_state'] = deepcopy(self.enemy_analysis)
            return reply
        prepared, self.prepared = self.prepared, None       # kept for one decision only
        if op == 'think':
            self._observe_pace(request, own)
        reply = self._think(request, own, enemy, rate, policy, op, prepared)
        if op == 'think':
            self.pace_state['popped'] = bool(reply.get('fire'))
        reply['enemy_analysis_state'] = deepcopy(self.enemy_analysis)
        return reply

    def _observe_pace(self, request, own):
        """Frames this side takes per piece in its present mode: the upper quartile of its last
        twelve pieces there, measured between two decisions for consecutive pieces with no chain
        of its own between them. The searches count the pieces left before a deadline with it
        instead of the model's fastest piece; the upper quartile, so that the count is not
        optimistic. Kept apart by mode (a Fever piece is quicker). None until three are measured.
        """
        last, key = self.pace_state, (request['match_id'], own['mode'])
        if last.get('key', (None,))[0] != request['match_id']:
            self.pace_samples = {}
        elif last['key'] == key and own['piece_id'] == last['piece'] + 1 and not last['popped']:
            taken = request['frame'] - last['frame']
            if 0 < taken <= 300:
                self.pace_samples[own['mode']] = (self.pace_samples.get(own['mode'], []) + [taken])[-12:]
        self.pace_state = dict(key=key, piece=own['piece_id'], frame=request['frame'], popped=False)
        samples = sorted(self.pace_samples.get(own['mode'], []))
        self.pace = samples[int(.75 * (len(samples) - 1))] if len(samples) >= 3 else None

    def _think(self, request, own, enemy, rate, policy, op, prepared=None):
        started = time.monotonic()
        budget = request.get('decision_budget_ms')
        if budget is not None:
            integer(budget, 'decision_budget_ms', 10, 1000)
        self.planning_deadline = None  # CPU budgets are compatibility input only; never truncate search
        if own.get('awaiting_seed') or (
            own['mode'] == 'normal' and own['gauge'] == self.mode_rules['gauge_max']):
            return dict(action='wait', reason='await_observed_mode_or_seed', decision_identity=identity(request))
        if (op == 'think' and prepared is not None and (
                    prepared[0] == self._signature(request, own) or
                    ((not prepared[2].get('fire') or own['mode'] == 'fever')
                     and len(prepared) > 3 and request.get('enemy_chain')
                     and self._attack_rate_stable(request, enemy)
                     and prepared[3] == self._signature(request, own, final_exchange=True)))
                and self._clock_allows(own, prepared[1]) and self._stacking_still_fits(own, prepared[2])
                and self._prepared_delivery_stable(request, own, enemy, prepared[2])):
            # Decided while the piece before fell, on this very side.
            reply = deepcopy(prepared[2])
            reply.update(decision_identity=identity(request), search_ms=0.0, search_reused=True,
                         searched_visible=2)
            reply['seed_search_reused' if own['mode'] == 'fever' else 'normal_search_reused'] = True
            return reply
        if op == 'recover_placement':
            allowed = request.get('reachable_placements')
            if not isinstance(allowed, list) or not 1 <= len(allowed) <= 24:
                raise ValueError('recovery requires observed reachable placements')
            for move in allowed:
                if not isinstance(move, dict) or set(move) != {'x', 'r'} or move['r'] not in ('U','R','D','L'):
                    raise ValueError('invalid reachable placement')
                integer(move['x'], 'reachable x', 0, 5)
            waiting = None if own['mode'] == 'fever' else self._tactics(request, own, enemy, rate, allowed=allowed)
            if own['mode'] == 'fever':
                self._enemy_fever(enemy,self._enemy_events(request,enemy),rate,analyze=True)
                options = request.get('seed_options', {})
                self.seed_solver.validate_options(options)
                options, strategy_reason = self._seed_options(request, own, enemy)
                result = self.seed_solver.solve(own, rate, policy['count_chain_frames'],
                    options,
                    match_id=request['match_id'], allowed=allowed,
                    enemy_events=self._enemy_events(request, enemy), enemy=enemy,
                    maximum_frames=clock_limit(policy), margin=self.margin,
                    quiet_carry_limit=self._quiet_carry_limit(own),
                    press=self._press(request, own, enemy, rate), pace=self.pace,
                    fever=self._enemy_fever(enemy, self._enemy_events(request, enemy), rate))
            else:
                result = uncertain_move(self.native, self.scoring, own, rate,
                    allowed_placements={(m['x'], m['r']) for m in allowed},
                    enemy_events=self._enemy_events(request, enemy), enemy=enemy, margin=self.margin)
            first = result['choice']; points = first['link_points']
            reply = dict(x=first['x'], r=first['r'], shape=own['queue'][0][0],
                reason='observed_reachable_recovery', decision_dependencies=['self'],
                fire=bool(points), chain=first['chain'], next_chain=first['chain'], next_score=sum(points),
                next_field=first['field'] if first['post_drop_field_known'] else None,
                link_points=points, next_all_clear=first['all_clear'], recovery_forecast=result,
                selected_move_loses=first['dead'], searched_visible=result.get('searched_visible', 1),
                input_required_frames=first['fire_at']+request.get('seed_options', {}).get('safety_frames', 8)
                    if own['mode']=='fever' else 0)
            if own['mode'] == 'fever':
                reply['seed_forecast'] = result
            if waiting is not None:
                # The same search as an ordinary decision, over the reachable placements only.
                reply = dict(waiting, recovery=True)
            if own['mode'] == 'normal':
                reply = report_colors(self.native, own, reply)
        elif own['mode'] == 'fever':
            self._enemy_fever(enemy,self._enemy_events(request,enemy),rate,analyze=True)
            options, strategy_reason = self._seed_options(request, own, enemy)
            result = self.seed_solver.solve(
                own, rate, policy['count_chain_frames'], options, match_id=request['match_id'],
                enemy_events=self._enemy_events(request, enemy), enemy=enemy,
                maximum_frames=clock_limit(policy), margin=self.margin,
                quiet_carry_limit=self._quiet_carry_limit(own),
                    press=self._press(request, own, enemy, rate), pace=self.pace,
                    fever=self._enemy_fever(enemy, self._enemy_events(request, enemy), rate))
            first = result['choice']
            points = first['link_points']
            safety = request.get('seed_options', {}).get('safety_frames', 8)
            reply = dict(x=first['x'], r=first['r'], shape=own['queue'][0][0], reason='fever_seed_search',
                fire=bool(points), chain=first['chain'], next_chain=first['chain'], next_score=sum(points),
                next_field=first['field'] if first.get('post_drop_field_known', True) else None,
                link_points=points, next_all_clear=first['all_clear'],
                seed_forecast=result, replaces_seed_on_clear=bool(points),
                seed_strategy_reason=strategy_reason, seed_search_reused=False,
                searched_visible=result.get('searched_visible', len(own['queue'])),
                input_required_frames=first['fire_at'] + safety,
                selected_move_loses=first['dead'])
            if result.get('intentional_seed_failure'):
                reply.update(reason='fever_intentional_failure_hold_nuisance', intentional_seed_failure=True)
            # Both objectives depend on our clock/seed, not enemy soft drops
            # or a speculative one-piece attack estimate.
            reply['decision_dependencies'] = ['self', 'enemy'] if request.get('enemy_chain') else ['self']
        else:
            reply = self._normal(request, own, enemy, rate)
            target_options = {**self.policy['solo_options'], **request.get('solo_options', {})}
            reply['normal_fire_policy'] = (('second_target_or_full' if request.get('second_target_chain') else 'fill_then_fire')
                                          if self._after_opening(own, target_options) else 'initial_target')
            reply['normal_build_target_chain'] = self.last_normal_options.get('build_chain', self.last_normal_options['trigger'])
            reply['normal_fire_required_chain'] = self.last_normal_options['trigger']
            if self.normal_build_cache and self.normal_build_used:
                built = self.normal_build_cache[2]
                reply['normal_build_completed_depth'] = built.get('search_completed_depth')
                reply['normal_build_virtual_depths'] = built.get('search_virtual_depths')
            if self.normal_build_reused:
                reply.update(normal_build_search_reused=True, normal_build_searched_visible=len(self.normal_build_cache[1]))
            reply = report_colors(self.native, own, reply)
            gauge = offset_gauge(reply['link_points'], own['confirmed'] + own['unconfirmed'],
                                 own['remainder'], rate, own['gauge'], request['gauge_gain_on_offset'])
            reply.update(gauge_forecast=gauge, entry_pending_after_chain=gauge['gauge_after'] == 7)
            # A reply that says nothing of what it rests on used only this side, unless an enemy
            # chain was given; the nuisance search (garbage_search) reads the opponent's packets.
            if not request.get('enemy_chain') and 'nuisance_forecast' not in reply:
                reply.setdefault('decision_dependencies', ['self'])
        if reply['shape'] == '0':
            # Every policy branch, including unknown nuisance and seed search,
            # uses the native absolute big-puyo color encoded as U/R/D/L.
            reply['color'] = 'RYGB'['URDL'.index(reply['r'])]
        reply.update(action='place', protocol_version=3, rule='fever_battle', mode=own['mode'],
                     decision_identity=identity(request), model_status='prototype_unverified_on_local_steam',
                     provenance=self.scoring.provenance, search_ms=(time.monotonic() - started) * 1000)
        reply['mode_timing_status'] = ('normal_calibrated_input_estimated' if own['mode'] == 'normal'
                                       else ChainTiming.for_mode('fever').effective_status)
        reply['margin_forecast'] = self.margin
        reply['arrival'] = self._arrival(request, own, enemy)
        target = self._enemy_fever(enemy, self._enemy_events(request, enemy), rate) or {}
        guard = disruption.contract(request, reply, target)
        if target:
            forecast = reply.get('tactics_forecast') or reply.get('seed_forecast') or {}
            reply['fever_disruption'] = dict({k:v for k,v in target.items() if k!='enemy_seed_defense'},
                kind=forecast.get('choice', {}).get('disruption_kind', 'none'))
        if guard:
            reply['disruption_timing'] = guard
        if reply['shape'] == '0':
            reply['color'] = 'RYGB'['URDL'.index(reply['r'])]
        return reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT / 'bin/fever_battle/fever_battle.exe')
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
