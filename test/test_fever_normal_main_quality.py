"""Recorded normal boards with a repair, a second main, a blocked NEXT2, and clears that keep the main."""
import json
import unittest

from fever_fixtures import NATIVE, ROOT, SOLO
from fever_battle.mode_engine import ModeBattleEngine


class NormalMainQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'data/fever/golden/normal-main-quality.json'
        cls.cases = json.loads(path.read_text(encoding='utf-8'))

    def replay(self, name):
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT / 'config.json')
        self.addCleanup(engine.close)
        request = self.cases[name]['request']
        return engine, request['self'], engine.answer(request)

    def placements(self, engine, field, piece):
        return engine.native.ask(dict(op='placements', field=field, piece=piece))['placements']

    def test_small_fire_can_save_a_known_square(self):
        engine, own, reply = self.replay('square_at_next2')
        self.assertEqual(reply['next_chain'], 3)
        self.assertTrue(any(
            not third['dead']
            for second in self.placements(engine, reply['next_field'], own['queue'][1])
            if not second['dead']
            for third in self.placements(engine, second['field'], own['queue'][2])
        ))

    def test_repair_clear_can_restore_the_main(self):
        engine, _, reply = self.replay('repair_after_clear')
        self.assertEqual(reply['next_chain'], 1)
        held = engine.native.ask(dict(op='holding', field=reply['next_field']))
        self.assertGreaterEqual(held['longest'], 8)

    def test_second_keeps_its_existing_main(self):
        engine, own, reply = self.replay('retain_second')
        self.assertEqual(reply['next_chain'], 0)
        before = engine.native.ask(dict(op='holding', field=own['field']))
        after = engine.native.ask(dict(op='holding', field=reply['next_field']))
        self.assertGreaterEqual(after['longest'], before['longest'])

    def test_repair_can_remove_garbage_long_after_a_clear(self):
        _, own, reply = self.replay('repair_old_garbage_damage')
        self.assertEqual(own['moves_since_chain'], 18)
        self.assertTrue(reply.get('score_repair'))
        self.assertLess(sum(row.count('#') for row in reply['next_field']),
                        sum(row.count('#') for row in own['field']))

    def test_repair_restores_a_broken_second_during_a_fully_offset_seed(self):
        engine, own, reply = self.replay('repair_broken_second')
        self.assertEqual(own['moves_since_chain'], 24)
        self.assertEqual(reply['next_chain'], 3)
        held = engine.native.ask(dict(op='holding', field=reply['next_field']))
        self.assertGreaterEqual(held['longest'], 8)

    def assert_clear_keeps_main(self, name):
        # A one-link clear that keeps the main ranks with the quiet builds by score; a quiet placement
        # that buries the trigger no longer wins only because it pops nothing.
        engine, own, reply = self.replay(name)
        self.assertEqual(reply['next_chain'], 1)
        before = engine.native.ask(dict(op='holding', field=own['field']))['longest']
        after = engine.native.ask(dict(op='holding', field=reply['next_field']))['longest']
        self.assertGreaterEqual(before, 10)
        self.assertGreaterEqual(after, before - 1)

    def test_clear_keeps_the_opening_main(self):
        self.assert_clear_keeps_main('clear_keeps_opening_main')

    def test_clear_keeps_the_second_main(self):
        self.assert_clear_keeps_main('clear_keeps_second_main')

    def test_offset_is_not_replaced_by_a_stack_that_buries_the_main(self):
        self.assert_clear_keeps_main('offset_keeps_main')

    def assert_quiet_keeps_main(self, name):
        # Virtual scores searched with every piece known do not trade a held main for a buried trigger.
        engine, own, reply = self.replay(name)
        self.assertEqual(reply['next_chain'], 0)
        before = engine.native.ask(dict(op='holding', field=own['field']))['longest']
        after = engine.native.ask(dict(op='holding', field=reply['next_field']))['longest']
        self.assertGreaterEqual(before, 9)
        self.assertGreaterEqual(after, before)

    def test_opening_retains_its_main(self):
        self.assert_quiet_keeps_main('opening_retains_main')

    def test_opening_retains_its_main_on_a_fuller_board(self):
        self.assert_quiet_keeps_main('opening_retains_main_late')

    def test_forced_lookahead_does_not_replace_the_only_main_keeper(self):
        self.assert_quiet_keeps_main('forced_lookahead_keeps_main')

    def test_opening_keeps_a_visible_fourteen_below_the_minimum(self):
        # One link short of the fire line, the visible route is kept while the opening builds on.
        engine, own, reply = self.replay('keep_visible_fourteen')
        self.assertEqual(reply['next_chain'], 0)
        fired = 0
        for second in self.placements(engine, reply['next_field'], own['queue'][1]):
            if second['dead'] or second['links'] or second['discarded']:
                continue
            for third in self.placements(engine, second['field'], own['queue'][2]):
                if not third['dead']:
                    fired = max(fired, len(third['links']))
        self.assertGreaterEqual(fired, 14)


if __name__ == '__main__':
    unittest.main()
