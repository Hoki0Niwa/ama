"""Time a sufficient return or margin-time offset against incoming attacks.

A fire made while their chain is still scoring offsets only what is in our tray when each of its links launches
and sends nothing back; the same chain a little later offsets more links and gains more Fever gauge (one step per
offset). The arrival of each of their links is predicted (their link begins at `frame`, its attack object enters
our tray `LAUNCH_FRAMES` later, chain_to_us.py) and set against the launch of each link of ours (its begin +
`launch_frames`, the lock after the fastest DOWN, ChainTiming), so the hold is chosen from the times at which the
packets are in the tray, not from the totals. A flight counts only `margin_frames` after its predicted entry.

The piece is held (no DOWN, a free fall) for the best of "now" and the moments just after each flight; the
bridge reads `hold_frames` / `hold_down_until_frame` as for entry_fire.py.
Outside confirmed margin time, a hold requires our chain to exceed the full known incoming attack.
A weaker normal main keeps building until the last safe lock/check before their chain ends.
"""
from .timing import ChainTiming
from .model import convert
from .margin import active as margin_active


def hold_permission(request, own, points, rate, flights, margin_forecast=None):
    flying=request.get('observation',{}).get('in_flight',{}).get('self',{}).get('incoming_in_flight',0)
    incoming=own['confirmed']+own['unconfirmed']+flying+sum(a for _,a in flights)
    strength=(own['remainder']+sum(points))//rate
    margin=margin_active(request,margin_forecast)
    return dict(allowed=margin or strength>incoming,margin=margin,
                own_nuisance=strength,incoming_total=incoming)


class GaugeWait:
    def __init__(self, native, scoring):
        self.native, self.scoring = native, scoring
        self.status = None

    @staticmethod
    def fire(links, pending, flights, remainder, rate, gauge, gain, launch, margin):
        """The chain whose links begin at the (frame, points) pairs `links`: gauge after it, nuisance sent back,
        and what is left pending. A flight is in the tray `margin` frames after its entry."""
        flights = sorted(flights)
        arrived = returned = offsets = cancelled = 0
        for begin, points in links:
            while arrived < len(flights) and flights[arrived][0] + margin <= begin + launch:
                pending += flights[arrived][1]
                arrived += 1
            amount, remainder, _ = convert(points, remainder, rate, pending)
            taken = min(pending, amount)
            cancelled += taken
            pending -= taken
            returned += amount - taken
            offsets += bool(taken)
        pending += sum(a for _, a in flights[arrived:])
        return dict(gauge_after=min(7, gauge + gain * offsets), offsets=offsets, returned=returned,
                    remaining=pending, cancelled=cancelled)

    def choose(self, request, own, enemy, reply, config, rate, flights, pace=None, placements=None, margin_forecast=None):
        """The reply with its hold, or None. `status` says why not (None when nothing is incoming to wait for).
        `flights` are chain_to_us.flights_to_us: (frame, amount) of each attack entering our tray."""
        self.status = None
        points = reply.get('link_points') or []
        if (not config.get('enabled', False) or own['mode'] != 'normal' or own['gauge'] >= 7
                or not reply.get('fire') or not points or reply.get('selected_move_loses')
                or reply.get('hold_down_until_frame') is not None):
            return None
        gain = request['gauge_gain_on_offset']
        if gain <= 0:
            return None
        if placements is None:
            if not flights:
                return None
            placements = self.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
        placed = next((p for p in placements if (p['x'], p['r']) == (reply['x'], reply['r'])), None)
        if placed is None or placed['dead'] or not placed['links']:
            self.status = dict(why='placement_not_found')
            return None
        from .nuisance import counter_flights
        predicted = list(flights)
        for flight in counter_flights(request):
            if flight.get('arrive_frame', -1) < 0:
                continue
            observed = (max(0,flight['arrive_frame']-request['frame']),flight['amount'])
            if observed in predicted:
                predicted.remove(observed)
        reply['offset_timing'] = dict(placement=placed, config=config, pace=pace, rate=rate,
            chain=chain_identity(request), flights=[[request['frame']+f,a] for f,a in predicted],
            margin_forecast=margin_forecast)
        if not flights:
            return None
        timing = ChainTiming.for_mode('normal')
        launch, margin, fast = config['launch_frames'], config['margin_frames'], config['fast_lock_frames']
        in_flight = request.get('observation', {}).get('in_flight', {}).get('self', {}).get('incoming_in_flight', 0)
        pending = own['confirmed'] + own['unconfirmed'] + in_flight
        fall = max(0, config['spawn_height'] - placed['contact_height']) * config['fall_frames_per_row']
        room = int(fall + config['lock_limit_frames'] - config['safety_frames'] - fast)

        line = timing.timeline(points, placed['fall_distances'], placed.get('fall_features'),
                               start_offset=fast + timing.first_link_frames)
        links = [(link['score_at'], link['points']) for link in line['links']]

        def shoot(hold):
            return self.fire([(begin+hold, value) for begin,value in links], pending, flights,
                             own['remainder'], rate, own['gauge'], gain, launch, margin)

        # Align every link, not just the first. An incoming packet near our
        # fifth link may need a short hold even when waiting for the first link
        # would exceed the available fall/lock room.
        holds = sorted({0, *(max(0, frame + margin - begin - launch)
                             for frame, _ in flights for begin, _ in links)})
        now = shoot(0)
        status = dict(why=None, gauge=own['gauge'], gauge_now=now['gauge_after'], returned_now=now['returned'],
                      remaining_now=now['remaining'], offsets_now=now['offsets'], cancelled_now=now['cancelled'],
                      room=room, flights=[list(f) for f in sorted(flights)[:6]])
        permission=hold_permission(request,own,points,rate,flights,margin_forecast)
        status.update(permission)
        if not permission['allowed']:
            self.status=dict(status,why='extend_before_entry')
            return None
        best, over = None, False
        for hold in holds:
            if hold > room:
                over = True
                continue
            result = dict(shoot(hold), hold=hold)
            # At margin a useful offset can also send a large surplus. Do not
            # reject it just because it exceeds the old six-puyo ceiling.
            if result['returned'] > max(config['max_returned'], now['returned']) or result['remaining'] > max(config['max_remaining'], now['remaining']):
                continue
            if best is None or (result['gauge_after'], -hold) > (best['gauge_after'], -best['hold']):
                best = result
        gained = best is not None and (best['gauge_after'] - now['gauge_after'] >= config['min_gauge_gain']
                                       or best['gauge_after'] >= 7 > now['gauge_after'])
        if best is None or best['hold'] == 0 or not gained:
            status['why'] = ('cannot_hold_long_enough' if over and best is None
                             else 'sends_back' if best is None and now['returned'] > config['max_returned']
                             else 'leaves_too_much' if best is None
                             else 'fire_now' if best['hold'] == 0 else 'gauge_not_worth_waiting')
            self.status = status
            return None
        status.update(why='wait', hold=best['hold'], gauge_then=best['gauge_after'], returned=best['returned'],
                      remaining=best['remaining'], offsets=best['offsets'], cancelled=best['cancelled'])
        self.status = status
        return dict(reply, hold_frames=best['hold'], hold_down_until_frame=request['frame'] + best['hold'],
                    gauge_forecast=forecast(best['gauge_after'],best['offsets'],best['cancelled'],best['remaining']),
                    entry_pending_after_chain=best['gauge_after']>=7,
                    gauge_wait=dict(status, kind='gauge_wait'))


