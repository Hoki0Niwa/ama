"""Fever-mode event model. Seeds and animation boundaries are explicit inputs.

Values from player measurements remain unverified on the local Steam build.
The normal-only Referee and protocol 2 retain their original behavior.
"""
from dataclasses import dataclass, field
import json
import hashlib
from .model import ROOT, Player, Packet, Referee, convert, dead, integer, settled_field


def rules():
    return json.loads((ROOT / 'data/fever/mode_rules.json').read_text(encoding='utf-8'))


def next_seed(base, chain, all_clear=False, config=None, displayed=None):
    cfg = config or rules()
    integer(base, 'seed base', cfg['min_seed_chain'], cfg['max_seed_chain'])
    integer(chain, 'chain', 1, 19)
    # On all-clear entry, failure is measured against the unboosted base.
    level = chain + 1 if chain >= (displayed or base) else base - min(2, max(0, base - chain - 1))
    return max(cfg['min_seed_chain'], min(cfg['max_seed_chain'], level + (2 if all_clear else 0)))


@dataclass
class ModePlayer(Player):
    mode: str = 'normal'
    stored_rows: list[str] | None = None
    held_packets: list[Packet] = field(default_factory=list)
    prepared_frames: int = 900
    remaining_frames: int = 0
    clock_running: bool = False
    mode_generation: int = 0
    seed_id: int = 0
    seed_base: int = 5
    seed_chain: int = 5
    next_seed_chain: int = 5
    normal_all_clear_entry_bonus: bool = False

    def pending(self, confirmed=None):
        # During Fever, offset Fever-side nuisance before held normal nuisance.
        return super().pending(confirmed) + sum(p.count for p in self.held_packets
                                               if confirmed is None or p.confirmed == confirmed)

    def active_pending(self, confirmed=None):
        return super().pending(confirmed)

    def consume(self, count, confirmed_only=False):
        taken = super().consume(count, confirmed_only)
        if not confirmed_only:
            for packet in self.held_packets:
                amount = min(packet.count, count - taken)
                packet.count -= amount
                taken += amount
            self.held_packets = [p for p in self.held_packets if p.count]
        return taken


