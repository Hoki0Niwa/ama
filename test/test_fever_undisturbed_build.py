"""An opponent's chain that lands nothing does not move the builder's placement."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import tactics


def candidate(x, **extra):
    return {**dict(x=x, r='U', chain=0, dropped=0, cancelled=0, survives=True, current_survives=True, can_receive=True,
                   current_exchange_pending=0, projected_all_clear=False, disruption_kind='none'), **extra}


class RuleTests(unittest.TestCase):
    def check(self, choice, placed):
        return tactics.undisturbed_build(dict(candidates=[choice, placed]), choice, (placed['x'], placed['r']))

    def test_the_build_stands_when_nothing_lands(self):
        self.assertTrue(self.check(candidate(0), candidate(1)))
        self.assertTrue(self.check(candidate(0, chain=1), candidate(1)))

    def test_the_search_keeps_what_it_means_to_do(self):
        for extra in (dict(cancelled=1), dict(dropped=6), dict(projected_all_clear=True), dict(disruption_kind='jab'),
                      dict(projected_normal_attack=dict(pressure=True)), dict(projected_normal_attack=dict(finish=True))):
            self.assertFalse(self.check(candidate(0, **extra), candidate(1)), extra)

    def test_a_build_that_is_not_safe_or_fires_is_left_to_the_search(self):
        for extra in (dict(chain=3), dict(dropped=6), dict(survives=False), dict(current_survives=False),
                      dict(can_receive=False), dict(current_exchange_pending=1)):
            self.assertFalse(self.check(candidate(0), candidate(1, **extra)), extra)

    def test_no_builder_or_same_move(self):
        same = candidate(0)
        self.assertFalse(tactics.undisturbed_build(dict(candidates=[same]), same, None))
        self.assertFalse(tactics.undisturbed_build(dict(candidates=[same]), same, (0, 'U')))


class RecordedTests(unittest.TestCase):
    def test_recorded_positions(self):
        cases = json.loads((ROOT/'data/fever/golden/undisturbed-build.json').read_text(encoding='utf-8'))['cases']
        for case in cases:
            with self.subTest(case['source']):
                engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
                try:
                    engine.answer(dict(deepcopy(case['request']), op='prepare_observed'))
                    reply = engine.answer(deepcopy(case['request']))
                finally:
                    engine.close()
                if case['build']:
                    self.assertEqual([reply['x'], reply['r']], case['build'])
                    self.assertEqual(reply['reason'], 'normal_build_or_fire')
                else:
                    self.assertTrue(reply['reason'].startswith('tactics_'))


if __name__ == '__main__': unittest.main()
