"""The battle placement generator and live operation library must agree."""
import ctypes as C
import os
import json
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
        cls.dll = C.CDLL(os.environ.get('AMA_TEST_OPERATION_DLL', str(ROOT / 'bin/fever/operations.dll')))
        cls.dll.ama_operation_route.argtypes = [C.POINTER(C.c_int)] + [C.c_int] * 9 + [C.POINTER(Press), C.c_int]
        cls.dll.ama_operation_route.restype = C.c_int
        cls.dll.ama_operation_rotate.argtypes = [C.POINTER(C.c_int)] + [C.c_int] * 6 + [C.POINTER(Press)]
        cls.dll.ama_operation_rotate.restype = C.c_int
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

    def test_trial_triple_kick_that_lifts_from_the_spawn_row_is_suspended(self):
        # Offered until 2026-10-14: the turn lifted the axis from the spawn row to the 13th row, the climb
        # `hook` was stopped for; five of six giving-ups of the 16:10 session were such routes.
        h = (11, 8, 2, 0, 0, 2)
        self.assertFalse(self.route(h, 3, 0, 1))
        answer = self.engine.ask(dict(op='placements', field=self.field(h), piece='L:RRG'))
        self.assertNotIn((0, 'R'), {(p['x'], p['r']) for p in answer['placements']})
        self.assertIn((2, 'U'), {(p['x'], p['r']) for p in answer['placements']})

    def test_logged_spawn_row_lifts_are_suspended(self):
        data = json.loads((ROOT / 'data/fever/baselines/2026-10-14-spawn-row-lift-triples.json').read_text(encoding='utf-8'))
        for case in data['cases']:
            with self.subTest(case=case['id']):
                x, r = case['target']
                self.assertFalse(self.route(case['heights'], 3, x, r))
                answer = self.engine.ask(dict(op='placements', field=self.field(case['heights']), piece=case['piece']))
                self.assertNotIn((x, 'URDL'[r]), {(p['x'], p['r']) for p in answer['placements']})

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

    def path_from(self, h, start, goal):
        out = (Press * 1024)()
        n = self.dll.ama_operation_route((C.c_int * 6)(*h), 2, *start, 0,
                                         *goal, 0, 1, out, len(out))
        return None if n < 0 else list(out[:n])

    def test_logged_airborne_traverse_cannot_turn_onto_thirteen_row_column(self):
        # seed 0 / AI2 / pair32: after the lift at x=5, the three left
        # translations end at y=-1.77, not the row-14 y=-2 needed by LEFT.
        h = (13, 13, 9, 7, 11, 12)
        self.assertIsNone(self.path_from(h, (5, -2, 2), (2, 3)))
        self.assertFalse(self.route(h, 2, 2, 3))
        offered = self.engine.ask(dict(op='placements', field=self.field(h), piece='2:YB'))
        self.assertNotIn((2, 'L'), {(p['x'], p['r']) for p in offered['placements']})
        # Mirror the observed lifted start, independently of the spawn column.
        self.assertIsNone(self.path_from(h[::-1], (0, -2, 2), (3, 1)))

    def test_airborne_translation_to_open_column_uses_entered_row(self):
        h = (13, 13, 9, 7, 11, 12)
        path = self.path_from(h, (5, -2, 2), (2, 2))
        self.assertIsNotNone(path)
        self.assertEqual((path[-1].x, path[-1].y, path[-1].r), (2, -1, 2))
        self.assertTrue(all(p.y >= -1 for p in path if p.dx))

    def test_supported_thirteen_row_traverse_stays_at_fourteenth_row(self):
        # The pivot of an upright pair remains on a 13-row surface. These
        # placements are not removed by the airborne clearance check.
        h = (0, 0, 0, 13, 13, 13)
        path = self.path_from(h, (5, -2, 0), (2, 0))
        self.assertIsNotNone(path)
        self.assertEqual([(p.x, p.y) for p in path], [(4, -2), (3, -2), (2, -1)])

    def test_logged_failed_triple_edges_are_suspended(self):
        cases = json.loads((ROOT / 'data/fever/baselines/2026-10-14-disabled-triple-operations.json').read_text(encoding='utf-8'))
        for case in cases:
            x, r = case['trace'][-1][0]
            step = case['diverged']['steps'][0][1]
            out = Press()
            with self.subTest(case=case['id']):
                self.assertEqual(self.dll.ama_operation_rotate((C.c_int * 6)(*case['heights']),
                    3, x, 0, r, 0, step, C.byref(out)), -1)
                answer = self.engine.ask(dict(op='placements', field=case['field'], piece=case['piece']))
                self.assertNotIn((case['target'][0], 'URDL'[case['target'][1]]),
                                 {(p['x'], p['r']) for p in answer['placements']})
            self.assertEqual(self.dll.ama_operation_rotate((C.c_int * 6)(*case['heights'][::-1]),
                3, 5-x, 0, (3-r)%4, 0, -step, C.byref(out)), -1)

    def test_triple_ordinary_wall_turn_and_lower_floor_kick_remain(self):
        out = Press()
        self.assertEqual(self.dll.ama_operation_rotate((C.c_int * 6)(*([0]*6)),
            3, 0, 0, 0, 0, -1, C.byref(out)), 0)
        self.assertEqual((out.x, out.y, out.r), (1, 0, 3))
        self.assertEqual(self.dll.ama_operation_rotate((C.c_int * 6)(0,0,0,6,0,0),
            3, 3, 5, 0, 0, 1, C.byref(out)), 0)
        self.assertEqual((out.x, out.y, out.r), (3, 4, 1))


if __name__ == '__main__':
    unittest.main()
