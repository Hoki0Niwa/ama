"""Observed mode clocks, seed turnover and exact-edge calibration regressions."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.calibrate_mode import measure
from fever_battle.model import Scoring, EMPTY
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.seed_solver import SeedSolver
from fever_battle.timing import ChainTiming
from fever_battle.worker import JsonProcess

NATIVE = Path(os.environ.get('AMA_BATTLE_NATIVE', ROOT/'bin/fever_battle/fever_battle.exe'))
REPORT = ROOT/'data/fever/baselines/2026-10-06-fever-chain-timing.json'


class ClockTests(unittest.TestCase):
    def test_recorded_links_and_terminal_ends_use_fever_clock(self):
        report = json.loads(REPORT.read_text(encoding='utf-8'))
        clock = ChainTiming.for_mode('fever')
        count = 0
        for kind in ('links', 'terminals'):
            for record in report[kind]:
                if record['mode'] != 'fever':
                    continue
                count += 1
                predicted = clock.duration(record['max_fall'], record, terminal=kind=='terminals')
                self.assertLessEqual(abs(predicted-record['duration_frames']), 2)
        self.assertEqual(count, 55)
        for mode in ('normal', 'fever'):
            clock = ChainTiming.for_mode(mode)
            for record in report['locks']:
                if record['mode'] == mode:
                    self.assertEqual(clock.first_link_frames+clock.split_extra_frames[record['split_rows']], record['duration_frames'])
            for record in report['placements']:
                if record['mode'] == mode:
                    self.assertEqual(clock.spawn_frames+clock.split_extra_frames[record['split_rows']], record['duration_frames'])

    def test_faster_chain_and_longer_seed_exchange_are_distinct(self):
        normal, fever = ChainTiming(), ChainTiming.for_mode('fever')
        features = dict(moving_distances_by_column=[[1,1,1,1],[],[],[],[],[]])
        self.assertEqual((normal.duration(1, features), fever.duration(1, features)), (76,61))
        self.assertEqual((normal.duration(0, terminal=True), fever.duration(0, terminal=True)), (55,43))
        timeline = fever.timeline([40], [0])
        self.assertEqual(timeline['end_frame'], 43)
        self.assertEqual(timeline['ready_frame'], 143)
        self.assertIn('estimated', timeline['readiness_status'])
        report = json.loads(REPORT.read_text(encoding='utf-8'))
        delays = [r['end_to_ready_frames'] for r in report['ready'] if r['mode']=='fever']
        self.assertEqual(delays, [91,98,94])
        self.assertTrue(all(delay <= fever.chain_ready_frames for delay in delays))

    def test_explicit_linear_simulation_clock_is_preserved(self):
        clock = ChainTiming(pop_frames=1, settle_frames=0, fall_frames_per_row=0, spawn_frames=2)
        self.assertEqual(clock.duration(10), 1)
        self.assertEqual(clock.native()['chain_ready_frames'], 2)
        self.assertEqual(clock.effective_status, 'explicit_linear_costs')
        with self.assertRaises(ValueError):
            ChainTiming.for_mode('unknown')


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = JsonProcess([NATIVE.resolve()])
        cls.scoring = Scoring()

    @classmethod
    def tearDownClass(cls):
        cls.native.close()

    def test_mode_prediction_changes_delivery_onsets_without_changing_scoring_mode(self):
        board = list(EMPTY)
        board[-2:] = ['BBB...', 'RRRR..']
        # Exercise the actual protocol-3 prediction function without starting the solo worker.
        engine = object.__new__(ModeBattleEngine)
        engine.native, engine.scoring = self.native, self.scoring
        normal = engine._prediction('raffina', board, 'normal')
        fever = engine._prediction('raffina', board, 'fever')
        self.assertLess(fever['end_frame'], normal['end_frame'])
        self.assertIn('fever_measured', fever['mode_timing_status'])
        self.assertEqual(fever['points'], self.scoring.chain('raffina', self.native.ask(dict(op='resolve', field=board))['links'], 'fever'))

    def test_seed_search_end_and_next_seed_deadline_match_mode_prediction(self):
        field = list(EMPTY)
        field[-7:] = ['.....R','.....R','.....B','.....B','...BRR','..YYBB','..YBRR']
        own = dict(character='raffina', field=field, queue=['2:RY', '2:GG'],
            fever_confirmed=0, fever_unconfirmed=0, normal_confirmed=0, normal_unconfirmed=0,
            remainder=0, garbage_phase=0, remaining_frames=900, seed_chain=3)
        solver = SeedSolver(self.native, self.scoring)
        result = solver.solve(own, 120, True, dict(budget_ms=500))
        first = result['choice']
        transition = self.native.ask(dict(op='transition', field=field, piece='2:RY', x=first['x'], r=first['r']))
        clock = ChainTiming.for_mode('fever')
        fire = 14 + clock.first_link_frames + clock.split_extra_frames[max(transition['split_distances'])]
        prediction = clock.timeline(first['link_points'], transition['fall_distances'], transition['fall_features'], fire)
        self.assertEqual(first['fire_at'], fire)
        self.assertEqual(first['end_at'], prediction['end_frame'])
        self.assertTrue(first['next_seed_input_fits'])
        # The chain fits, but the next seed does not fit its measured exchange budget.
        own['remaining_frames'] = first['end_at'] + 90
        result = solver.solve(own, 120, True, dict(budget_ms=500),
                              allowed=[dict(x=first['x'],r=first['r'])])
        self.assertTrue(result['choice']['completed_before_timeout'])
        self.assertFalse(result['choice']['next_seed_input_fits'])
        self.assertIn('estimated', result['seed_exchange_status'])


class CaptureTests(unittest.TestCase):
    def capture(self, missing_onset=False, wrong_score=False, reset=False, cpu=False):
        features = dict(max_fall=0, moving_puyos=0, moving_columns=0, distance_sum=0,
            cleared_including_garbage=4, moving_distances_by_column=[[]]*6)
        class Native:
            def ask(self, request):
                return dict(links=[dict(groups=[4],colors=1)], fall_features=[features])
        packets = []
        for frame, link, phase in ((0,0,6),(1,1,6),(43,1,6),(44,0,6),(141,0,1),(142,0,2)):
            side = dict(address='a', frame=frame, cpu=cpu, player_state=1, mode='fever', character='raffina',
                active=dict(placed=1), link=link, mode_phase=phase, field_phase=0,
                field_settled=frame>=44, total_score=(41 if wrong_score else 40) if frame else 0,
                drawn_field_codes=[[0]*6]*13+[[1,1,1,1,0,0]],
                fever_nuisance=dict(confirmed=0,unconfirmed=0))
            if reset and frame>=43:
                side['address']='b'
            if missing_onset and frame==0:
                continue
            packets.append(dict(event='sample',frame_before=frame,frame_after=frame,
                                players=[side,dict(cpu=True)]))
        data = ''.join(json.dumps(p)+'\n' for p in packets)
        scoring = Scoring()
        with patch.object(Path, 'open', return_value=io.StringIO(data)), \
             patch('fever_battle.calibrate_mode.file_sha256', return_value='test'):
            return measure(['test'], Native(), scoring)

    def test_exact_endpoints_measure_seed_exchange_without_requiring_every_interior_frame(self):
        result = self.capture()
        self.assertEqual(result['terminals'][0]['duration_frames'], 43)
        self.assertEqual(result['ready'][0]['end_to_ready_frames'], 98)

    def test_late_onset_wrong_score_reset_and_cpu_do_not_become_timing_samples(self):
        for option in ('missing_onset','wrong_score','reset','cpu'):
            with self.subTest(option=option):
                result = self.capture(**{option:True})
                self.assertEqual(result['terminals'], [])
                self.assertEqual(result['ready'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
