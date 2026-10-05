"""Mode boundaries, queue routing, deadlines and real native seed transitions."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode import ModeReferee, next_seed
from fever_battle.model import EMPTY, Scoring
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply
from fever_battle.replay import replay
from fever_battle.reference_seeds import decode
from fever_battle.mode_tactics import seed_strategy
from fever_battle.worker import JsonProcess

NATIVE = Path(os.environ.get('AMA_BATTLE_NATIVE', ROOT / 'bin/t14/fever_battle.exe'))
SOLO = ROOT / 'bin/fever/fever.exe'


def seed3():
    rows = list(EMPTY)
    # Public flat-stacking seed, canonical color labels; not a Steam capture.
    rows[-7:] = ['.....R', '.....R', '.....B', '.....B', '...BRR', '..YYBB', '..YBRR']
    return rows


def side(mode='normal', rows=None, queue=None):
    return dict(character='raffina', field=list(rows or EMPTY), mode=mode, gauge=7 if mode == 'fever' else 0,
                observed_frame=0, phase='controllable', moves_since_chain=0,
                dropset_index=0, piece_id=0, queue=queue or ['2:RY'], confirmed=0, unconfirmed=0,
                remainder=0, garbage_phase=0, mode_generation=1 if mode == 'fever' else 0, seed_id=1,
                prepared_frames=900, remaining_frames=900 if mode == 'fever' else 0,
                clock_running=mode == 'fever', seed_base=3, seed_chain=3,
                stored_field=list(EMPTY) if mode == 'fever' else None,
                normal_confirmed=0, normal_unconfirmed=0, fever_confirmed=0, fever_unconfirmed=0)


def request(own=None, enemy=None):
    return dict(protocol_version=3, rule='fever_battle', match_id='mode-test', frame=0,
                observation=dict(frame_before=0, frame_after=0, match_status='running'),
                target_point=120, gauge_gain_on_offset=1,
                clock_policy=dict(count_chain_frames=True), self=own or side('fever', seed3()),
                enemy=enemy or side(), seed_options=dict(budget_ms=500, max_nodes=20000),
                solo_options=dict(beam_width=10, beam_depth=3))


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.ref = ModeReferee(['raffina', 'ally'])
        self.order = 0

    def event(self, kind, player=0, frame=0, **kwargs):
        self.order += 1
        return self.ref.apply(dict(type=kind, player=player, frame=frame, order=self.order, **kwargs))

    def chain(self, count=1, player=0, all_clear=False, frame=0, points=40):
        name = str(self.order)
        rows = list(EMPTY)
        if not all_clear:
            rows[-1] = '.Y....'
        self.event('place', player, frame, chain=name, result=dict(field=rows, links=[{}]*count))
        for link in range(1, count+1):
            self.event('link', player, frame, chain=name, link=link, points=points)
        return name

    def enter(self, player=0, frame=0):
        self.ref.players[player].gauge = 7
        return self.event('enter', player, frame, clock_running=True)

    def test_offset_per_link_and_enemy_preparation(self):
        self.event('incoming', count=50, confirmed=True, chain='attack', destination='normal')
        name = self.chain(7)
        self.assertEqual(self.ref.players[0].gauge, 7)
        self.assertEqual(self.ref.players[1].prepared_frames, 1320)
        with self.assertRaises(ValueError):
            self.event('enter', clock_running=True)
        self.event('end', chain=name)
        self.event('enter', clock_running=True)
        self.assertEqual(self.ref.players[0].mode, 'fever')

    def test_zero_gain_regression_and_no_unearned_gauge(self):
        self.ref = ModeReferee(['raffina', 'ally'], gauge_gain_on_offset=0)
        self.event('incoming', count=30, confirmed=True, chain='attack', destination='normal')
        self.chain(2, points=40)
        self.assertEqual(self.ref.players[0].gauge, 0)
        self.assertEqual(self.ref.players[1].prepared_frames, 1020)

    def test_preserve_normal_board_and_merge_both_queues(self):
        self.ref.players[0].rows[-1] = 'G.....'
        self.ref.players[0].garbage_phase = 4
        self.event('incoming', count=8, confirmed=True, chain='old', destination='normal')
        self.enter()
        self.event('incoming', count=3, confirmed=True, chain='new', destination='fever')
        self.event('clock', remaining_frames=0, running=False)
        self.event('exit')
        p = self.ref.players[0]
        self.assertEqual(p.rows[-1], 'G.....')
        self.assertEqual(p.pending(True), 11)
        self.assertEqual((p.garbage_phase, p.gauge, p.prepared_frames), (4, 0, 900))

    def test_fever_offsets_active_before_held_and_drops_only_active(self):
        self.event('incoming', count=5, confirmed=True, chain='held', destination='normal')
        self.enter()
        self.event('seed', field=seed3(), seed_id=1, seed_chain=5)
        self.event('incoming', count=2, confirmed=True, chain='active', destination='fever')
        name = self.chain(points=360)
        self.assertEqual(self.ref.players[0].active_pending(), 0)
        self.assertEqual(self.ref.players[0].pending(), 4)
        self.event('end', chain=name)
        self.event('seed', field=seed3(), seed_id=2, seed_chain=3)
        effect = self.event('place', result=dict(field=seed3(), links=[]))
        self.assertEqual(effect['dropped'], 0)
        self.assertEqual(self.ref.players[0].pending(), 4)

    def test_confirmation_survives_recipient_mode_switch(self):
        name = self.chain(points=600, player=1)
        self.enter()
        self.event('end', player=1, chain=name)
        self.assertEqual(self.ref.players[0].held_packets[0].count, 5)
        self.assertTrue(self.ref.players[0].held_packets[0].confirmed)

    def test_remainder_cursor_continues_through_fever_drop_and_return(self):
        self.ref.players[0].garbage_phase = 4
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        self.event('incoming', count=1, confirmed=True, chain='active', destination='fever')
        effect = self.event('place', result=dict(field=seed3(), links=[]))
        self.assertEqual(effect['garbage_phase'], 5)
        self.event('clock', remaining_frames=0, running=False)
        self.event('exit')
        self.assertEqual(self.ref.players[0].garbage_phase, 5)

    def test_timer_stop_resume_and_no_revival_after_expiry(self):
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        self.event('clock', frame=100, remaining_frames=800, running=False)
        self.event('tick', frame=200)
        self.assertEqual(self.ref.players[0].remaining_frames, 800)
        self.event('clock', frame=200, remaining_frames=800, running=True)
        name = self.chain(3, frame=200, all_clear=True)
        self.event('end', frame=1001, chain=name)
        self.assertEqual(self.ref.players[0].remaining_frames, 0)
        self.assertFalse(self.ref.players[0].awaiting_seed)
        self.event('exit', frame=1001)

    def test_any_clear_requires_observed_next_seed(self):
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        name = self.chain(5)
        effect = self.event('end', chain=name)
        self.assertEqual(effect['seed_chain'], 6)
        self.assertEqual(effect['remaining_frames'], 990)
        self.assertTrue(effect['awaiting_seed'])
        before = self.ref.snapshot()
        with self.assertRaises(ValueError):
            self.event('seed', field=seed3(), seed_id=1, seed_chain=6)
        self.assertEqual(self.ref.snapshot(), before)
        with self.assertRaises(ValueError):
            self.event('place', result=dict(field=seed3(), links=[]))
        self.event('seed', field=seed3(), seed_id=2, seed_chain=6)

    def test_failure_rules_and_limits(self):
        self.assertEqual([next_seed(7, n) for n in (7, 6, 5, 4)], [8, 7, 6, 5])
        self.assertEqual(next_seed(4, 1), 3)
        self.assertEqual(next_seed(9, 9, True), 12)
        self.assertEqual(next_seed(15, 15, True), 15)
        self.assertEqual(next_seed(5, 3, displayed=7), 4)
        self.assertEqual(next_seed(5, 1, displayed=7), 3)

    def test_all_clear_entry_boost_and_time_cap(self):
        self.ref.players[0].prepared_frames = 1790
        name = self.chain(all_clear=True)
        self.event('end', chain=name)
        effect = self.enter()
        self.assertEqual(effect['seed_chain'], 7)
        self.assertEqual(effect['remaining_frames'], 1800)
        self.assertEqual(self.ref.players[0].seed_base, 5)

    def test_normal_all_clear_seed_consumes_entry_bonus(self):
        name = self.chain(all_clear=True)
        self.event('end', chain=name)
        self.event('seed', field=seed3(), seed_chain=4, seed_id=1)
        self.assertEqual(self.enter()['seed_chain'], 5)

    def test_invalid_event_rolls_back_clock_and_mode_and_replay(self):
        self.event('incoming', count=50, confirmed=True, chain='attack', destination='normal')
        name = self.chain(7)
        self.event('end', chain=name)
        self.event('enter', clock_running=True)
        before = self.ref.snapshot()
        with self.assertRaises(ValueError):
            self.event('exit', frame=20)
        self.assertEqual(self.ref.snapshot(), before)
        self.assertTrue(replay(dict(characters=['raffina', 'ally'], events=self.ref.log,
                                    state=self.ref.snapshot()))['state_matches'])


class NativeModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_tables_and_mode_dependent_score(self):
        score = Scoring()
        self.assertEqual(score.link('raffina', 10, [4], 1, 'fever'), 6760)
        self.assertEqual(score.link('paprisu', 17, [4], 1, 'fever'), 16400)
        self.assertEqual(score.link('schezo', 17, [4], 1, 'fever'), 13120)
        for c in score.data['characters']:
            self.assertEqual(len(score.data['characters'][c]['fever']), 17)
        with self.assertRaises(ValueError):
            score.link('raffina', 18, [4], 1, 'fever')

    def test_three_chain_native_path_matches_scoring(self):
        req = request()
        reply = self.engine.answer(req)
        self.assertTrue(reply['seed_forecast']['solved'])
        self.assertGreaterEqual(reply['chain'], 3)
        step = self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:RY',
                                          x=reply['x'], r=reply['r']))
        self.assertEqual(step['field'], reply['next_field'])
        self.assertEqual(self.engine.scoring.chain('raffina', step['links'], 'fever'), reply['link_points'])
        self.assertTrue(authorize_mode_reply(req, reply, copy.deepcopy(req)))

    def test_two_move_solution_and_stop_at_first_clear(self):
        req = request(side('fever', seed3(), ['2:GG', '2:RY']))
        reply = self.engine.answer(req)
        forecast = reply['seed_forecast']
        self.assertTrue(forecast['solved'])
        self.assertEqual(len(forecast['path']), 2)
        self.assertEqual(forecast['path'][0]['chain'], 0)
        self.assertGreaterEqual(forecast['path'][1]['chain'], 3)

    def test_cutoff_returns_legal_fallback_and_no_hidden_colors(self):
        req = request(side('fever', queue=['2:GY']))
        req['seed_options']['max_nodes'] = 1
        reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        self.assertFalse(reply['seed_forecast']['solved'])
        self.assertTrue(reply['seed_forecast']['cutoff'])
        self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:GY',
                                    x=reply['x'], r=reply['r']))
        req['self']['queue'] = ['2:GY'] * 4
        with self.assertRaises(ValueError):
            self.engine.answer(req)

    def test_mode_or_seed_change_rejects_old_input(self):
        req = request()
        reply = self.engine.answer(req)
        for key in ('seed_id', 'mode_generation'):
            latest = copy.deepcopy(req)
            latest['self'][key] += 1
            with self.assertRaises(ValueError):
                authorize_mode_reply(req, reply, latest)
        latest = copy.deepcopy(req)
        latest['frame'] = 5
        latest['observation'].update(frame_before=5, frame_after=5)
        for name in ('self', 'enemy'):
            latest[name]['observed_frame'] = 5
        latest['self']['remaining_frames'] -= 5
        self.assertTrue(authorize_mode_reply(req, reply, latest))

    def test_short_timer_wait_and_expired_timer_never_place(self):
        req = request()
        req['self']['remaining_frames'] = 1
        self.assertEqual(self.engine.answer(req)['action'], 'wait')
        req['self']['remaining_frames'] = 0
        self.assertEqual(self.engine.answer(req)['action'], 'wait')

    def test_normal_return_uses_normal_scoring_with_fever_enemy(self):
        req = request(side(), side('fever', seed3()))
        req['self']['field'][-1] = 'RRR.BB'
        req['self']['queue'] = ['2:RG']
        reply = self.engine.answer(req)
        self.assertEqual(reply['mode'], 'normal')
        result = self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:RG',
                                            x=reply['x'], r=reply['r']))
        self.assertEqual(reply['link_points'], self.engine.scoring.chain('raffina', result['links']))

    def test_active_and_held_queues_and_observation_fields_required(self):
        req = request()
        req['self']['normal_confirmed'] = 100
        reply = self.engine.answer(req)
        self.assertTrue(reply['seed_forecast']['solved'])
        for step in reply['seed_forecast']['path']:
            self.assertEqual(step['dropped'], 0)
        for key in ('stored_field', 'seed_id', 'mode_generation', 'clock_running'):
            invalid = copy.deepcopy(req)
            del invalid['self'][key]
            with self.assertRaises((ValueError, KeyError)):
                self.engine.answer(invalid)

    def test_all_characters_and_cycle_positions_in_fever_mode(self):
        for character in self.engine.patterns:
            queue = self.engine.native.ask(dict(op='queue', character=character, seed=1, count=16))['queue']
            for index, piece in enumerate(queue):
                own = side('fever', seed3(), [piece])
                own.update(character=character, piece_id=index, dropset_index=index)
                req = request(own)
                reply = self.engine.answer(req)
                self.assertEqual(reply['action'], 'place', (character, index))
                actual = self.engine.native.ask(dict(op='transition', field=own['field'], piece=piece,
                                                     x=reply['x'], r=reply['r']))
                self.assertEqual(actual['field'], reply['next_field'])
                self.assertTrue(authorize_mode_reply(req, reply, copy.deepcopy(req)))

    def test_normal_offset_forecasts_fever_entry(self):
        own = side()
        own['gauge'] = 6
        own['field'][-1] = 'RRR.BB'
        own['confirmed'] = own['normal_confirmed'] = 30
        reply = self.engine.answer(request(own))
        self.assertTrue(reply['entry_pending_after_chain'])
        self.assertEqual(reply['gauge_forecast']['gauge_after'], 7)

    def test_reference_metadata_and_decoder_do_not_guess_missing_entries(self):
        data = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['seeds']), 50)
        self.assertEqual([(p['kind'],p['seed_chain']) for p in data['missing']], [('kaidan',4),('zabuton',6)])
        self.assertFalse(data['color_mapping_verified_on_steam'])
        for seed in data['seeds']:
            self.assertEqual(decode(seed['encoding']), seed['field'])
            self.assertEqual(self.engine.native.ask(dict(op='resolve',field=seed['field']))['links'], [])
        for bad in ('a78x', 'a0b78', 'a999999999999', 'a77'):
            with self.assertRaises(ValueError):
                decode(bad)

    def test_shared_strategy_distinguishes_pressure_and_extension(self):
        own, enemy = side('fever'), side('fever')
        self.assertEqual(seed_strategy(own, enemy, 100)[0], 'extend')
        own['fever_confirmed'] = 1
        self.assertEqual(seed_strategy(own, enemy, 100)[0], 'quick')
        own['fever_confirmed'] = 0
        own['remaining_frames'] = 120
        self.assertEqual(seed_strategy(own, enemy, 100)[0], 'quick')

    def test_countdown_can_finish_active_chain_but_never_accept_stale_deadline(self):
        req = request()
        req['self']['remaining_frames'] = 50
        reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        self.assertTrue(reply['seed_forecast']['solved'])
        latest = copy.deepcopy(req)
        elapsed = 15
        latest['frame'] = elapsed
        latest['observation'].update(frame_before=elapsed, frame_after=elapsed)
        for who in ('self', 'enemy'):
            latest[who]['observed_frame'] = elapsed
        latest['self']['remaining_frames'] -= elapsed
        with self.assertRaises(ValueError):
            authorize_mode_reply(req, reply, latest)

    def test_json_lines_refuses_non_object_and_keeps_session_alive(self):
        with JsonProcess([sys.executable, '-m', 'fever_battle.mode_engine', '--native', NATIVE,
                          '--solo', SOLO, '--config', ROOT/'config.json'], cwd=ROOT) as engine:
            with self.assertRaises(ValueError):
                engine.ask(['not', 'an', 'observation'])
            self.assertEqual(engine.ask(request())['action'], 'place')


if __name__ == '__main__':
    unittest.main()
