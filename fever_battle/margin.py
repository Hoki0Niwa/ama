"""Fever margin forecasts anchored to observed rates, never a guessed setting.

The curve is the Steam code's (FUN_140059e60, data/fever/margin_reference.json):
from the start frame, every 8 seconds the rate is initial*factor>>8 (at least 1)
over a 27-step table. 120 and 192 seconds are the code defaults, which does not
identify a live room's setting, so the start is inferred from observed changes
unless a request states it.
"""
import json
from .model import ROOT, integer

_REFERENCE = json.loads((ROOT/'data/fever/margin_reference.json').read_text(encoding='utf-8'))
FACTORS = tuple(_REFERENCE['factor_256'])
STEP = _REFERENCE['step_frames']
DEFAULT_INITIAL = _REFERENCE['initial_target_point']


def step_rate(initial, step):
    """The rate `step` margin steps after the start frame."""
    return max(1, initial*FACTORS[min(len(FACTORS)-1, step)] >> 8)


def changes(initial):
    """(step, rate) of each step whose rate differs from the step before; step 0 starts at the start frame."""
    result, previous = [], initial
    for step in range(len(FACTORS)):
        rate = step_rate(initial, step)
        if rate != previous:
            result.append((step, rate))
            previous = rate
    return tuple(result)


REFERENCE_CHANGES = changes(DEFAULT_INITIAL)
# Distinct and decreasing, so an observed rate names its change.
REFERENCE_RATES = tuple(rate for _, rate in REFERENCE_CHANGES)


def active(request, forecast=None):
    """A stated or observed margin start, never a guess from a low rate alone."""
    explicit=request.get('margin_policy')
    if explicit is not None:
        return request['frame']>=explicit['start_frame']
    bounds=(forecast or {}).get('margin_start_frame_bounds')
    return bool(bounds and request['frame']>=bounds[1])


def rate_at(initial, events, frame):
    for event in events or []:
        if event['frame'] > frame:
            break
        initial = event['target_point']
    return initial


class MarginForecast:
    def __init__(self):
        self.match = None
        self.previous = None
        self.bounds = None
        self.changes = 0
        self.disabled = False

    def observe(self, request):
        frame, rate = request['frame'], request['target_point']
        if self.match != request['match_id'] or (self.previous and frame < self.previous[0]):
            self.__init__()
            self.match = request['match_id']
        explicit = request.get('margin_policy')
        if explicit is not None:
            if not isinstance(explicit, dict) or set(explicit) != {'start_frame', 'initial_target_point'}:
                raise ValueError('margin_policy requires explicit start_frame and initial_target_point')
            start = integer(explicit['start_frame'], 'margin start_frame', 0, 10**9)
            initial = integer(explicit['initial_target_point'], 'margin initial rate', 1, 100000)
            expected = initial if frame < start else step_rate(initial, (frame-start)//STEP)
            if rate != expected:
                return self.describe(frame, rate, None, 'observed_rate_disagrees_with_explicit_reference')
            return self.describe(frame, rate, (start, start), 'explicit_setting_steam_code_curve', initial)
        if self.previous and frame > self.previous[0] and rate != self.previous[1]:
            old_frame, old_rate = self.previous
            if rate not in REFERENCE_RATES or not (old_rate == DEFAULT_INITIAL or old_rate in REFERENCE_RATES) or rate >= old_rate:
                self.disabled = True
            elif not self.disabled:
                index = REFERENCE_RATES.index(rate)
                # Last observation bounds the FIRST crossed boundary, which
                # matters when several stages passed without a decision.
                next_index = 0 if old_rate == DEFAULT_INITIAL else REFERENCE_RATES.index(old_rate)+1
                low = old_frame+1-REFERENCE_CHANGES[next_index][0]*STEP
                high = frame-REFERENCE_CHANGES[index][0]*STEP
                if self.bounds:
                    low, high = max(low, self.bounds[0]), min(high, self.bounds[1])
                if low > high:
                    self.disabled = True
                else:
                    self.bounds = low, high
                    self.changes += 1
        if not self.previous or frame >= self.previous[0]:
            self.previous = frame, rate
        bounds = None if self.disabled else self.bounds
        return self.describe(frame, rate, bounds, 'observed_changes_steam_code_curve_estimate' if bounds
                             else 'observed_rate_only_margin_setting_unknown')

    def describe(self, frame, rate, bounds, status, initial=DEFAULT_INITIAL):
        own, enemy = [], []
        table = changes(initial)
        rates = [value for _, value in table]
        upcoming = ()
        if bounds and rate in rates:
            upcoming = table[rates.index(rate)+1:]
        elif bounds and rate == initial:
            upcoming = table
        for step, value in upcoming:
            # Own changes at the latest start (our attack no larger), the opponent's at the earliest.
            earliest, latest = bounds[0]+step*STEP-frame, bounds[1]+step*STEP-frame
            if earliest > 3000:
                break
            own.append(dict(frame=max(0, latest), target_point=value))
            enemy.append(dict(frame=max(0, earliest), target_point=value))
        # Large missed intervals can place multiple changes at frame zero.
        def unique(events):
            result = {}
            for event in events:
                result[event['frame']] = event
            return list(result.values())
        return dict(rate_events=unique(own), enemy_rate_events=unique(enemy),
                    status=status, observed_target_point=rate, observed_changes=self.changes,
                    margin_start_frame_bounds=list(bounds) if bounds else None)
