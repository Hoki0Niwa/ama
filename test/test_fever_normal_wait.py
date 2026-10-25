"""Saved no-send cases, conservative readiness intervals and diagnostic compatibility."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, request, side, seed3
from fever_battle.worker import JsonProcess
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.normal_wait import ready_window
from fever_battle import tactical_options


def strip_diagnostics(value):
    if isinstance(value, dict):
        return {k: strip_diagnostics(v) for k, v in value.items() if k not in ('diagnostic', 'diagnostics', 'search_ms')}
    if isinstance(value, list):
        return [strip_diagnostics(v) for v in value]
    return value


class NormalWaitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = JsonProcess([NATIVE], cwd=ROOT)
        cls.cases = json.loads((ROOT/'data/fever/golden/normal-wait-audit.json').read_text())
        cls.digests = json.loads((ROOT/'data/fever/golden/normal-wait-audit-sha256.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.native.close()

    def test_three_saved_cases_match_complete_legacy_responses(self):
        for name, req in self.cases.items():
            with self.subTest(name=name):
                actual = self.native.ask(req, timeout=60)
                encoded = json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), self.digests[name])
                off = copy.deepcopy(req)
                off['normal_pressure']['counter_read']['normal_wait'] = False
                off['normal_pressure_enemy'].update(ready_in_min=9, ready_in_max=13)
                self.assertEqual(actual, self.native.ask(off, timeout=60))

    def test_diagnostic_output_does_not_change_search_or_first_block(self):
        for name, req in self.cases.items():
            with self.subTest(name=name):
                baseline = self.native.ask(req, timeout=60)
                diagnostic = copy.deepcopy(req)
                diagnostic['normal_pressure']['diagnostics'] = True
                result = self.native.ask(diagnostic, timeout=60)
                self.assertEqual(strip_diagnostics(result), baseline)
                self.assertTrue(all('diagnostic' in c['normal_attack'] for c in result['candidates'] if c['normal_attack']))

    def test_saved_wait_case_evaluates_send_candidate(self):
        req = copy.deepcopy(self.cases['normal-spawn-wait'])
        req['normal_pressure'].update(diagnostics=True)
        req['normal_pressure']['counter_read']['normal_wait'] = True
        req['normal_pressure_enemy'].update(available=True, ready_in_min=0, ready_in_max=13)
        result = self.native.ask(req, timeout=60)
        target = next(c for c in result['candidates'] if (c['x'], c['r']) == (4, 'R'))
        self.assertEqual((target['chain'], target['sent'], target['remaining_cells']), (2, 3, 44))
        attack = target['normal_attack']
        self.assertNotEqual(attack.get('blocked'), 'enemy_unavailable')
        self.assertTrue(attack['diagnostic']['resources_pass'])
        self.assertTrue(attack['counter']['available'])
        self.assertGreater(attack['counter']['expanded'], 0)
        self.assertEqual(attack['counter']['readiness']['evaluated_starts'], 14)

    def probe(self):
        req = copy.deepcopy(self.cases['normal-spawn-wait'])
        req.update(op='normal_pressure_probe', chain=2, redundancy=1, sent=3, deadline=80,
                   enemy_rate_events=[dict(frame=85, target_point=60)])
        req['normal_pressure']['counter_read'].update(normal_wait=True, depth=1)
        req['normal_pressure_enemy'].update(available=True, field=seed3(), queue=['2:RY','2:GB','2:YB'])
        return req

    def test_interval_covers_every_integral_start_and_rate_boundary(self):
        req = self.probe()
        exact = []
        for start in range(9):
            req['normal_pressure_enemy'].update(ready_in_min=start, ready_in_max=start)
            exact.append(self.native.ask(req)['counter'])
        req['normal_pressure_enemy'].update(ready_in_min=0, ready_in_max=8)
        combined = self.native.ask(req)['counter']
        for key in ('defence_1', 'defence_2', 'full_counter', 'gauge_gain'):
            self.assertEqual(combined[key], max(r[key] for r in exact), key)
        self.assertEqual(combined['complete'], all(r['complete'] for r in exact))
        self.assertEqual(combined['entry_possible'], any(r['entry_possible'] for r in exact))
        self.assertEqual(combined['finish'], all(r['finish'] for r in exact))
        costs = [r['counter_cost_cells'] for r in exact if r['counter_cost_cells']]
        self.assertEqual(combined['counter_cost_cells'], min(costs, default=0))

    def test_fixed_start_shifts_counter_deadline(self):
        req = self.probe()
        req.pop('enemy_rate_events')
        req['normal_pressure_enemy'].update(ready_in_min=0, ready_in_max=0)
        early = [self.native.ask(dict(req, deadline=t))['counter']['defence_1'] for t in range(20, 181, 10)]
        req['normal_pressure_enemy'].update(ready_in_min=10, ready_in_max=10)
        shifted = [self.native.ask(dict(req, deadline=t))['counter']['defence_1'] for t in range(30, 191, 10)]
        self.assertEqual(early, shifted)
        self.assertGreater(max(early), 0)

    def test_public_wait_contract_rejects_uncertain_or_stale_boards(self):
        enemy = side()
        enemy.update(phase='waiting_seed', board_status='observed_fixed', board_observed_frame=0,
                     awaiting_seed=True, normal_wait=dict(kind='spawn', board_fixed=True,
                        observed_frame=0, ready_in_min=0, ready_in_max=13))
        self.assertEqual(ready_window(enemy, [], None, True), dict(ready_in_min=0, ready_in_max=13))
        self.assertIsNone(ready_window(enemy, [], None, False))
        self.assertIsNone(ready_window(enemy, [dict(type='link')], None, True))
        self.assertIsNone(ready_window(enemy, [], dict(enemy_fever=True), True))
        for changes in (dict(phase='placing'), dict(phase='chain'), dict(mode='fever'), dict(gauge=7),
                        dict(board_status='unknown'), dict(board_observed_frame=1), dict(queue=[]),
                        dict(normal_wait=None), dict(normal_wait=dict(kind='seed_exchange'))):
            self.assertIsNone(ready_window(dict(enemy, **changes), [], None, True), changes)
        for changes in (dict(ready_in_min=True), dict(ready_in_max=121), dict(ready_in_min=14)):
            bad = copy.deepcopy(enemy)
            bad['normal_wait'].update(changes)
            with self.assertRaises(ValueError):
                ready_window(bad, [], None, True)

    def test_new_options_are_strict_booleans(self):
        for value in (True, False):
            tactical_options.validate(dict(normal_tactics=dict(diagnostics=value, counter_read=dict(normal_wait=value))))
        for value in (0, 1, 'true', None):
            for options in (dict(diagnostics=value), dict(counter_read=dict(normal_wait=value))):
                with self.assertRaises(ValueError):
                    tactical_options.validate(dict(normal_tactics=options))

    def test_builder_fallback_keeps_selected_and_executed_distinct(self):
        # An unaffordable early send must remain visible even when the builder wins.
        own = side('normal', ['......']*13+['RRR...'], ['2:RY', '2:GB', '2:YB'])
        own['character'] = 'arle'
        req = request(own, side())
        req['target_point'] = 40
        req['normal_tactics'] = dict(pressure=dict(enabled=True, min_remaining=84))
        replies = []
        for enabled in (False, True):
            engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
            try:
                options = copy.deepcopy(req)
                if enabled:
                    options['normal_tactics']['diagnostics'] = True
                replies.append(engine.answer(options))
            finally:
                engine.close()
        self.assertEqual(strip_diagnostics(replies[0]), strip_diagnostics(replies[1]))
        diagnostic = replies[1]['normal_tactics']['diagnostics']
        self.assertEqual(diagnostic['search_status'], 'build')
        self.assertGreater(diagnostic['counts']['root_candidates'], 0)
        self.assertGreater(diagnostic['counts']['send'], 0)
        self.assertGreater(diagnostic['resource_blocks']['min_remaining'], 0)
        self.assertTrue(diagnostic['execution']['matched_root'])
        self.assertEqual(diagnostic['executed']['x'], replies[1]['x'])


if __name__ == '__main__':
    unittest.main()
