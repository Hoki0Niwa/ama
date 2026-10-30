"""Defaults and bounds of opt-in normal-board pressure and finishing."""
from copy import deepcopy
from .model import integer

DEFAULTS = dict(
    pressure=dict(enabled=False, max_chain=2, min_send=6, max_send=30,
                  min_remaining=24, min_heights=[4, 4, 4, 3, 3, 3],
                  max_redundancy=4, third_column_height=8, block_seed_chain=8, weight=400,
                  allow_pending=False, fever_pressure=False, preempt=False, race_margin_frames=0,
                  min_enemy_points=2100, preempt_bonus=0,
                  send_weight=0, counter_cost_weight=1, gauge_weight=6, gauge_gain_weight=0, surplus_weight=0,
                  max_main_loss=84, protect_main_chain=0, min_remaining_chain=0, chain_reserve_step=0,
                  time_scale=0, max_attacks=0, attacks_used=0),
    finish=dict(enabled=False, min_send=6, weight=30000),
    counter_read=dict(depth=3, max_nodes=4000))
BOUNDS = dict(
    pressure=dict(max_chain=(1,19), min_send=(1,1000000), max_send=(1,1000000),
                  min_remaining=(0,84), max_redundancy=(0,84), third_column_height=(0,13),
                  block_seed_chain=(1,19), weight=(0,1000000),
                  race_margin_frames=(0,10000), min_enemy_points=(1,1000000000),
                  preempt_bonus=(0,1000000), send_weight=(0,1000000), counter_cost_weight=(0,1000000),
                  gauge_weight=(0,1000000), gauge_gain_weight=(0,1000000), surplus_weight=(0,1000000),
                  max_main_loss=(0,84), protect_main_chain=(0,19), min_remaining_chain=(0,19), chain_reserve_step=(0,84),
                  time_scale=(0,10000), max_attacks=(0,100), attacks_used=(0,1000000)),
    finish=dict(min_send=(1,1000000), weight=(0,1000000)),
    counter_read=dict(depth=(1,3), max_nodes=(1,100000)))


def validate(overrides):
    for section, defaults in DEFAULTS.items():
        if section not in overrides:
            continue
        cfg = overrides[section]
        if not isinstance(cfg, dict) or set(cfg) - defaults.keys():
            raise ValueError(f'normal_tactics.{section} must be an object with known keys')
        for key, value in cfg.items():
            name = f'normal_tactics.{section}.{key}'
            if type(defaults[key]) is bool:
                if type(value) is not bool:
                    raise ValueError(f'{name} must be a boolean')
            elif key == 'min_heights':
                if not isinstance(value, list) or len(value) != 6:
                    raise ValueError(f'{name} must contain six heights')
                for height in value:
                    integer(height, name, 0, 13)
            else:
                integer(value, name, *BOUNDS[section][key])
        if section == 'pressure' and cfg.get('min_send', defaults['min_send']) > cfg.get('max_send', defaults['max_send']):
            raise ValueError('normal_tactics.pressure.min_send must be <= max_send')


def resolve(overrides):
    return {section: {**deepcopy(defaults), **deepcopy(overrides.get(section, {}))}
            for section, defaults in DEFAULTS.items()}
