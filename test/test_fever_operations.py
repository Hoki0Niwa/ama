"""The battle placement generator and live operation library must agree."""
import ctypes as C
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'test')]
from fever_fixtures import NATIVE
from fever_battle.worker import JsonProcess


class Press(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('dx', 'turn', 'x', 'y', 'r', 'armed', 'quick', 'frames')]


class OperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = JsonProcess([NATIVE])
        cls.dll = C.CDLL(str(ROOT / 'bin/fever/operations.dll'))
        cls.dll.ama_operation_route.argtypes = [C.POINTER(C.c_int)] + [C.c_int] * 9 + [C.POINTER(Press), C.c_int]
        cls.dll.ama_operation_route.restype = C.c_int
        assert cls.dll.ama_operation_version() == 1 and cls.dll.ama_operation_rule() == 1

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    @staticmethod
    def field(h):
        return [''.join('#' if 14 - row <= h[x] else '.' for x in range(6)) for row in range(14)]

    def route(self, h, shape, x, r, special=True):
        # Triple box -> pivot: LEFT/DOWN have their pivot in the right column.
        pivot = x + (shape == 3 and r in (2, 3))
        out = (Press * 1024)()
        n = self.dll.ama_operation_route((C.c_int * 6)(*h), shape, 2, 0, 0, 0,
                                         pivot, r, 0, special, out, len(out))
        return n >= 0

    def test_random_pair_and_triple_candidates_have_executable_native_routes(self):
        rng = random.Random(1009)
        for trial in range(64):
            h = [rng.randrange(14 if x not in (2, 3) else 12) for x in range(6)]
            for text, shape in (('2:RG', 2), ('L:RRG', 3), ('J:RGR', 3)):
                answer = self.engine.ask(dict(op='placements', field=self.field(h), piece=text))
                offered = {(p['x'], 'URDL'.index(p['r'])) for p in answer['placements']}
                expected = {(x, r) for x in range(6 if shape == 2 else 5) for r in range(4)
                            if self.route(h, shape, x, r)}
                self.assertEqual(offered, expected, (trial, h, text))

    def test_trial_triple_kick_is_offered_without_a_special_penalty(self):
        h = (11, 8, 2, 0, 0, 2)
        self.assertFalse(self.route(h, 3, 0, 1, special=False))
        self.assertTrue(self.route(h, 3, 0, 1))
        answer = self.engine.ask(dict(op='placements', field=self.field(h), piece='L:RRG'))
        kicked = next(p for p in answer['placements'] if (p['x'], p['r']) == (0, 'R'))
        # It has exactly the same transition schema as ordinary placements.
        ordinary = next(p for p in answer['placements'] if (p['x'], p['r']) == (2, 'U'))
        self.assertEqual(set(kicked), set(ordinary))
        self.assertNotIn('operation_penalty', kicked)

    def test_pair_crosses_twelve_without_eleven_support(self):
        for h, x in (((0, 0, 0, 0, 12, 0), 5), ((0, 12, 0, 0, 0, 0), 0)):
            self.assertNotIn(11, h)
            self.assertTrue(self.route(h, 2, x, 0))
            self.assertFalse(self.route(h, 2, x, 0, special=False))
            answer = self.engine.ask(dict(op='placements', field=self.field(h), piece='2:RG'))
            self.assertIn((x, 'U'), {(p['x'], p['r']) for p in answer['placements']})

    def test_dragon_discards_two_puyos_and_can_repeat_without_hidden_obstruction(self):
        for h, x in (((0, 0, 0, 0, 12, 13), 5), ((13, 12, 0, 0, 0, 0), 0)):
            board = self.field(h)
            for text in ('2:RG', '2:BB', '2:YR'):
                answer = self.engine.ask(dict(op='placements', field=board, piece=text))
                discard = next(p for p in answer['placements'] if (p['x'], p['r']) == (x, 'U'))
                self.assertEqual(discard['discarded'], 2)
                self.assertEqual(discard['locked_field'], board)
                self.assertFalse(discard['dead'])
                self.assertTrue(self.route(h, 2, x, 0))
                board = discard['locked_field']

    def test_thirteenth_row_remains_and_is_not_discarded(self):
        h = (0, 0, 0, 0, 12, 0)
        answer = self.engine.ask(dict(op='placements', field=self.field(h), piece='2:RG'))
        upright = next(p for p in answer['placements'] if (p['x'], p['r']) == (4, 'U'))
        self.assertEqual(upright['discarded'], 1)
        self.assertEqual(upright['locked_field'][1][4], 'R')

    def test_logged_boards_reject_left_disposal_without_the_twelve_row_step(self):
        for h in ((13, 11, 9, 10, 12, 11), (13, 11, 9, 10, 12, 13)):
            answer = self.engine.ask(dict(op='placements', field=self.field(h), piece='2:GY'))
            offered = {(p['x'], p['r']) for p in answer['placements']}
            self.assertNotIn((0, 'U'), offered)
            self.assertFalse(self.route(h, 2, 0, 0))
            if h[5] == 13:
                self.assertIn((5, 'U'), offered)
                right = next(p for p in answer['placements'] if (p['x'], p['r']) == (5, 'U'))
                self.assertEqual(right['discarded'], 2)

    def test_four_cell_pieces_cannot_use_kicks_to_cross_a_spawn_wall(self):
        h = (0, 12, 0, 0, 0, 0)
        for text in ('4:RRGG', '0:R'):
            answer = self.engine.ask(dict(op='placements', field=self.field(h), piece=text))
            self.assertTrue(answer['placements'])
            self.assertTrue(all(p['x'] >= 2 for p in answer['placements']))


if __name__ == '__main__':
    unittest.main()
