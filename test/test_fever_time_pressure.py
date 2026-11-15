"""Answering an attack in full, hurrying the second against an opponent in Fever, and keeping clears off the board."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, request, seed3, side
from fever_battle import strategy, tactical_options
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.worker import JsonProcess


class AttackAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def req(self, name):
        req = request(side(), side())
        req['normal_tactics'] = dict(strategy=name)
        return req

    def test_pressure_strategies_answer_an_attack_with_the_baseline_search(self):
        for name in ('brawl', 'hybrid'):
            quiet = self.req(name)
            self.assertTrue(strategy.profile(quiet)['pressure_style'])
            narrow = tactical_options.resolve(self.engine.policy['normal_tactics'], quiet, quiet['self'], quiet['enemy'])
            full = []
            for change in ({'enemy_chain': {'chain': 2}}, {'self': dict(quiet['self'], unconfirmed=6)},
                           {'self': dict(quiet['self'], normal_confirmed=6)}):
                attacked = dict(deepcopy(quiet), **change)
                self.assertTrue(strategy.facing_attack(attacked))
                self.assertFalse(strategy.profile(attacked)['pressure_style'])
                full.append(tactical_options.resolve(self.engine.policy['normal_tactics'], attacked,
                                                     attacked['self'], attacked['enemy']))
            for policy in full:
                self.assertGreater(policy['width'], narrow['width'])
                self.assertGreater(policy['max_nodes'], narrow['max_nodes'])
            self.assertFalse(strategy.facing_attack(quiet))


class HurriedSecondTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.solo = JsonProcess([SOLO], cwd=ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.solo.close()
        cls.engine.close()

    def options(self, enemy_mode):
        own = side('normal', queue=['2:RG', '2:GB', 'L:RRG'])
        own.update(normal_chain_max=14, moves_since_chain=10)
        req = request(own, side(enemy_mode))
        req['second_target_chain'] = 14
        return self.engine._normal_options(req, own)

    def test_the_second_hurries_only_against_an_opponent_in_fever(self):
        hurry = self.engine.policy['normal_build']['second_time_pressure']
        fever = self.options('fever')
        self.assertEqual((fever['fire_tolerance'], fever['waste_scale']), (hurry['fire_tolerance'], hurry['waste_scale']))
        normal = self.options('normal')
        self.assertNotIn('fire_tolerance', normal)
        self.assertNotIn('waste_scale', normal)

    def ask(self, queue, **extra):
        return self.solo.ask(dict(rule='fever', solo=True, character='raffina', dropset_index=0,
            self={'field': seed3(), 'queue': queue}, plain_pairs=True, special_moves=True, include_next=True,
            sustained=True, sustained_min_chain=3, build_chain=14, trigger=14, panic_chain=14, panic_count=0,
            panic_step=0, patience=0, rebuild=True, construction_scoring=True, preserve_build=True,
            beam_width=50, beam_depth=8, pace_frames=55, elapsed_build_frames=300, **extra))

    def test_a_tolerance_fires_the_large_chain_instead_of_building_on_for_a_few_links(self):
        queue = ['2:GR', '2:YR']
        patient = self.ask(queue, fire_tolerance=0)
        hurried = self.ask(queue, fire_tolerance=90)
        self.assertFalse(patient['fire'])
        self.assertGreater(patient['chain'], hurried['chain'])
        self.assertTrue(hurried['fire'])
        fires = [self.ask(queue, fire_tolerance=t)['fire'] for t in (0, 25, 50, 75, 90)]
        self.assertEqual(fires, sorted(fires))      # a larger tolerance never turns a fire into a wait

    def test_the_waste_scale_is_accepted_and_changes_no_chain_that_is_fired(self):
        queue = ['2:GR', '2:YR']
        self.assertEqual(self.ask(queue)['chain'], self.ask(queue, waste_scale=100)['chain'])
        self.assertIn('x', self.ask(queue, waste_scale=400))


class EarlyClearTests(unittest.TestCase):
    """Log of 2026-11-02: clears that offset nothing while the opponent's chain had not landed."""
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.cases = json.loads((ROOT/'data/fever/golden/early-clear-before-landing.json').read_text(encoding='utf-8'))['cases']

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def answer(self, case):
        req = deepcopy(case['request'])
        self.engine.answer(dict(req, op='prepare_observed'))
        return self.engine.answer(req)

    def test_a_clear_before_the_landing_is_a_placement_that_pops_nothing(self):
        for case in (c for c in self.cases if c['kind'] == 'replaced'):
            reply = self.answer(case)
            self.assertEqual(reply['chain'], 0, case['line'])
            self.assertNotEqual(reply['reason'], 'tactics_clear', case['line'])

    def test_an_offset_that_no_nuisance_falls_without_is_a_placement_that_pops_nothing(self):
        for case in (c for c in self.cases if c['kind'] == 'replaced_offset'):
            self.assertEqual(case['logged'], 'tactics_offset')
            reply = self.answer(case)
            self.assertEqual(reply['chain'], 0, case['line'])
            self.assertTrue(reply['tactics_forecast']['choice']['survives'], case['line'])
            self.assertIsNotNone(reply['tactics_forecast'].get('early_clear_replaced'), case['line'])

    def test_a_main_chain_and_a_board_with_no_other_placement_are_kept(self):
        for case in (c for c in self.cases if c['kind'].startswith('kept')):
            reply = self.answer(case)
            self.assertGreater(reply['chain'], 0, case['line'])

    def test_the_replacement_is_a_surviving_placement_of_the_same_search(self):
        from fever_battle.tactics import early_clear
        case = next(c for c in self.cases if c['kind'] == 'replaced')
        reply = self.answer(case)
        replaced = reply.get('tactics_forecast', {}).get('early_clear_replaced')
        if replaced is not None:
            self.assertGreater(replaced['chain'], 0)
            self.assertTrue(reply['tactics_forecast']['choice']['survives'])
        own = case['request']['self']
        choice = dict(chain=1, cancelled=0, dropped=0, all_clear=False, projected_all_clear=False)
        result = dict(candidates=[dict(chain=0, dropped=0, survives=True, value=5), dict(chain=0, dropped=0, survives=False, value=9)])
        events = [dict(type='link', frame=10, points=100), dict(type='end', frame=20)]
        self.assertEqual(early_clear(result, choice, own, events)['value'], 5)
        self.assertIsNone(early_clear(result, choice, own, [dict(type='end', frame=20)]))
        # An offset is replaced as well, when a placement that pops nothing lets nothing fall.
        self.assertEqual(early_clear(result, dict(choice, cancelled=2), own, events)['value'], 5)
        self.assertEqual(early_clear(result, dict(choice, cancelled=2), dict(own, unconfirmed=3), [])['value'], 5)
        self.assertIsNone(early_clear(result, dict(choice, cancelled=2), own, []))
        falling = dict(candidates=[dict(chain=0, dropped=6, survives=True, value=9)])
        self.assertIsNone(early_clear(falling, dict(choice, cancelled=2), dict(own, confirmed=6), events))
        self.assertIsNone(early_clear(result, dict(choice, attack_kind='main'), own, events))
        self.assertIsNone(early_clear(result, dict(choice, enters_fever=True, cancelled=2), own, events))
        self.assertIsNone(early_clear(result, dict(choice, projected_sufficient_return=True, cancelled=2), own, events))


