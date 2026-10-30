"""Known queues and completed preparations survive repeated standing-board reads."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fever_battle.mode_engine import ModeBattleEngine
from fever_fixtures import NATIVE, SOLO, ROOT, request, seed3, side


class PreparationQualityTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT / 'config.json')

    def tearDown(self):
        self.engine.close()

    def prepare(self):
        req = request(side(queue=['2:RY', '2:BB', 'L:RRY']))
        req.update(op='prepare_observed')
        req['solo_options'] = dict(beam_width=80, beam_depth=4)
        result = self.engine.answer(req)
        self.assertTrue(result['prepared'])
        return req, result

    def test_slow_previous_search_does_not_shrink_next_preparation(self):
        queue=self.engine.native.ask(dict(op='queue',character='raffina',seed=1,count=4))['queue']
        req=request(side(queue=queue))
        req['solo_options']=dict(beam_width=80,beam_depth=4)
        self.engine.prepare_ms['normal']=1000000
        reply=self.engine.answer(dict(req,op='prepare',placement=dict(x=0,r='U'),cold_spawn=True))
        self.assertTrue(reply['prepared'])
        self.assertEqual(self.engine.prepared[2]['normal_build_width'],80)
        self.assertFalse(self.engine.prepared[2]['cold_spawn'])

    def test_recorded_late_observations_keep_the_emergency_budget(self):
        fixture=ROOT/'data/fever/golden/preparation-width-regressions.json'
        for case in json.loads(fixture.read_text(encoding='utf-8'))['cases']:
            engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
            try:
                result=engine.answer(case['request'])
                self.assertTrue(result['prepared'],case['line'])
                self.assertEqual(engine.prepared[2]['normal_build_width'],50,case['line'])
                self.assertTrue(engine.prepared[2]['cold_spawn'])
            finally: engine.close()

    def test_observed_preparation_uses_every_supplied_piece_in_both_modes(self):
        for mode in ('normal', 'fever'):
            queue = self.engine.native.ask(dict(op='queue', character='raffina', seed=2, count=12))['queue']
            for count in (1, 2, 3, 4, 12):
                with self.subTest(mode=mode, count=count):
                    own = side(mode, seed3() if mode == 'fever' else None, queue[:count])
                    req = request(own)
                    req.update(op='prepare_observed', match_id=f'{mode}-{count}')
                    req['seed_options'] = dict(width=2, max_nodes=500)
                    result = self.engine.answer(req)
                    self.assertTrue(result['prepared'], result)
                    self.assertEqual(result['searched_visible'], count)
                    self.assertEqual(result['plan']['queue'], queue[:count])

    def test_cold_observation_preserves_completed_width_queue_and_placement(self):
        req, first = self.prepare()
        req['cold_spawn'] = True
        saved = copy.deepcopy(self.engine.prepared)
        execution = copy.deepcopy(self.engine.execution_request)
        cost = dict(self.engine.prepare_ms)
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            again = self.engine.answer(req)
        build.assert_not_called()
        self.assertEqual(self.engine.prepared, saved)
        self.assertEqual(self.engine.execution_request['self'], execution['self'])
        self.assertEqual(self.engine.prepare_ms, cost)
        self.assertEqual(self.engine.prepared[2]['normal_build_width'], 80)
        self.assertEqual(again['searched_visible'], 3)
        self.assertEqual(again['plan']['placement'], first['plan']['placement'])

    def test_changed_board_known_piece_rate_or_settings_still_refreshes(self):
        for change in ('board', 'third_piece', 'rate', 'settings'):
            with self.subTest(change=change):
                req, _ = self.prepare()
                if change == 'board':
                    req['self']['field'][-1] = 'G.....'
                elif change == 'third_piece':
                    req['self']['queue'][2] = 'L:GGY'
                elif change == 'rate':
                    req['target_point'] += 1
                else:
                    req['solo_options']['beam_width'] += 1
                with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
                    result = self.engine.answer(req)
                self.assertTrue(result['prepared'])
                if change == 'rate':
                    # Rates invalidate tactics; the unchanged solo board can still be cached.
                    self.assertEqual(self.engine.execution_request['target_point'], req['target_point'])
                else:
                    build.assert_called_once()

    def test_transferred_preparation_keeps_its_execution_request(self):
        req, first = self.prepare()
        state = copy.deepcopy(first['prepared_state'])
        self.engine.close()
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT / 'config.json')
        req.update(prepared_state=state, cold_spawn=True)
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            result = self.engine.answer(req)
        build.assert_not_called()
        self.assertEqual(result['prepared_state']['execution_request']['self'], state['execution_request']['self'])
        self.assertEqual(result['plan']['placement'], first['plan']['placement'])

    def test_repeated_placement_preparation_does_not_replace_completed_search(self):
        req = request(side(queue=['2:RY', '2:BB', 'L:RRY']))
        req['solo_options'] = dict(beam_width=80, beam_depth=4)
        first = self.engine.answer(req)
        req['self']['queue'].append('2:GY')
        req.update(op='prepare', placement=dict(x=first['x'], r=first['r']))
        full = self.engine.answer(req)
        self.engine.prepare_ms['normal'] = 5000
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as build:
            again = self.engine.answer(req)
        build.assert_not_called()
        self.assertEqual(again['plan']['placement'], full['plan']['placement'])
        self.assertEqual(again['searched_visible'], 3)
        self.assertEqual(self.engine.prepared[2]['normal_build_width'], 80)


if __name__ == '__main__':
    unittest.main()
