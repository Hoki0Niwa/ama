"""Strategy selection, preparation reuse and the no-extra-search input path."""
import copy
import unittest
from unittest.mock import patch
from fever_fixtures import ROOT, NATIVE, SOLO, request, side
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply
from fever_battle import tactical_options


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    def tearDown(self):
        self.engine.close()

    def req(self, strategy):
        req = request(side(queue=['2:RY','2:BB','L:RRY']))
        req['normal_tactics'] = dict(strategy=strategy)
        return req

    def test_bad_strategy_rejected_before_search(self):
        for value in (None, True, 'automatic', [], {}):
            with self.assertRaises(ValueError):
                self.engine.answer(self.req(value))

    def test_prepared_decision_costs_no_search_for_every_strategy(self):
        for name in ('mainline','brawl','hybrid'):
            req = self.req(name)
            req['op'] = 'prepare_observed'
            self.assertTrue(self.engine.answer(req)['prepared'])
            req.pop('op')
            with patch.object(self.engine.native, 'ask', wraps=self.engine.native.ask) as native:
                reply = self.engine.answer(req)
            self.assertTrue(reply['search_reused'])
            self.assertEqual(reply['search_ms'], 0)
            self.assertFalse(any(c.args[0].get('op') in ('solo','tactics') for c in native.call_args_list))
            latest = copy.deepcopy(req)
            latest['normal_tactics']['strategy'] = 'hybrid' if name != 'hybrid' else 'brawl'
            with self.assertRaises(ValueError):
                authorize_mode_reply(req, reply, latest)

    def test_unprepared_normal_board_does_not_start_discretionary_search(self):
        for name in ('brawl','hybrid'):
            with patch.object(self.engine.native, 'ask', wraps=self.engine.native.ask) as native:
                reply = self.engine.answer(self.req(name))
            self.assertEqual(reply['action'], 'place')
            self.assertFalse(any(c.args[0].get('op') == 'tactics' for c in native.call_args_list))

    def test_pressure_preparation_reaches_next2_without_more_nodes(self):
        for strategy in ('brawl','hybrid'):
            calls=[]
            ask=self.engine.native.ask
            def capture(req,*args,**kwargs):
                reply=ask(req,*args,**kwargs)
                if req.get('op')=='tactics': calls.append(reply)
                return reply
            req=self.req(strategy)
            with patch.object(self.engine.native,'ask',side_effect=capture):
                self.engine.answer(dict(req,op='prepare_observed'))
            self.assertTrue(calls)
            self.assertEqual(calls[-1]['completed_depth'],3)
            self.assertLessEqual(calls[-1]['expanded'],512)
            self.assertFalse(calls[-1]['cutoff'])

    def test_pace_update_keeps_the_prepared_attack_without_another_search(self):
        import json
        req=json.loads((ROOT/'data/fever/golden/midgame-pressure-issued.json').read_text(encoding='utf-8'))['request']
        for strategy in ('brawl','hybrid'):
            req['normal_tactics']=dict(strategy=strategy)
            self.engine.pace_samples={}
            self.engine.answer(dict(req,op='prepare_observed'))
            expected=copy.deepcopy(self.engine.prepared[2])
            self.engine.pace_samples['normal']=[55,56,57]
            with patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as native:
                reply=self.engine.answer(req)
            self.assertTrue(reply['search_reused'])
            self.assertEqual(reply['reason'],expected['reason'])
            self.assertEqual((reply['x'],reply['r']),(expected['x'],expected['r']))
            self.assertFalse(any(c.args[0].get('op') in ('tactics','solo') for c in native.call_args_list))

    def test_piece_pace_is_not_counted_again_for_preparation_and_execution(self):
        for piece,frame in enumerate((0,50,104,160,230)):
            req=self.req('hybrid');req['frame']=frame;req['self']['piece_id']=piece
            for op in ('prepare','prepare_observed','think'):
                self.engine._observe_pace(req,req['self'],op)
        self.assertEqual(self.engine.pace_samples['normal'],[50,54,56,70])
        self.assertEqual(self.engine.pace,56)

    def test_hybrid_preserves_main_and_limits_catalyst_tree(self):
        req = self.req('hybrid')
        policy = tactical_options.resolve(self.engine.policy['normal_tactics'], req, req['self'], req['enemy'])
        self.assertEqual(policy['pressure']['min_remaining_chain'], 5)
        self.assertEqual(policy['pressure']['chain_reserve_step'], 8)
        self.assertTrue(policy['invite_fever'])
        self.assertLessEqual(policy['counter_read']['max_nodes'], 96)
        self.assertLessEqual(policy['max_nodes'], self.engine.policy['normal_tactics']['max_nodes'])


if __name__ == '__main__':
    unittest.main()
