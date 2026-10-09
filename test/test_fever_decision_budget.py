"""Bound live work and preserve the large-chain objective after a small clear."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, request, side, seed3, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply


class DecisionBudgetTests(unittest.TestCase):
    def setUp(self): self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    def tearDown(self): self.engine.close()

    def test_five_chain_all_clear_does_not_release_the_opening_target(self):
        own = side('normal', seed3(), ['2:RY']); own['normal_chain_max'] = 5
        options = self.engine._normal_options(request(own), own)
        self.assertEqual(options['trigger'], 15)
        own['mode_generation'] = 2
        options = self.engine._normal_options(request(own), own)
        self.assertEqual((options['trigger'], options['build_chain']), (19, 14))

    def test_second_target_is_independent_and_only_applies_after_opening(self):
        own = side('normal', seed3(), ['2:RY'])
        req = request(own); req['second_target_chain'] = 10
        self.assertEqual(self.engine._normal_options(req, own)['trigger'], 15)
        own['mode_generation'] = 2
        options = self.engine._normal_options(req, own)
        self.assertEqual((options['build_chain'], options['trigger']), (10, 10))
        req['second_target_chain'] = None
        options = self.engine._normal_options(req, own)
        self.assertEqual((options['build_chain'], options['trigger']), (19, 19))

    def test_an_end_without_remaining_attack_never_runs_the_garbage_fallback(self):
        own = side('normal', seed3(), ['2:BB']); own['character'] = 'arle'
        with patch.object(self.engine, '_enemy_events', return_value=[dict(type='end', frame=20)]), \
             patch.object(self.engine, '_tactics', return_value=None), \
             patch.object(self.engine.garbage_search, 'search') as search:
            reply = self.engine.answer(request(own))
        search.assert_not_called()
        self.assertEqual(reply['reason'], 'normal_build_or_fire')

    def test_legacy_live_budget_does_not_truncate_solo_or_tactics(self):
        own = side('normal', seed3(), ['2:BB', '2:RY', '2:GB']); own['character'] = 'arle'
        req = request(own); req.update(decision_budget_ms=100)
        req['solo_options'] = dict(beam_width=20, beam_depth=4)
        with patch.object(self.engine.native, 'ask', wraps=self.engine.native.ask) as ask:
            reply = self.engine.answer(req)
        calls = [c.args[0] for c in ask.call_args_list]
        solo = next(c['request'] for c in calls if c['op'] == 'solo')
        self.assertNotIn('budget_ms', solo)
        tactical = next(c for c in calls if c['op'] == 'tactics')
        self.assertFalse(self.engine.planning_deadline)
        placements = self.engine.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))
        self.assertIn((reply['x'], reply['r']), [(p['x'], p['r']) for p in placements['placements'] if not p['dead']])

    def test_constructor_ignores_one_millisecond_cpu_limit(self):
        own=side('normal',['......']*14,['2:RY','2:GB','2:YB']);own['character']='arle'
        args=dict(rule='fever',solo=True,self=dict(field=own['field'],queue=own['queue']),character='arle',dropset_index=0,
                  beam_width=20,beam_depth=4,trigger=19,stretch=True)
        ordinary=self.engine.solo.ask(args)
        clipped=self.engine.solo.ask(dict(args,budget_ms=1))
        self.assertEqual({k:v for k,v in ordinary.items() if k != 'search_ms'},
                         {k:v for k,v in clipped.items() if k != 'search_ms'})
        self.assertEqual(clipped['search_virtual_depths'],[4]*6)

    def test_long_match_does_not_lower_opening_chain_target(self):
        own=side('normal',['......']*14,['2:RY']);own['moves_since_chain']=200
        opts=self.engine._normal_options(request(own),own)
        self.assertEqual((opts['trigger'],opts['build_chain'],opts['patience']),(15,15,0))

    def test_late_gauge_accounting_does_not_cancel_input_but_fever_entry_does(self):
        req = request(side('normal', seed3(), ['2:BB']))
        reply = self.engine.answer(req)
        latest = copy.deepcopy(req); latest['self'].update(gauge=1, normal_chain_max=5, moves_since_chain=0)
        self.assertTrue(authorize_mode_reply(req, reply, latest))
        latest['self']['gauge'] = 7
        with self.assertRaises(ValueError): authorize_mode_reply(req, reply, latest)

    def test_legacy_garbage_budget_does_not_truncate_visible_layers(self):
        own = side('normal', seed3(), ['2:BB', '2:RY', '2:GB']); own['character'] = 'arle'
        result = self.engine.garbage_search.search('arle', own['field'], own['queue'],
            12, 0, 0, 120, 0, width=12, budget_ms=1)
        self.assertFalse(result['budget_exhausted'])
        self.assertEqual(result['completed_moves'], 3)
        self.assertEqual(len(result['path']), 3)

    def test_builder_can_clear_one_useless_group_without_releasing_the_main_target(self):
        own = side('normal', seed_with_small_green(), ['2:GY', '2:RY', '2:BB'])
        own.update(character='arle', mode_generation=2)
        options = self.engine._normal_options(request(own), own)
        result = self.engine._solo_build(own, options)
        after = self.engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                            x=result['x'], r=result['r']))
        self.assertEqual(len(after['links']),1)
        self.assertFalse(result['fire'])
        self.assertEqual(options['build_chain'],14)

    def test_no_garbage_rescue_is_a_placement_reply_not_a_fatal_error(self):
        rows = ['......']*4 + ['RGRGRG', 'GRGRGR']*5
        own = side('normal', rows, ['2:BB']); own.update(character='arle', confirmed=30, normal_confirmed=30)
        req = request(own); req['gauge_gain_on_offset'] = 0
        with patch('fever_battle.mode_engine.fast_finish', return_value=None):
            reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        self.assertEqual(reply['reason'], 'no_surviving_garbage_reply')
        self.assertTrue(reply['selected_move_loses'])
        self.assertIsNone(reply['next_field'])

if __name__ == '__main__': unittest.main()