class ModeReferee(Referee):
    """Transactional explicit events; no generated seed or inferred timer pause."""
    def __init__(self, characters, target_point=120, gauge_gain_on_offset=1):
        super().__init__(characters, target_point, 0)
        self.gain = integer(gauge_gain_on_offset, 'gauge_gain_on_offset', 0, 7)
        self.config = rules()
        self.players = [ModePlayer(c, prepared_frames=self.config['initial_time_frames'],
                                   seed_base=self.config['initial_seed_chain'],
                                   seed_chain=self.config['initial_seed_chain'],
                                   next_seed_chain=self.config['initial_seed_chain']) for c in characters]

    def _reward(self, player, frames):
        if player.mode == 'normal':
            player.prepared_frames = min(self.config['max_time_frames'], player.prepared_frames + frames)
        elif player.remaining_frames > 0:
            player.remaining_frames = min(self.config['max_time_frames'], player.remaining_frames + frames)

    def _apply(self, event):
        frame = integer(event['frame'], 'frame')
        elapsed = max(0, frame - max(0, self.last_key[0]))
        for p in self.players:
            if p.mode == 'fever' and p.clock_running:
                p.remaining_frames = max(0, p.remaining_frames - elapsed)
        kind = event['type']
        if kind == 'rate':
            return super()._apply(event)
        index = integer(event['player'], 'player', 0, 1)
        actor, enemy = self.players[index], self.players[1 - index]
        if kind in ('enter', 'exit', 'clock', 'tick'):
            key = (frame, integer(event['order'], 'order'))
            if key <= self.last_key:
                raise ValueError('events must be strictly ordered by (frame, order)')
            self.last_key = key
            if not actor.alive:
                raise ValueError('dead player cannot act')
            if kind == 'enter':
                if actor.mode != 'normal' or actor.active_chain or actor.gauge < self.config['gauge_max']:
                    raise ValueError('entry requires completed chain and full normal gauge')
                if type(event.get('clock_running')) is not bool:
                    raise ValueError('entry requires explicit clock_running')
                actor.stored_rows = actor.rows
                actor.held_packets = actor.packets
                actor.packets = []
                actor.rows = ['......'] * 14
                actor.mode = 'fever'
                actor.mode_generation += 1
                actor.remaining_frames = actor.prepared_frames
                actor.clock_running = event['clock_running']
                actor.seed_base = actor.next_seed_chain
                actor.seed_chain = min(self.config['max_seed_chain'], actor.seed_base +
                                      (2 if actor.normal_all_clear_entry_bonus else 0))
                actor.normal_all_clear_entry_bonus = False
                actor.awaiting_seed = True
                return {'mode': actor.mode, 'seed_chain': actor.seed_chain,
                        'remaining_frames': actor.remaining_frames, 'mode_generation': actor.mode_generation}
            if kind == 'exit':
                if actor.mode != 'fever' or actor.active_chain or actor.remaining_frames != 0:
                    raise ValueError('exit requires expired clock and completed chain')
                actor.rows = actor.stored_rows
                actor.stored_rows = None
                actor.packets = actor.held_packets + actor.packets
                actor.held_packets = []
                actor.mode = 'normal'
                actor.mode_generation += 1
                actor.gauge = 0
                actor.clock_running = False
                actor.prepared_frames = self.config['initial_time_frames']
                actor.awaiting_seed = False
                actor.all_clear = False
                actor.alive = not dead(actor.rows)
                return {'mode': actor.mode, 'dead': not actor.alive, 'mode_generation': actor.mode_generation}
            if actor.mode != 'fever':
                raise ValueError('clock event requires fever mode')
            if kind == 'clock':
                if type(event.get('running')) is not bool:
                    raise ValueError('explicit observed running flag required')
                actor.remaining_frames = integer(event['remaining_frames'], 'remaining_frames',
                                                 0, self.config['max_time_frames'])
                actor.clock_running = event['running']
            return {'remaining_frames': actor.remaining_frames, 'clock_running': actor.clock_running,
                    'exit_pending': actor.remaining_frames == 0}
        if kind == 'incoming':
            destination = event.get('destination')
            if destination not in ('normal', 'fever'):
                raise ValueError('incoming requires explicit normal/fever destination')
            if destination == 'fever' and actor.mode != 'fever':
                raise ValueError('fever destination unavailable')
            effect = super()._apply(event)
            if actor.mode == 'fever' and destination == 'normal':
                actor.held_packets.append(actor.packets.pop())
            return {**effect, 'destination': destination}
        if kind == 'seed':
            seed_id = integer(event['seed_id'], 'seed_id', actor.seed_id + 1)
            level = integer(event['seed_chain'], 'seed_chain', 3, 15)
            expected = actor.seed_chain if actor.mode == 'fever' else self.config['normal_all_clear_seed_chain']
            if level != expected:
                raise ValueError('seed chain does not match requested level')
            effect = super()._apply(event)
            actor.seed_id = seed_id
            # Consuming a normal all-clear reward before entry removes its entry bonus.
            if actor.mode == 'normal':
                actor.normal_all_clear_entry_bonus = False
            return {**effect, 'seed_id': seed_id, 'seed_chain': level}
        if kind == 'place':
            if actor.mode == 'fever' and actor.remaining_frames == 0:
                raise ValueError('expired timer requires exit before another placement')
            # Parent's drop must use only active-board packets, never stored ones.
            held = actor.held_packets
            actor.held_packets = []
            effect = super()._apply(event)
            actor.held_packets = held
            return effect
        if kind == 'link':
            # The inherited operation validates chain and event identity, then
            # consumes via ModePlayer's Fever-first packet ordering.
            effect = super()._apply(event)
            if effect['cancelled']:
                if actor.mode == 'normal':
                    actor.gauge = min(self.config['gauge_max'], actor.gauge + self.gain)
                if enemy.mode == 'normal':
                    self._reward(enemy, self.config['offset_time_reward_frames'])
            effect['gauge'] = actor.gauge
            effect['entry_pending'] = actor.mode == 'normal' and actor.gauge == self.config['gauge_max']
            return effect
        if kind == 'end':
            chain_id = actor.active_chain
            count, all_clear = actor.expected_links, actor.all_clear
            effect = super()._apply(event)
            # Packets sent before recipient entry retain their chain identity.
            for packet in enemy.held_packets:
                if packet.chain == chain_id:
                    packet.confirmed = True
            if actor.mode == 'fever':
                actor.next_seed_chain = next_seed(actor.seed_base, count, all_clear, self.config, actor.seed_chain)
                actor.seed_base = actor.next_seed_chain
                actor.seed_chain = actor.next_seed_chain
                self._reward(actor, max(0, count - self.config['chain_reward_start'] + 1) *
                             self.config['chain_reward_step_frames'])
                actor.awaiting_seed = actor.remaining_frames > 0 and actor.alive
            elif all_clear:
                actor.normal_all_clear_entry_bonus = True
            if all_clear:
                self._reward(actor, self.config['all_clear_time_reward_frames'])
            return {**effect, 'awaiting_seed': actor.awaiting_seed, 'seed_chain': actor.seed_chain,
                    'remaining_frames': actor.remaining_frames, 'prepared_frames': actor.prepared_frames,
                    'entry_pending': actor.mode == 'normal' and actor.gauge == self.config['gauge_max'],
                    'exit_pending': actor.mode == 'fever' and actor.remaining_frames == 0}
        return super()._apply(event)

    def snapshot(self):
        result = super().snapshot()
        result.update(rule='fever_battle', protocol_version=3, gauge_gain_on_offset=self.gain,
                      mode_rules_status=self.config['status'],
                      mode_rules_sha256=hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest())
        for data, p in zip(result['players'], self.players):
            data.update(mode=p.mode, mode_generation=p.mode_generation, seed_id=p.seed_id,
                        stored_field=p.stored_rows, remaining_frames=p.remaining_frames,
                        prepared_frames=p.prepared_frames, clock_running=p.clock_running,
                        seed_base=p.seed_base, seed_chain=p.seed_chain, next_seed_chain=p.next_seed_chain,
                        active_confirmed=p.active_pending(True), active_unconfirmed=p.active_pending(False),
                        held_confirmed=sum(q.count for q in p.held_packets if q.confirmed),
                        held_unconfirmed=sum(q.count for q in p.held_packets if not q.confirmed))
        return result
