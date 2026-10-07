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
from .mode_tactics import QUICK_FRAMES, offset_gauge
from .normal_colors import report as report_colors
from .uncertainty import choose as uncertain_move
from .finish import choose as fast_finish
from . import tactics
from .uncertainty import outcomes
from .margin import MarginForecast


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
        self.margin_forecast = MarginForecast()
        self.margin = {}
        self.normal_build_cache = None
        self.normal_build_reused = False
        self.normal_build_used = False
        self.build_match = None

    def mode_side(self, side, max_time_frames=None):
        if side['mode'] not in ('normal', 'fever'):
            raise ValueError('unsupported mode; transitions cannot request placements')
        integer(side['gauge'], 'gauge', 0, self.mode_rules['gauge_max'])
        integer(side['mode_generation'], 'mode_generation')
        integer(side['seed_id'], 'seed_id')
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
        result = self.native.ask(dict(op='resolve', field=rows))
        points = self.scoring.chain(character, result['links'], mode)
        clock = ChainTiming.for_mode(mode)
        return dict(points=points, field=result['field'], mode_timing_status=clock.effective_status,
                    **clock.timeline(points, result['fall_distances'], result['fall_features']))

    def _enemy_events(self, request, enemy):
        chain = request.get('enemy_chain')
        if chain is None:
            return []
        if chain['mode_generation'] != enemy['mode_generation'] or chain['seed_id'] != enemy['seed_id']:
            raise ValueError('enemy prediction belongs to another mode or seed')
        prediction = self._prediction(enemy['character'], chain['trigger_field'], enemy['mode'])
        if not prediction['points'] or ('first_link_points' in chain and chain['first_link_points'] != prediction['points'][0]):
            return []  # Drawn board/score did not prove this chain; keep arrival unknown.
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
        if own['moves_since_chain'] is not None:
            options['moves'] = own['moves_since_chain']
        else:
            options.pop('patience', None)  # no history-based impatience threshold
        options.setdefault('beam_width', 50)
        options.setdefault('beam_depth', 8)
        build = self.policy.get('normal_build', {})
        if (build.get('objective') == 'fever_aim' and request['gauge_gain_on_offset'] > 0
                and own['gauge'] < self.mode_rules['gauge_max']):
            # Fever aim: build what offsets link by link, not one long chain.
            # The builder ranks by its evaluation and fires nothing by length.
            aim = build['fever_aim']
            options.update(aim['solo_options'], aim=True, weight_set=aim['weight_set'],
                           stock_want=self.mode_rules['gauge_max'] - own['gauge'])
        return options

    def _solo_build(self, own, options):
        self.normal_build_used = True
        key = json.dumps(dict(match=self.build_match, character=own['character'],
            field=own['field'], piece_id=own['piece_id'], dropset_index=own['dropset_index'],
            mode_generation=own['mode_generation'], seed_id=own['seed_id'], options=options), sort_keys=True)
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
            plain_pairs=True, include_next=True, **build), **(
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

    def _signature(self, request, own):
        """Everything a decision for this side rests on, for the first two visible pieces."""
        side = {key: value for key, value in own.items() if key not in self.VOLATILE}
        side['queue'] = own['queue'][:2]
        options = request.get('solo_options', {})
        if own['mode'] == 'fever':
            for key in self.FEVER_UNREAD:
                side.pop(key, None)
            options = self._seed_options(request, own, None)[0]
        return json.dumps(dict(match_id=request['match_id'], target_point=request['target_point'],
            gauge_gain_on_offset=request['gauge_gain_on_offset'], clock_policy=request['clock_policy'],
            options=options, side=side,
            enemy_prediction=request.get('enemy_chain'),
            enemy_state=request['enemy'] if request.get('enemy_chain') else None), sort_keys=True)

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

        While an enemy chain is observed, or a rate change is near, what the
        opponent delivers by the time the piece appears cannot be told. The plan
        is then `speculative`: where the piece goes if nothing changes, for keys
        to be held towards before it appears. It is not kept: the `think` at the
        spawn decides on what is observed then, as the fork's origin decides
        every piece, and the keys carry on only if it names the same placement.
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
        if not speculative:
            self.prepared = (self._signature(ahead, future), future['remaining_frames'], reply)
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
                searched_visible=len(future['queue']), search_ms=(time.monotonic()-started)*1000,
                controller=False, plan=plan, reason='speculative_plan_decided_again_on_spawn')
        return dict(prepared=True, searched_visible=len(future['queue']),
            search_ms=(time.monotonic()-started)*1000, controller=False, plan=plan)

    def _seed_options(self, request, own, enemy):
        options = request.get('seed_options', {})
        self.seed_solver.validate_options(options)
        # One measure ranks every line (seed_search.cpp); there is no strategy to choose.
        return dict(options), 'expected_points_by_the_end_of_this_fever'

    def _tactics(self, request, own, enemy, rate, build=None, allowed=None):
        """The single search's reply to a threat on the normal board, or None to leave it to the rest."""
        policy = self.policy['normal_tactics']
        events = self._enemy_events(request, enemy)
        threat = own['confirmed'] + own['unconfirmed'] or events
        # Offsets earn no gauge: the nuisance search of the gauge-free battle answers.
        # Without a threat only a recovery (allowed) has anything to decide here.
        if (request['gauge_gain_on_offset'] <= 0 or own['gauge'] >= self.mode_rules['gauge_max']
                or not (threat or allowed is not None)):
            return None
        builder = None
        if build is not None:
            try:
                builder = build()
            except ValueError:
                builder = None      # nothing the builder plays survives; the search decides alone
        reply = tactics.choose(self.native, self.scoring, own, rate, request['gauge_gain_on_offset'],
            policy, events, enemy, self.margin, allowed, builder)
        # A position every placement loses belongs to the finish probe below.
        return None if reply is None or reply['selected_move_loses'] else reply

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
            return result['x'], result['r']
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
        if own['confirmed'] + own['unconfirmed'] or scheduled:
            forecast = self.garbage_search.search(own['character'], own['field'], own['queue'],
                own['confirmed'], own['unconfirmed'], own['remainder'], rate, own['garbage_phase'],
                min(1000, options.get('beam_width', 80)), enemy_events=scheduled,
                enemy_confirmed=enemy['confirmed'] + (enemy['normal_confirmed'] if enemy['mode'] == 'fever' else 0),
                enemy_unconfirmed=enemy['unconfirmed'] + (enemy['normal_unconfirmed'] if enemy['mode'] == 'fever' else 0),
                enemy_remainder=enemy['remainder'], margin=self.margin)
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
        self.build_match = request['match_id']
        self.normal_build_reused = False
        self.normal_build_used = False
        if op in ('prepare', 'prepare_normal', 'prepare_observed'):
            return self._prepare(request, own, enemy, rate, policy, op == 'prepare_observed')
        prepared, self.prepared = self.prepared, None       # kept for one decision only
        return self._think(request, own, enemy, rate, policy, op, prepared)

    def _think(self, request, own, enemy, rate, policy, op, prepared=None):
        started = time.monotonic()
        if own.get('awaiting_seed') or (
            own['mode'] == 'normal' and own['gauge'] == self.mode_rules['gauge_max']):
            return dict(action='wait', reason='await_observed_mode_or_seed', decision_identity=identity(request))
        if (op == 'think' and prepared is not None and not self.margin.get('rate_events') and
                not self.margin.get('enemy_rate_events') and prepared[0] == self._signature(request, own)
                and self._clock_allows(own, prepared[1]) and self._stacking_still_fits(own, prepared[2])):
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
                options = request.get('seed_options', {})
                self.seed_solver.validate_options(options)
                options, strategy_reason = self._seed_options(request, own, enemy)
                result = self.seed_solver.solve(own, rate, policy['count_chain_frames'],
                    options,
                    match_id=request['match_id'], allowed=allowed,
                    enemy_events=self._enemy_events(request, enemy), enemy=enemy,
                    maximum_frames=clock_limit(policy), margin=self.margin,
                    quiet_carry_limit=self._quiet_carry_limit(own))
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
            if waiting is not None:
                # The same search as an ordinary decision, over the reachable placements only.
                reply = dict(waiting, recovery=True)
            if own['mode'] == 'normal':
                reply = report_colors(self.native, own, reply)
        elif own['mode'] == 'fever':
            options, strategy_reason = self._seed_options(request, own, enemy)
            result = self.seed_solver.solve(
                own, rate, policy['count_chain_frames'], options, match_id=request['match_id'],
                enemy_events=self._enemy_events(request, enemy), enemy=enemy,
                maximum_frames=clock_limit(policy), margin=self.margin,
                quiet_carry_limit=self._quiet_carry_limit(own))
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
