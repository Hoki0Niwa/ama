"""Keep the two destinations through observation, prediction and native requests."""


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
