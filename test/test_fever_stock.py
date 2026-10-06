"""Offset stock: links a board pops trigger after trigger, and the aim objective's wiring."""
import unittest

from fever_fixtures import NATIVE, ROOT, SOLO, request, side
from fever_battle.model import EMPTY
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.worker import JsonProcess


def board(*columns):
    """Columns given bottom-up, left to right; the rest stays empty."""
    rows = [list(row) for row in EMPTY]
    for x, cells in enumerate(columns):
        for y, cell in enumerate(cells):
            rows[13-y][x] = cell
    return [''.join(row) for row in rows]


class StockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = JsonProcess([NATIVE], cwd=ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.native.close()

    def stock(self, rows, want=7):
        return self.native.ask(dict(op='stock', field=rows, want=want))

    def test_empty_board_has_no_stock(self):
        self.assertEqual(self.stock(EMPTY), dict(units=0, links=0, colors=0))

    def test_three_stacked_fire_with_one_puyo(self):
        self.assertEqual(self.stock(board('RRR')), dict(units=4, links=1, colors=1))

    def test_two_stacked_need_two_puyos_and_count_less(self):
        self.assertEqual(self.stock(board('RR')), dict(units=2, links=1, colors=0))

    def test_independent_triggers_add_up(self):
        result = self.stock(board('RRR', '', 'YYY', '', 'GGG'))
        self.assertEqual((result['links'], result['colors'], result['units']), (3, 3, 12))

    def test_links_stop_at_the_number_wanted(self):
        rows = board('RRR', '', 'YYY', '', 'GGG')
        self.assertEqual(self.stock(rows, want=2)['links'], 2)

    def test_a_chain_counts_every_link(self):
        # Red on yellow: the yellow trigger drops the reds onto the bottom red.
        result = self.stock(board('RYYYRR'))
        self.assertGreaterEqual(result['links'], 2)

    def test_a_trigger_is_reached_from_the_side_until_nuisance_walls_it_in(self):
        self.assertEqual(self.stock(board('RRR#'))['links'], 1)
        self.assertEqual(self.stock(board('RRR#', '###'))['links'], 0)


class AimObjectiveTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    def tearDown(self):
        self.engine.close()

    def options(self, gauge=0, gain=1):
        own = side()
        own['gauge'] = gauge
        req = request(own, side())
        req['gauge_gain_on_offset'] = gain
        return self.engine._normal_options(req, own)

    def test_mainline_is_the_default_objective(self):
        self.assertEqual(self.engine.policy['normal_build']['objective'], 'mainline')
        self.assertNotIn('aim', self.options())

    def test_aim_objective_sets_the_builder_request(self):
        self.engine.policy['normal_build']['objective'] = 'fever_aim'
        options = self.options(gauge=3)
        self.assertTrue(options['aim'])
        self.assertEqual((options['stock_want'], options['weight_set'], options['trigger']), (4, 'fever_aim', 19))

    def test_aim_objective_needs_a_gauge_that_can_fill(self):
        self.engine.policy['normal_build']['objective'] = 'fever_aim'
        self.assertNotIn('aim', self.options(gain=0))

    def test_aim_build_places_a_piece(self):
        self.engine.policy['normal_build']['objective'] = 'fever_aim'
        own = side(queue=['2:RY', '2:GB', 'L:RRG'])
        reply = self.engine.answer(request(own, side()))
        self.assertEqual((reply['action'], reply['reason']), ('place', 'normal_build_or_fire'))


if __name__ == '__main__':
    unittest.main()
