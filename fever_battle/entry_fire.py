"""Start a chain after the opponent's Fever entry, by letting the piece fall on its own first.

Steam copies the receiver's tray at the sender's first link (doc/FEVER_BATTLE_RULES.md): a chain whose first
link starts before the opponent's Fever entry goes to the normal tray whatever it does later. When their
chain has made the entry certain, the piece is held (no DOWN) so that the first link begins at the entry or
after it, and the packet lands in the Fever tray: a fire the other policies chose is retimed that way, and
where nothing was chosen a side attack that spends none of the main chain is sent as a jab.

`hold_frames` / `hold_down_until_frame` tell the bridge how long to keep DOWN up. How long a piece can be
held is the natural fall to its resting row and the lock delay after it (fever-simulator revision 21:
10/256 rows a frame, 32 frames); not checked against the live game.
"""
from .timing import ChainTiming
from .chain_to_us import chain_to_us

WINDOW = 26         # fever_battle/disruption.h


class EntryFire:
    def __init__(self, native, scoring):
        self.native, self.scoring = native, scoring
        self.status = None
        self.late = 0

    def choose(self, request, own, enemy, baseline, config, margin, events, fever, rate, pace=None,
               after_opening=False, chain_returns=False):
        """The reply to play now (with its hold), or None. `status` says why not (None unless they are entering)."""
        self.status = None
        entering = (enemy['mode'] == 'normal' and fever is not None and fever.get('enemy_fever_at', -1) > 0
                    and enemy['gauge'] >= 7)
        if not entering or not config.get('enabled', False):
            return None
        if chain_returns:
            # Known when their chain started: it comes back at us, so there is no jab to weigh, early or late.
            self.status = dict(why='chain_returns_nuisance')
            return None
        why = ('own_side_not_normal' if own['mode'] != 'normal' or own['gauge'] >= 7
               else 'rate_change' if any(margin.get(k) for k in ('rate_events', 'enemy_rate_events'))
               else 'no_enemy_chain' if not request.get('enemy_chain') or not any(e['type'] == 'end' for e in events)
               else 'baseline_is_not_a_fire_or_jab_off' if not baseline.get('fire') and not config.get('jab', True)
               else None)
        if why:
            self.status = dict(why=why)
            return None
        entry = fever['enemy_fever_at']
        self.late = config['max_late_frames']
        window = fever.get('disrupt_window', WINDOW)
        timing = ChainTiming.for_mode('normal')
        incoming = own['confirmed'] + own['unconfirmed'] + chain_to_us(events, enemy, rate)
        # Attacks already in flight at us are not in the tray yet (observation.in_flight).
        flying = request.get('observation', {}).get('in_flight', {}).get('self', {}).get('incoming_in_flight', 0)
        if incoming > 0 or flying > 0:
            # Their chain (after their own pending takes its share) or what waits for us comes back as a notice:
            # the piece is not held for a jab or a retimed fire, whatever the shot could still send over it.
            self.status = dict(why='nuisance_comes_back', incoming=incoming, in_flight=flying, entry=entry)
            return None
        placements = self.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
        held = self.native.ask(dict(op='holding', field=own['field']))['longest']
        status = dict(why='no_fire_placement', entry=entry, window=window, incoming=incoming, held=held)
        plans = []
        for p in placements:
            if p['dead'] or not p['links']:
                continue
            points = self.scoring.chain(own['character'], p['links'])
            lock = timing.lock_frames(timing.split_extra_frames[max(p['split_distances'], default=0)], pace)
            first = lock + timing.first_link_frames
            finish = timing.timeline(points, p['fall_distances'], p.get('fall_features'), start_offset=first)['end_frame']
            # DOWN may go down once the fastest lock after it still puts the first link at the entry or later; a
            # slower lock only makes it later (the 2026-10-25 log: the model said 44 frames from DOWN to lock, 10 were).
            hold = max(0, entry + config['margin_frames'] - timing.first_link_frames - config['fast_lock_frames'])
            fall = max(0, config['spawn_height'] - p['contact_height']) * config['fall_frames_per_row']
            room = fall + config['lock_limit_frames'] - config['safety_frames'] - config['fast_lock_frames']
            offset, remainder = 0, own['remainder']
            for score in points:
                amount, remainder = divmod(score + remainder, rate)
                offset += max(1, amount) if incoming else amount
            plans.append(dict(p=p, points=points, hold=hold, room=int(room), finish=finish + hold,
                              first=entry + config['margin_frames'] if hold else first,
                              sent=offset - incoming, chosen=(p['x'], p['r']) == (baseline.get('x'), baseline.get('r'))))
        chosen = next((q for q in plans if q['chosen'] and baseline.get('fire')), None)
        if chosen is not None:
            if chosen['sent'] <= 0 or chosen['hold'] == 0:
                self.status = dict(status, why='nothing_to_retime', sent=chosen['sent'], hold=chosen['hold'])
                return None
            if chosen['hold'] > chosen['room']:
                self.status = dict(status, why='cannot_hold_long_enough', hold=chosen['hold'], room=chosen['room'])
                return None
            return self._reply(request, own, baseline, chosen, entry, window, 'retimed', status)
        if baseline.get('fire'):
            self.status = dict(status, why='baseline_fire_not_found')
            return None
        best = None
        # For the log: every fire the placements offer, biggest first (chain, sent, hold, room).
        status['candidates'] = [[len(q['points']), q['sent'], q['hold'], q['room']]
                                for q in sorted(plans, key=lambda q: -q['sent'])[:6]]
        for q in plans:
            if len(q['points']) > config['max_jab_chain']:
                status.update(why='jab_too_long', chain=len(q['points']))
                continue
            if q['sent'] < config['min_jab_sent'] or q['hold'] > q['room'] or q['finish'] > entry + window:
                status.update(why='no_jab_fits', sent=q['sent'], hold=q['hold'], room=q['room'], finish=q['finish'])
                continue
            if q['hold'] > config.get('max_jab_hold_frames',60):
                # Continue constructing until a later piece can hit the entry,
                # rather than freezing this piece for several build turns.
                status.update(why='jab_waits_too_long',hold=q['hold'])
                continue
            after = self.native.ask(dict(op='holding', field=q['p']['field']))['longest']
            if held >= config['main_min'] and after < held:
                status.update(why='jab_spends_the_main', held=held, after=after)
                continue
            # Do not hold a piece for a jab that misses the turnover window.
            q['in_window'] = q['finish'] <= entry + window
            if best is None or (q['in_window'], q['sent'], -q['hold']) > (best['in_window'], best['sent'], -best['hold']):
                best = q
        if best is None:
            self.status = status
            return None
        return self._reply(request, own, baseline, best, entry, window, 'jab', status)

    def _reply(self, request, own, baseline, plan, entry, window, kind, status):
        p, points = plan['p'], plan['points']
        shot = dict(kind=kind, entry=entry, window=window, hold_frames=plan['hold'], room=plan['room'],
                    first_link=plan['first'], end=plan['finish'], sent=plan['sent'],
                    in_window=plan['finish'] <= entry + window,
                    latest_end=entry + window + (self.late if kind == 'retimed' else 0))
        self.status = dict(why=kind, **shot)
        reply = dict(baseline) if kind == 'retimed' else dict(
            x=p['x'], r=p['r'], shape=own['queue'][0][0], reason='normal_entry_jab',
            fire=True, chain=len(points), next_chain=len(points), next_score=sum(points),
            next_field=p['field'], link_points=points, next_all_clear=p['all_clear'],
            decision_dependencies=['self', 'enemy'], searched_visible=len(own['queue']),
            normal_search_reused=False, normal_decision_status='build')
        reply.update(entry_fire=shot)
        if plan['hold']:
            reply.update(hold_frames=plan['hold'], hold_down_until_frame=request['frame'] + plan['hold'])
        return reply
