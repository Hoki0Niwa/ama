"""Opt-in normal spawn observations; unknown moving/transition boards stay excluded."""
from .model import integer


def ready_window(opponent, events, fever, enabled):
    if not enabled or opponent.get('mode') != 'normal' or opponent.get('phase') != 'waiting_seed':
        return None
    if events or (fever and fever.get('enemy_fever')) or opponent.get('gauge', 7) >= 7:
        return None
    wait = opponent.get('normal_wait')
    if not isinstance(wait, dict) or wait.get('kind') != 'spawn' or wait.get('board_fixed') is not True:
        return None
    if opponent.get('board_status') != 'observed_fixed' or not opponent.get('queue'):
        return None
    if wait.get('observed_frame') != opponent.get('observed_frame') or opponent.get('board_observed_frame') != opponent.get('observed_frame'):
        return None
    low = integer(wait.get('ready_in_min'), 'normal_wait.ready_in_min', 0, 120)
    high = integer(wait.get('ready_in_max'), 'normal_wait.ready_in_max', low, 120)
    return dict(ready_in_min=low, ready_in_max=high)
