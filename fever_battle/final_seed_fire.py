"""Fire a main below its target when the opponent's Fever is on its last seed and cannot answer it.

Ends our chain with theirs: the shot is placed so that its last link lands at their chain end (or within
the disruption window after it), instead of waiting for the build target. It is taken only when
 - the opponent is in Fever with a chain running and at most `max_seeds_after` seeds left to fire after it,
 - our chain offsets everything still on its way to us and sends more (so nothing of theirs lands),
 - at least `min_remaining` nuisance stay on them even if they then do the best they can: the most the rest of
   their Fever can score (the seeds still to come, each one level up, or the extension the seed search
   expects) and then the main of the normal board they go back to answer first, and only what is not offset counts.
Estimates of boards and clocks, not a proof (doc/FEVER_MODE_ENGINE.md).
"""
from .timing import ChainTiming
from .chain_to_us import chain_to_us

WINDOW = 26         # fever_battle/disruption.h


class FinalSeedFire:
    def __init__(self, native, scoring):
        self.native, self.scoring = native, scoring
        self.status = None

    def choose(self, request, own, enemy, baseline, config, margin, events, hold, fever, rate, pace=None,
               after_opening=False):
        """The reply to fire now, or None. `status` says why not (None while the opponent is not in Fever)."""
        self.status = None
        if enemy['mode'] != 'fever' or not config.get('enabled', False):
            return None
        why = ('not_after_opening' if not after_opening else 'builder_or_tactics_fires' if baseline.get('fire')
               else 'own_side_not_normal' if own['mode'] != 'normal' or own['gauge'] >= 7
               else 'rate_change' if any(margin.get(k) for k in ('rate_events', 'enemy_rate_events'))
               else 'no_enemy_chain' if not request.get('enemy_chain') or hold is None
               else 'no_chain_end_time' if fever is None or 'their_end' not in fever
               or not any(e['type'] == 'end' for e in events) else None)
        if why:
            self.status = dict(why=why)
            return None
        seeds, fever_points, board_points = hold
        end = fever['their_end']
        if seeds > config['max_seeds_after'] or end < 0:
            self.status = dict(why='seed_left_after_chain' if seeds else 'chain_end_passed', seeds=seeds, their_end=end)
            return None
        timing = ChainTiming.for_mode('normal')
        piece = max(timing.placement_frames + timing.spawn_frames, pace or 0)
        window = fever.get('disrupt_window', WINDOW)
        # What waits for us already, and what their running chain still sends at us once their own pending is offset.
        incoming = (own['confirmed'] + own['unconfirmed'] + chain_to_us(events, enemy, rate)
                    + request.get('observation', {}).get('in_flight', {}).get('self', {}).get('incoming_in_flight', 0))
        # Their best answer, one after the other: what is left of their Fever, then the main of the board they return to.
        fever_reply = max(fever_points // rate, fever.get('enemy_reply_nuisance', 0) if seeds else 0)
        reply = fever_reply + board_points // rate
        placements = self.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
        best, status = None, dict(why='no_placement_with_min_chain', their_end=end, window=window, incoming=incoming,
                                  fever_reply=fever_reply, board_reply=board_points // rate, reply=reply, longest=0, window_range=[end + window - piece + 1, end + window])
        for p in placements:
            status['longest'] = max(status['longest'], 0 if p['dead'] else len(p['links']))
            if p['dead'] or len(p['links']) < config['min_chain']:
                continue
            points = self.scoring.chain(own['character'], p['links'])
            start = timing.lock_frames(timing.split_extra_frames[max(p['split_distances'], default=0)], pace)                 + timing.first_link_frames
            finish = timing.timeline(points, p['fall_distances'], p.get('fall_features'), start_offset=start)['end_frame']
            # Last piece whose shot still ends inside the window: waiting one more piece misses it.
            if not end + window - piece < finish <= end + window:
                status.update(why='outside_window', chain=len(points), finish=finish)
                continue
            offset, remainder = 0, own['remainder']
            for score in points:
                amount, remainder = divmod(score + remainder, rate)
                offset += max(1, amount) if incoming else amount
            # A shot that sends anything has offset all of what is still on its way to us.
            sent = offset - incoming
            if sent <= 0 or sent - reply < config['min_remaining']:
                status.update(why='remaining_short', chain=len(points), finish=finish, sent=sent,
                              remaining=sent - reply, need=config['min_remaining'])
                continue
            if best is None or (sent, len(points)) > best[0]:
                best = (sent, len(points)), p, points, finish, dict(
                    sent=sent, incoming=incoming, reply=reply, their_end=end, window=window,
                    end=finish, earliest_end=end + window - piece + 1, latest_end=end + window,
                    remaining=sent - reply, fever_reply=fever_reply, board_reply=board_points // rate)
        if best is None:
            self.status = status
            return None
        _, p, points, _, forecast = best
        self.status = dict(why='fire', **forecast)
        return dict(x=p['x'], r=p['r'], shape=own['queue'][0][0], reason='normal_final_seed_fire',
            fire=True, chain=len(points), next_chain=len(points), next_score=sum(points),
            next_field=p['field'], link_points=points, next_all_clear=p['all_clear'],
            decision_dependencies=['self', 'enemy'], searched_visible=len(own['queue']),
            normal_search_reused=False, normal_decision_status='build', final_seed_fire=forecast)