def forecast(gauge, offsets, cancelled, remaining):
    return dict(gauge_after=gauge,offset_links=offsets,cancelled=cancelled,
                remaining_pending=remaining,model='offset_launch_timeline')


def chain_identity(request):
    chain = request.get('enemy_chain')
    enemy = request['enemy']
    return None if not chain else [request['match_id'], enemy['mode_generation'], enemy['seed_id'],
        chain.get('start_frame', request['frame']-chain.get('elapsed',0))]


def retime_cached(reply, request):
    """Recheck only a committed fire's timing on spawn; no IPC or placement search."""
    context = reply.get('offset_timing')
    if not context or reply.get('entry_fire') or not reply.get('fire'):
        return reply
    from .nuisance import counter_flights
    result = dict(reply)
    for key in ('hold_frames','hold_down_until_frame','gauge_wait','gauge_wait_status'):
        result.pop(key, None)
    flights = []
    if context['chain'] == chain_identity(request) and context['rate'] == request['target_point']:
        flights.extend((f-request['frame'],a) for f,a in context['flights'] if f>request['frame'])
    for flight in counter_flights(request):
        if flight.get('arrive_frame', -1) >= 0:
            flights.append((max(0,flight['arrive_frame']-request['frame']),flight['amount']))
    wait = GaugeWait(None, None)
    chosen = wait.choose(request, request['self'], request['enemy'], result, context['config'],
        request['target_point'], sorted(flights), pace=context['pace'], placements=[context['placement']],
        margin_forecast=context.get('margin_forecast'))
    result = chosen or result
    if wait.status is not None:
        result['gauge_wait_status'] = dict(wait.status, execution_retimed=True)
        if chosen is None and 'gauge_now' in wait.status:
            status=wait.status
            result['gauge_forecast']=forecast(status['gauge_now'],status['offsets_now'],
                                               status['cancelled_now'],status['remaining_now'])
            result['entry_pending_after_chain']=status['gauge_now']>=7
    elif request['self']['mode']=='normal':
        own=request['self']
        pending=own['confirmed']+own['unconfirmed']+request.get('observation',{}).get('in_flight',{}).get('self',{}).get('incoming_in_flight',0)
        now=GaugeWait.fire([(0,p) for p in result['link_points']],pending,[],own['remainder'],
                           request['target_point'],own['gauge'],request['gauge_gain_on_offset'],0,0)
        result['gauge_forecast']=forecast(now['gauge_after'],now['offsets'],now['cancelled'],now['remaining'])
        result['entry_pending_after_chain']=now['gauge_after']>=7
    return result