class PreparedMissDetailTests(unittest.TestCase):
    def test_the_signature_difference_names_the_changed_paths(self):
        diff = ModeBattleEngine._signature_difference
        old = json.dumps(dict(side=dict(queue=['2:RG'], gauge=7, remaining_frames=900), margin=dict(rate=[])), sort_keys=True)
        new = json.dumps(dict(side=dict(queue=['2:RG'], gauge=7, remaining_frames=865, tray=1), margin=dict(rate=[])), sort_keys=True)
        self.assertEqual(diff(old, new), ['/side/remaining_frames', '/side/tray'])
        self.assertEqual(diff(old, old), [])
        self.assertIsNone(diff('not json', old))


class ReusedAnswerMissTests(unittest.TestCase):
    def test_a_reused_prepared_answer_does_not_report_the_miss_of_its_own_preparation(self):
        reply = dict(x=1, prepared_miss='signature_final_exchange', prepared_miss_detail=['/side/piece_id'])
        ModeBattleEngine._forget_miss(reply)
        self.assertEqual(reply, dict(x=1))


class AbsorbedCounterTests(unittest.TestCase):
    def test_a_weak_main_is_not_fired_into_the_tray_that_absorbs_it(self):
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        try:
            req = json.loads((ROOT/'data/fever/golden/absorbed-counter-main.json').read_text(encoding='utf-8'))['request']
            self.assertGreater(req['enemy']['normal_confirmed'], 100)
            engine.answer(dict(req))
            reply = engine.prepared[2]
            self.assertEqual(reply['chain'], 0, reply['reason'])
        finally:
            engine.close()


class FirstSeedWidthTests(unittest.TestCase):
    def test_the_preparation_of_a_first_seed_keeps_the_requested_width(self):
        from unittest.mock import patch
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        widths = []
        real = engine.seed_solver.solve
        def spy(own, rate, count, options, **kw):
            widths.append((own.get('board_status'), options.get('width')))
            return real(own, rate, count, options, **kw)
        try:
            own = side('fever', seed3(), ['2:RY', '2:GG'])
            for status in ('observed_fixed', 'predicted_seed_drop'):
                own['board_status'] = status
                req = request(own); req['seed_options'] = dict(width=250, depth=3, max_nodes=0)
                with patch.object(engine.seed_solver, 'solve', spy):
                    engine.answer(dict(req, op='think'))
            self.assertEqual(widths, [('observed_fixed', 250), ('predicted_seed_drop', 250)])
        finally:
            engine.close()

    def test_only_the_first_seed_stops_on_the_clock_and_keeps_a_move(self):
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        try:
            engine.policy['fever_seed']['spawn_deadline_ms'] = 20
            replies = {}
            for status in ('observed_fixed', 'predicted_seed_drop'):
                own = side('fever', seed3(), ['2:RY', '2:GG'])
                own['board_status'] = status
                req = request(own); req['seed_options'] = dict(width=250, depth=16, max_nodes=0)
                replies[status] = engine.answer(dict(req, op='think'))['seed_forecast']
            self.assertFalse(replies['observed_fixed']['cutoff'])
            self.assertTrue(replies['predicted_seed_drop']['cutoff'])
            self.assertLess(replies['predicted_seed_drop']['expanded'], replies['observed_fixed']['expanded'])
            own = side('fever', seed3(), ['2:RY', '2:GG'])
            own['board_status'] = 'predicted_visible_landing'
            req = request(own); req['seed_options'] = dict(width=250, depth=16, max_nodes=0)
            self.assertTrue(engine.answer(dict(req, op='think'))['seed_forecast']['cutoff'])
        finally:
            engine.close()


if __name__ == '__main__':
    unittest.main()
