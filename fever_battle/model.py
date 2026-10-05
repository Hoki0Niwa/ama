"""Normal-board scoring and causal battle events.

The event order is explicit, not an assertion about the Steam game's timing.
Rules not yet measured on the local Steam build are reported as a prototype.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMPTY = ['......'] * 14
GARBAGE_ORDER = (0, 3, 2, 5, 1, 4)  # player's documented Fever order, zero based


def integer(value, name, low=0, high=10**12):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def settled_field(rows):
    if not isinstance(rows, list) or len(rows) != 14 or rows[0] != '......':
        raise ValueError('field must have 14 rows and an empty 14th row')
    for row in rows:
        if not isinstance(row, str) or len(row) != 6 or any(c not in 'RYGB#.' for c in row):
            raise ValueError('invalid field row')
    for x in range(6):
        empty_seen = False
        for y in range(13, 0, -1):
            if rows[y][x] == '.':
                empty_seen = True
            elif empty_seen:
                raise ValueError('floating cells in settled field')
    return list(rows)


def dead(rows):
    return rows[2][2] != '.' or rows[2][3] != '.'


def drop_garbage(rows, count, garbage_phase=0):
    """Deterministic Fever columns; never reuse Tsu's drop_garbage()."""
    rows = [list(row) for row in settled_field(rows)]
    integer(count, 'garbage count', 0, 30)
    integer(garbage_phase, 'garbage_phase', 0, 5)
    heights = [sum(rows[y][x] != '.' for y in range(1, 14)) for x in range(6)]
    amounts = [count // 6] * 6
    for k in range(count % 6):
        amounts[GARBAGE_ORDER[(garbage_phase + k) % 6]] += 1
    discarded = 0
    for x, amount in enumerate(amounts):
        for _ in range(amount):
            if heights[x] >= 13:
                discarded += 1
            else:
                rows[13 - heights[x]][x] = '#'
                heights[x] += 1
    result = [''.join(row) for row in rows]
    return result, discarded


class Scoring:
    def __init__(self, path=ROOT / 'data/fever/scoring.json'):
        self.data = json.loads(Path(path).read_text(encoding='utf-8'))
        expected = {c['id'] for c in json.loads((ROOT / 'data/fever/dropsets.json').read_text(encoding='utf-8'))['characters']}
        if set(self.data['characters']) != expected:
            raise ValueError('scoring table must cover exactly the known character IDs')
        for entry in self.data['characters'].values():
            if len(entry['normal']) != 19:
                raise ValueError('normal power table must contain 19 links')
            for power in entry['normal']:
                integer(power, 'chain power', 0, 999)
            if 'fever' in entry:
                if len(entry['fever']) != 17:
                    raise ValueError('Fever power table must contain 17 links')
                for power in entry['fever']:
                    integer(power, 'Fever chain power', 0, 999)

    def link(self, character, index, groups, colors, mode='normal'):
        if character not in self.data['characters']:
            raise ValueError('unknown character')
        if mode not in ('normal', 'fever'):
            raise ValueError('unknown scoring mode')
        table = self.data['characters'][character].get(mode)
        if table is None:
            raise ValueError('missing power table for scoring mode')
        integer(index, 'chain link', 1, len(table))
        if not isinstance(groups, list) or not groups:
            raise ValueError('a link must clear at least one group')
        for group in groups:
            integer(group, 'group size', 4, 78)
        integer(colors, 'cleared colors', 1, min(4, len(groups)))
        if sum(groups) > 78:
            raise ValueError('a link cannot clear more than 78 cells in the 13-row model')
        bonus = self.data['bonuses']
        power = table[index - 1]
        multiplier = power + bonus['color'][colors] + sum(bonus['group'][min(11, g)] for g in groups)
        multiplier = min(bonus['multiplier_max'], max(bonus['multiplier_min'], multiplier))
        return 10 * sum(groups) * multiplier

    def chain(self, character, links, mode='normal'):
        return [self.link(character, i + 1, link['groups'], link['colors'], mode) for i, link in enumerate(links)]

    @property
    def provenance(self):
        return {'power': self.data['source']['status'], 'bonuses': self.data['bonuses']['status'],
                'local_steam_verified': False}


def convert(points, remainder, target_point, pending=0):
    integer(points, 'points')
    integer(remainder, 'unconverted points')
    integer(target_point, 'target_point', 1, 100000)
    integer(pending, 'pending')
    nuisance, rest = divmod(points + remainder, target_point)
    # The guaranteed one-puyo offset is documented; the interaction with the
    # carried remainder is a prototype assumption awaiting a Fever recording.
    forced = pending > 0 and nuisance == 0 and points > 0
    return nuisance if not forced else 1, rest, forced


@dataclass
class Packet:
    count: int
    chain: str
    confirmed: bool = False


@dataclass
class Player:
    character: str
    rows: list[str] = field(default_factory=lambda: list(EMPTY))
    packets: list[Packet] = field(default_factory=list)
    remainder: int = 0
    gauge: int = 0
    garbage_phase: int = 0
    active_chain: str | None = None
    next_link: int = 1
    expected_links: int = 0
    final_field: list[str] | None = None
    all_clear: bool = False
    awaiting_seed: bool = False
    alive: bool = True
    moves_since_chain: int = 0

    def pending(self, confirmed=None):
        return sum(p.count for p in self.packets if confirmed is None or p.confirmed == confirmed)

    def consume(self, count, confirmed_only=False):
        taken = 0
        # Explicit causal model: oldest packet first. Steam ordering of fixed
        # versus running packets is not silently assumed to be verified.
        for p in self.packets:
            if confirmed_only and not p.confirmed:
                continue
            amount = min(p.count, count - taken)
            p.count -= amount
            taken += amount
        self.packets = [p for p in self.packets if p.count]
        return taken


class Referee:
    """Replay explicit events, transactional on each event, gauge gain fixed at 0."""
    def __init__(self, characters, target_point=120, gauge_gain_on_offset=0):
        if len(characters) != 2:
            raise ValueError('exactly two players required')
        scoring = Scoring()
        if any(c not in scoring.data['characters'] for c in characters):
            raise ValueError('unknown character')
        if gauge_gain_on_offset != 0 or type(gauge_gain_on_offset) is not int:
            raise ValueError('only gauge_gain_on_offset=0 is implemented')
        self.players = [Player(c) for c in characters]
        self.target_point = integer(target_point, 'target_point', 1, 100000)
        self.last_key = (-1, -1)
        self.used_chains = set()
        self.log = []
        self.reset_moves_at_chain = integer(json.loads((ROOT / 'data/fever/battle_policy.json').read_text(
            encoding='utf-8'))['reset_moves_at_chain'], 'reset_moves_at_chain', 1, 19)

    def apply(self, event):
        saved = deepcopy((self.players, self.target_point, self.last_key, self.used_chains))
        try:
            output = self._apply(event)
        except Exception:
            self.players, self.target_point, self.last_key, self.used_chains = saved
            raise
        self.log.append({'event': deepcopy(event), 'effect': output})
        return output

    def _apply(self, event):
        key = (integer(event['frame'], 'frame'), integer(event['order'], 'order'))
        if key <= self.last_key:
            raise ValueError('events must be strictly ordered by (frame, order)')
        self.last_key = key
        kind = event['type']
        if kind == 'rate':
            self.target_point = integer(event['target_point'], 'target_point', 1, 100000)
            return {'target_point': self.target_point}
        index = integer(event['player'], 'player', 0, 1)
        actor, enemy = self.players[index], self.players[1 - index]
        if not actor.alive:
            raise ValueError('dead player cannot act')
        if kind == 'incoming':
            count = integer(event['count'], 'incoming count')
            if type(event['confirmed']) is not bool:
                raise ValueError('confirmed must be boolean')
            chain = event['chain']
            if not isinstance(chain, str) or not chain:
                raise ValueError('chain identity required')
            actor.packets.append(Packet(count, chain, event['confirmed']))
            return {'added': count}
        if kind == 'seed':
            if not actor.awaiting_seed or actor.active_chain:
                raise ValueError('no completed all-clear seed requested')
            actor.rows = settled_field(event['field'])
            actor.awaiting_seed = False
            actor.alive = not dead(actor.rows)
            return {'seed_loaded': True, 'dead': not actor.alive}
        if kind == 'place':
            if actor.active_chain or actor.awaiting_seed:
                raise ValueError('player is busy or needs an observed all-clear seed')
            result = event['result']
            after = settled_field(result['field'])
            links = result['links']
            if not isinstance(links, list):
                raise ValueError('links must be an array')
            integer(len(links), 'chain length', 0, 19)
            actor.moves_since_chain = (0 if len(links) >= self.reset_moves_at_chain
                                       else actor.moves_since_chain + 1)
            if links:
                chain = event['chain']
                if not isinstance(chain, str) or not chain or chain in self.used_chains:
                    raise ValueError('chain ID must be unique')
                self.used_chains.add(chain)
                actor.active_chain = chain
                actor.next_link = 1
                actor.expected_links = len(links)
                actor.final_field = after
                actor.all_clear = all(row == '......' for row in after)
                return {'chain_started': chain, 'links': len(links)}
            actor.rows = after
            dropped = actor.consume(min(30, actor.pending(True)), confirmed_only=True)
            actor.rows, discarded = drop_garbage(actor.rows, dropped, actor.garbage_phase)
            if dropped:
                actor.garbage_phase = (actor.garbage_phase + dropped) % 6
            actor.alive = not dead(actor.rows)
            return {'dropped': dropped, 'discarded': discarded, 'dead': not actor.alive,
                    'garbage_phase': actor.garbage_phase}
        if kind == 'link':
            link = integer(event['link'], 'link', 1, 19)
            if actor.active_chain != event['chain'] or link != actor.next_link:
                raise ValueError('wrong active chain or link order')
            if actor.next_link > actor.expected_links:
                raise ValueError('too many links')
            points = integer(event['points'], 'link points', 1)
            nuisance, actor.remainder, forced = convert(points, actor.remainder, self.target_point, actor.pending())
            cancelled = actor.consume(nuisance)
            sent = nuisance - cancelled
            if sent:
                enemy.packets.append(Packet(sent, actor.active_chain, False))
            actor.next_link += 1
            return {'points': points, 'cancelled': cancelled, 'sent': sent,
                    'remainder': actor.remainder, 'forced_minimum_offset': forced, 'gauge': actor.gauge}
        if kind == 'end':
            if actor.active_chain != event['chain'] or actor.next_link != actor.expected_links + 1:
                raise ValueError('cannot finish incomplete or wrong chain')
            for packet in enemy.packets:
                if packet.chain == actor.active_chain:
                    packet.confirmed = True
            actor.rows = actor.final_field
            actor.final_field = None
            actor.active_chain = None
            actor.awaiting_seed = actor.all_clear
            actor.alive = not dead(actor.rows)
            # Clearing keeps the nuisance held. It drops on a later nonclear
            # placement; no fictional Tsu +30 all-clear bonus is added.
            return {'dead': not actor.alive, 'awaiting_seed': actor.awaiting_seed}
        raise ValueError('unknown event type')

    def snapshot(self):
        return {'model_status': 'prototype_unverified_on_local_steam', 'target_point': self.target_point,
                'gauge_gain_on_offset': 0, 'event_order': 'explicit_frame_order',
                'players': [{'character': p.character, 'field': p.rows, 'confirmed': p.pending(True),
                             'unconfirmed': p.pending(False), 'remainder': p.remainder, 'gauge': p.gauge,
                             'chain': p.active_chain, 'awaiting_seed': p.awaiting_seed, 'alive': p.alive,
                             'moves_since_chain': p.moves_since_chain, 'garbage_phase': p.garbage_phase}
                            for p in self.players]}
