"""Fever margin forecasts anchored to observed rates, never a guessed setting.

SEGA documents a default of 192 seconds; that does not identify a live match's
setting. The 16-second sequence is a PS2 Fever measurement, so extrapolation
from observed Steam changes is labelled as an estimate until measured locally.
"""
import json
from .model import ROOT, integer

_REFERENCE = json.loads((ROOT/'data/fever/margin_reference.json').read_text(encoding='utf-8'))
REFERENCE_RATES = tuple(_REFERENCE['rates_after_start'])
INTERVAL = _REFERENCE['interval_frames']


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
            if initial != 120:
                raise ValueError('reference margin curve only supports initial rate 120')
            expected = 120 if frame < start else REFERENCE_RATES[min(11, (frame-start)//INTERVAL)]
            if rate != expected:
                return self.describe(frame, rate, None, 'observed_rate_disagrees_with_explicit_reference')
            return self.describe(frame, rate, (start, start), 'explicit_setting_reference_curve_unverified_steam')
        if self.previous and frame > self.previous[0] and rate != self.previous[1]:
            old_frame, old_rate = self.previous
            if rate not in REFERENCE_RATES or not (old_rate == 120 or old_rate in REFERENCE_RATES) or rate >= old_rate:
                self.disabled = True
            elif not self.disabled:
                index = REFERENCE_RATES.index(rate)
                # Last observation bounds the FIRST crossed boundary, which
                # matters when several stages passed without a decision.
                next_index = 0 if old_rate == 120 else REFERENCE_RATES.index(old_rate)+1
                low, high = old_frame+1-next_index*INTERVAL, frame-index*INTERVAL
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
        return self.describe(frame, rate, bounds, 'observed_changes_reference_interval_estimate' if bounds
                             else 'observed_rate_only_margin_setting_unknown')

    def describe(self, frame, rate, bounds, status):
        own, enemy = [], []
        if bounds and rate in REFERENCE_RATES:
            current = REFERENCE_RATES.index(rate)
            for index in range(current+1, len(REFERENCE_RATES)):
                earliest, latest = bounds[0]+index*INTERVAL-frame, bounds[1]+index*INTERVAL-frame
                if earliest > 3000:
                    break
                own.append(dict(frame=max(0, latest), target_point=REFERENCE_RATES[index]))
                enemy.append(dict(frame=max(0, earliest), target_point=REFERENCE_RATES[index]))
        elif bounds and rate == 120:
            for index, value in enumerate(REFERENCE_RATES):
                at = bounds[0]+index*INTERVAL-frame
                if at > 3000:
                    break
                own.append(dict(frame=max(0, at), target_point=value))
            enemy = list(own)
        # Large missed intervals can place multiple changes at frame zero.
        def unique(events):
            result = {}
            for event in events:
                result[event['frame']] = event
            return list(result.values())
        return dict(rate_events=unique(own), enemy_rate_events=unique(enemy),
                    status=status, observed_target_point=rate, observed_changes=self.changes,
                    margin_start_frame_bounds=list(bounds) if bounds else None)
