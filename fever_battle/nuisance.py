"""Keep the two destinations through observation, prediction and native requests."""
from .model import integer


def counter_flights(request):
    flights = request.get('observation', {}).get('in_flight', {}).get('enemy', {})
    return [f for f in flights.get('attacks_in_flight', []) if f.get('counter') and f.get('amount')]


def link_amount(event, remainder, rate, pending):
    """A flight is already converted to nuisance; do not score it twice."""
    if 'nuisance' in event:
        return integer(event['nuisance'], 'observed nuisance', 0, 10**9), remainder
    amount, remainder = divmod(event['points'] + remainder, rate)
    return max(1, amount) if pending else amount, remainder


class Trays:
    def __init__(self, side):
        self.destination = side.get('nuisance_destination', side.get('mode', 'normal'))
        if self.destination not in ('normal', 'fever'):
            raise ValueError('invalid nuisance destination')
        self.values = {mode: [side.get(mode + '_confirmed',
                                      side.get('confirmed', 0) if mode == self.destination else 0),
                              side.get(mode + '_unconfirmed',
                                      side.get('unconfirmed', 0) if mode == self.destination else 0)]
                       for mode in ('normal', 'fever')}

    def pending(self):
        # The dormant Fever tray is not a normal-board counter balance.
        modes = ('fever', 'normal') if self.destination == 'fever' else ('normal',)
        return sum(sum(self.values[m]) for m in modes)

    def offset(self, amount):
        modes = ('fever', 'normal') if self.destination == 'fever' else ('normal',)
        for mode in modes:
            for i in (0, 1):
                taken = min(self.values[mode][i], amount)
                self.values[mode][i] -= taken
                amount -= taken
        return amount

    def send(self, amount):
        self.values[self.destination][1] += amount

    def native(self):
        return dict(enemy_nuisance_destination=self.destination,
                    **{'enemy_' + mode + '_' + kind: self.values[mode][i]
                       for mode in ('normal', 'fever')
                       for i, kind in enumerate(('confirmed', 'unconfirmed'))})

    def identity(self):
        return dict(destination=self.destination, **self.values)
