"""A move that enters Fever is charged for every puyo it pops: the board is stored for the next entry."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import tactics, tactical_options


class EntryConsumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def own(self, gauge):
        refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows = list(next(s['field'] for s in refs['seeds'] if s['id'] == 'hirazumi-7'))
        rows[4:7] = ['Y.....']*3
        own = side('normal', rows, ['2:YG'])
        own.update(character='arle', gauge=gauge, confirmed=1, normal_confirmed=1)
        return own

    def candidates(self, gauge, weight):
        policy = deepcopy(self.engine.policy['normal_tactics']); policy['weights']['entry_consume'] = weight
        result = tactics.choose(self.engine.native, self.engine.scoring, self.own(gauge), 30, 1, policy,
            enemy=side('normal'), fever=dict(enemy_fever=True, enemy_fever_at=1000))
        return {(c['x'], c['r']): c for c in result['tactics_forecast']['candidates']}

    def test_policy_carries_the_weight_and_the_protocol_accepts_it(self):
        self.assertGreater(self.engine.policy['normal_tactics']['weights']['entry_consume'], 0)
        tactical_options.validate(dict(normal_tactics=dict(weights=dict(entry_consume=0))))

    def test_entering_pays_only_for_the_puyos_popped_past_what_the_entry_needed(self):
        free, charged = self.candidates(6, 0), self.candidates(6, 100)
        once = (0, 'U')                              # one four-puyo link takes the gauge from 6 to 7
        long = (2, 'U')                              # seven links of four: 24 puyos more than the entry needed
        for move in (once, long):
            self.assertTrue(free[move]['enters_fever'] and charged[move]['enters_fever'])
        self.assertEqual(free[once]['value'], charged[once]['value'])
        self.assertEqual(free[long]['value'] - charged[long]['value'], 100 * (7 * 4 - 4))

    def test_a_move_that_does_not_enter_is_not_charged(self):
        free, charged = self.candidates(0, 0), self.candidates(0, 100)
        for move, c in free.items():
            self.assertFalse(c['enters_fever'])
            self.assertEqual(c['value'], charged[move]['value'])

class LeastEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def candidate(self, groups, value, enters=True, survives=True, **extra):
        return {**dict(enters_fever=enters, survives=survives, value=value,
                       links=[dict(groups=[g], colors=1) for g in groups], x=len(groups), r='U'), **extra}

    def result(self, chosen, *others):
        return dict(choice=chosen, candidates=[chosen, *others])

    def test_the_entering_candidate_that_pops_fewest_replaces_a_wasteful_choice(self):
        wasteful, minimal = self.candidate([5, 5], 4980), self.candidate([4], 4000)
        self.assertIs(tactics.least_entry(self.result(wasteful, minimal)), minimal)
        self.assertEqual(tactics.popped(wasteful), 10)

    def test_ties_keep_the_higher_value_and_nothing_else_is_touched(self):
        a, b = self.candidate([4], 3000), self.candidate([4], 3500, x=9)
        chosen = self.candidate([4, 4], 5000)
        self.assertIs(tactics.least_entry(self.result(chosen, a, b)), b)
        # Not entering: untouched. Candidates that lose, or do not enter, are never picked.
        quiet = self.candidate([5], 1000, enters=False)
        self.assertIs(tactics.least_entry(self.result(quiet, self.candidate([4], 9))), quiet)
        dying = self.candidate([4], 9, survives=False)
        small = self.candidate([4], 9, enters=False)
        self.assertIs(tactics.least_entry(self.result(chosen, dying, small)), chosen)
        # An entry that also clears the board whole keeps its place.
        whole = self.candidate([4, 4], 5000, all_clear=True)
        self.assertIs(tactics.least_entry(self.result(whole, self.candidate([4], 1))), whole)
        # Already the fewest: the choice stands.
        only = self.candidate([4], 100)
        self.assertIs(tactics.least_entry(self.result(only, self.candidate([4, 4], 9999))), only)

    def test_the_engine_reply_follows_it(self):
        own = EntryConsumeTests.own(self, 6)
        reply = tactics.choose(self.engine.native, self.engine.scoring, own, 30, 1,
            self.engine.policy['normal_tactics'], enemy=side('normal'),
            fever=dict(enemy_fever=True, enemy_fever_at=1000))
        choice = reply['tactics_forecast']['choice']
        self.assertTrue(choice['enters_fever'])
        self.assertEqual(tactics.popped(choice), 4)


if __name__ == '__main__': unittest.main()
