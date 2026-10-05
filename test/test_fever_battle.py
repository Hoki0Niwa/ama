"""Counterexamples for normal-battle scoring, nuisance causality and native API."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.engine import BattleEngine
from fever_battle.model import EMPTY, Referee, Scoring, convert, drop_garbage
from fever_battle.worker import JsonProcess
from fever_battle.observation import authorize_reply
from fever_battle.replay import replay
from fever_battle.simulate import simulate

NATIVE = Path(os.environ.get('AMA_BATTLE_NATIVE', ROOT / 'bin/fever_battle/fever_battle.exe'))
SOLO = Path(os.environ.get('AMA_TEST_FEVER_ENGINE', ROOT / 'bin/fever/fever.exe'))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.score = Scoring()

    def test_distinct_characters_and_e_sports_specific_table(self):
        self.assertEqual(self.score.link('paprisu', 2, [4], 1), 360)
        self.assertEqual(self.score.link('raffina', 12, [4], 1), 20480)
        self.assertEqual(self.score.link('serilly', 7, [4], 1), 3600)
        self.assertEqual(self.score.link('satan', 14, [4], 1), 26200)
        self.assertEqual(self.score.link('penglai', 10, [4], 1), 12800)
        self.assertEqual(self.score.link('draco', 10, [4], 1), 12760)

    def test_color_and_separate_group_bonus(self):
        self.assertEqual(self.score.link('raffina', 1, [4], 1), 40)
        self.assertEqual(self.score.link('raffina', 1, [5], 1), 50)
        self.assertEqual(self.score.link('raffina', 1, [4, 4], 2), 160)
        self.assertEqual(self.score.link('raffina', 1, [4, 4], 1), 80)
        self.assertEqual(self.score.link('raffina', 1, [8], 1), 320)
        self.assertEqual(self.score.link('raffina', 19, [60], 1), 424200)

    def test_reject_unknown_character_or_unknown_power(self):
        for character, index in [('unknown', 1), ('raffina', 20), ('raffina', 0)]:
            with self.assertRaises(ValueError):
                self.score.link(character, index, [4], 1)
        with self.assertRaises(ValueError):
            self.score.link('raffina', 1, [3], 1)

    def test_residue_rate_change_and_minimum_offset(self):
        self.assertEqual(convert(40, 0, 120), (0, 40, False))
        self.assertEqual(convert(40, 80, 120), (1, 0, False))
        self.assertEqual(convert(40, 0, 120, 5), (1, 40, True))
        self.assertEqual(convert(40, 80, 60), (2, 0, False))

    def test_provenance_is_not_promoted_to_steam(self):
        self.assertFalse(self.score.provenance['local_steam_verified'])
        self.assertEqual(len(self.score.data['characters']), 26)


class GarbageTests(unittest.TestCase):
    def test_fever_order_and_rounds(self):
        rows, _ = drop_garbage(EMPTY, 1)
        self.assertEqual(rows[-1], '#.....')
        rows, _ = drop_garbage(EMPTY, 3)
        self.assertEqual(rows[-1], '#.##..')
        rows, _ = drop_garbage(EMPTY, 8)
        self.assertEqual(rows[-1], '######')
        self.assertEqual(rows[-2], '#..#..')

    def test_overflow_and_death_rows(self):
        rows = list(EMPTY)
        for y in range(1, 14):
            rows[y] = '#.....'
        after, discarded = drop_garbage(rows, 1)
        self.assertEqual(discarded, 1)
        self.assertEqual(after[0], '......')
        with self.assertRaises(ValueError):
            drop_garbage(EMPTY, 31)


class CausalTests(unittest.TestCase):
    def setUp(self):
        self.ref = Referee(['raffina', 'paprisu'])
        self.order = 0

    def event(self, kind, player=0, **kw):
        self.order += 1
        return self.ref.apply(dict(type=kind, player=player, frame=self.order, order=0, **kw))

    def start(self, player, chain, links=1, all_clear=False):
        rows = list(EMPTY)
        if not all_clear:
            rows[-1] = 'B.....'
        self.event('place', player, chain=chain,
                   result={'field': rows, 'links': [{'groups': [4], 'colors': 1}] * links})

    def test_cancelled_running_packets_do_not_reappear_on_confirmation(self):
        self.start(0, 'a')
        self.event('link', chain='a', link=1, points=1200)
        self.assertEqual(self.ref.players[1].pending(False), 10)
        self.start(1, 'b')
        reply = self.event('link', 1, chain='b', link=1, points=480)
        self.assertEqual(reply['cancelled'], 4)
        self.event('end', chain='a')
        self.assertEqual(self.ref.players[1].pending(True), 6)
        self.assertEqual(self.ref.players[1].pending(False), 0)
        self.assertEqual(self.ref.players[1].gauge, 0)

    def test_only_fixed_packets_fall_after_nonclear(self):
        self.event('incoming', count=40, confirmed=True, chain='old')
        self.event('incoming', count=9, confirmed=False, chain='running')
        effect = self.event('place', result={'field': EMPTY, 'links': []})
        self.assertEqual(effect['dropped'], 30)
        self.assertEqual(self.ref.players[0].pending(True), 10)
        self.assertEqual(self.ref.players[0].pending(False), 9)
        self.assertEqual(sum(row.count('#') for row in self.ref.players[0].rows), 30)

    def test_a_clear_holds_remaining_garbage(self):
        self.event('incoming', count=20, confirmed=True, chain='old')
        self.start(0, 'a')
        effect = self.event('link', chain='a', link=1, points=40)
        self.assertEqual(effect['cancelled'], 1)
        self.event('end', chain='a')
        self.assertEqual(self.ref.players[0].pending(True), 19)
        self.assertEqual(sum(row.count('#') for row in self.ref.players[0].rows), 0)

    def test_all_clear_requires_real_seed_and_no_tsu_bonus(self):
        self.start(0, 'a', all_clear=True)
        self.event('link', chain='a', link=1, points=40)
        self.event('end', chain='a')
        self.assertTrue(self.ref.players[0].awaiting_seed)
        self.assertEqual(self.ref.players[1].pending(), 0)
        with self.assertRaises(ValueError):
            self.event('place', result={'field': EMPTY, 'links': []})
        seed = list(EMPTY)
        seed[-1] = 'RRGGBB'
        self.event('seed', field=seed)
        self.assertFalse(self.ref.players[0].awaiting_seed)

    def test_failed_event_is_transactional_and_duplicates_rejected(self):
        self.start(0, 'a', links=2)
        before = copy.deepcopy(self.ref.snapshot())
        with self.assertRaises(ValueError):
            self.event('end', chain='a')
        self.assertEqual(before, self.ref.snapshot())
        self.event('link', chain='a', link=1, points=40)
        with self.assertRaises(ValueError):
            self.event('link', chain='a', link=1, points=40)
        with self.assertRaises(ValueError):
            self.ref.apply(dict(type='rate', frame=0, order=0, target_point=10))

    def test_death_and_gauge_configuration(self):
        rows = list(EMPTY)
        for y in range(3, 14):
            rows[y] = '..#...'
        self.event('incoming', count=6, confirmed=True, chain='old')
        effect = self.event('place', result={'field': rows, 'links': []})
        self.assertTrue(effect['dead'])
        with self.assertRaises(ValueError):
            Referee(['raffina', 'paprisu'], gauge_gain_on_offset=1)


class NativeAndProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NATIVE.is_file() or not SOLO.is_file():
            raise RuntimeError('build native and Fever binaries before running tests')
        cls.engine = BattleEngine(NATIVE, SOLO, ROOT / 'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def request(self):
        side = {'character': 'raffina', 'field': list(EMPTY), 'queue': ['2:RG', '2:BY', 'L:RRG'],
                'dropset_index': 0, 'piece_id': 0, 'mode': 'normal', 'gauge': 0,
                'observed_frame': 0, 'phase': 'controllable',
                'moves_since_chain': 0,
                'confirmed': 0, 'unconfirmed': 0, 'remainder': 0, 'garbage_phase': 0}
        return {'protocol_version': 2, 'rule': 'fever_normal_battle', 'match_id': 'test', 'frame': 0,
                'observation': {'frame_before': 0, 'frame_after': 0, 'match_status': 'running'},
                'gauge_gain_on_offset': 0, 'target_point': 120, 'self': side, 'enemy': copy.deepcopy(side),
                'solo_options': {'beam_width': 15, 'beam_depth': 4}}

    def test_native_resolves_links_without_tsu_score(self):
        result = self.engine.native.ask({'op': 'resolve', 'field': list(EMPTY[:-1]) + ['RRRRBB']})
        self.assertEqual(result['links'], [{'groups': [4], 'colors': 1}])
        self.assertEqual(result['field'][-1], '....BB')
        self.assertEqual(self.engine.scoring.chain('raffina', result['links']), [40])

    def test_every_character_piece_cycle_is_preserved_even_equal_j(self):
        for character, pattern in self.engine.patterns.items():
            queue = self.engine.native.ask({'op': 'queue', 'character': character, 'seed': 1, 'count': 64})['queue']
            self.assertEqual(''.join(piece[0] for piece in queue), pattern * 4)
            for piece in queue[:16]:
                self.engine.native.ask({'op': 'placements', 'field': EMPTY, 'piece': piece})

    def test_hidden_row_floating_cells_and_illegal_placement_rejected(self):
        for field in ([ 'R.....'] + list(EMPTY[1:]), list(EMPTY[:12]) + ['R.....', '......']):
            with self.assertRaises(ValueError):
                self.engine.native.ask({'op': 'validate', 'field': field})
        with self.assertRaises(ValueError):
            self.engine.native.ask({'op': 'transition', 'field': EMPTY, 'piece': '0:R', 'x': 5, 'r': 'U'})

    def test_defense_and_reply_identity(self):
        request = self.request()
        request['self']['field'][-1] = 'RRR.BB'
        request['self']['confirmed'] = 12
        reply = self.engine.answer(request)
        self.assertEqual(reply['reason'], 'garbage_state_search')
        self.assertTrue(reply['nuisance_forecast']['horizon_complete'])
        self.assertEqual(reply['decision_identity']['match_id'], 'test')
        self.assertFalse(reply['provenance']['local_steam_verified'])

    def test_common_builder_returns_a_reachable_move(self):
        request = self.request()
        reply = self.engine.answer(request)
        self.engine.native.ask({'op': 'transition', 'field': EMPTY, 'piece': request['self']['queue'][0],
                                'x': reply['x'], 'r': reply['r']})

    def test_shared_policy_accepts_all_characters_and_all_cycle_slots(self):
        for character in self.engine.patterns:
            queue = self.engine.native.ask({'op': 'queue', 'character': character, 'seed': 31, 'count': 18})['queue']
            for index in range(16):
                request = self.request()
                request['self'].update(character=character, dropset_index=index, piece_id=index,
                                       queue=queue[index:index+3])
                reply = self.engine.answer(request)
                with self.subTest(character=character, index=index):
                    native = self.engine.native.ask({'op': 'transition', 'field': EMPTY,
                                                    'piece': queue[index], 'x': reply['x'], 'r': reply['r']})
                    self.assertEqual(reply['next_field'], native['field'])
                    self.assertEqual(reply['next_score'], sum(self.engine.scoring.chain(character, native['links'])))
                    self.assertEqual(reply['decision_identity']['dropset_index'], index)

    def test_no_hidden_information_or_missing_gauge(self):
        for modify in (lambda r: r['self']['queue'].append('2:RG'),
                       lambda r: r['enemy'].update(gauge=None),
                       lambda r: r['enemy'].update(mode='fever'),
                       lambda r: r.update(gauge_gain_on_offset=1),
                       lambda r: r['self'].update(awaiting_seed=True),
                       lambda r: r['self'].update(character='missing')):
            request = self.request()
            modify(request)
            with self.assertRaises(ValueError):
                self.engine.answer(request)

    def test_capture_coherence_pause_and_stale_reply(self):
        request = self.request()
        reply = self.engine.answer(request)
        latest = copy.deepcopy(request)
        latest['frame'] = 3
        latest['observation'].update(frame_before=3, frame_after=3)
        for name in ('self', 'enemy'):
            latest[name]['observed_frame'] = 3
        self.assertTrue(authorize_reply(request, reply, latest))
        latest['self']['confirmed'] = 6
        with self.assertRaises(ValueError):
            authorize_reply(request, reply, latest)
        for modify in (lambda r: r['observation'].update(frame_after=1),
                       lambda r: r['observation'].update(match_status='paused'),
                       lambda r: r['enemy'].update(observed_frame=1),
                       lambda r: r['self'].update(phase='chain')):
            bad = self.request()
            modify(bad)
            with self.assertRaises(ValueError):
                self.engine.answer(bad)

    def test_busy_enemy_is_not_reported_as_ready_to_fire(self):
        request = self.request()
        request['enemy'].update(phase='chain')
        request['enemy']['field'][-1] = 'RRR.BB'
        reply = self.engine.answer(request)
        self.assertFalse(reply['enemy_current_piece_controllable'])
        self.assertEqual(reply['enemy_possible_score_now'], 0)

    def test_two_engine_log_replay_and_tamper_detection(self):
        document = simulate(self.engine, ['raffina', 'schezo'], 1, 45, 48, 48, width=15, depth=4)
        self.assertTrue(replay(document)['state_matches'])
        altered = copy.deepcopy(document)
        altered['events'][0]['effect']['dropped'] = 999
        with self.assertRaises(ValueError):
            replay(altered)


if __name__ == '__main__':
    unittest.main(verbosity=2)
