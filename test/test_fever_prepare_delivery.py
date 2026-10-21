"""The next piece prepared on the board nuisance leaves: an opposing chain ending during the placement, and
what this side's own chain leaves confirmed (mode_engine _after_placement, _drop_after_chain)."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'test'))
from fever_fixtures import NATIVE, SOLO, side, request, seed3, bystander
from fever_battle.mode_engine import ModeBattleEngine


def own_normal(**changes):
    own = side('normal', seed3(), ['2:RY', '2:GG', '2:BY'])
    own.update(changes)
    own['normal_confirmed'], own['normal_unconfirmed'] = own['confirmed'], own['unconfirmed']
    return own


class PrepareDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def prepare_request(self, own, placement):
        message = request(own, bystander())
        message.update(op='prepare', placement=placement, enemy_chain=dict(mode_generation=0, seed_id=1))
        return message

    def after(self, own, placement, events):
        self.engine.margin = {}
        with patch.object(self.engine, '_enemy_events', return_value=events):
            return self.engine._after_placement(self.prepare_request(own, placement), own)

    def test_a_chain_ending_before_the_check_drops_what_it_sent(self):
        own = own_normal(unconfirmed=5, garbage_phase=0)
        placement = dict(x=0, r='U')
        future = self.after(own, placement, [dict(type='link', frame=5, points=600), dict(type='end', frame=10)])
        placed = self.engine.native.ask(dict(op='transition', field=own['field'], piece='2:RY', **placement))
        dropped = self.engine.native.ask(dict(op='drop_preview', field=placed['field'], count=10, garbage_phase=0))
        self.assertEqual(future['field'], dropped['field'])          # 5 flying + 600/120 sent, confirmed at the end
        self.assertEqual((future['confirmed'], future['unconfirmed'], future['garbage_phase']), (0, 0, 4))
        self.assertEqual((future['normal_confirmed'], future['normal_unconfirmed']), (0, 0))

    def test_a_chain_ending_after_the_check_leaves_the_board(self):
        own = own_normal(unconfirmed=5, garbage_phase=0)
        future = self.after(own, dict(x=0, r='U'), [dict(type='link', frame=5, points=600), dict(type='end', frame=900)])
        placed = self.engine.native.ask(dict(op='transition', field=own['field'], piece='2:RY', x=0, r='U'))
        self.assertEqual(future['field'], placed['field'])
        self.assertEqual((future['confirmed'], future['unconfirmed']), (0, 5))

    def test_unknown_columns_leave_the_builder_alone_prepared(self):
        own = own_normal(unconfirmed=5, garbage_phase=None)
        reason = self.after(own, dict(x=0, r='U'), [dict(type='link', frame=5, points=480), dict(type='end', frame=10)])
        self.assertEqual(reason, 'enemy_delivery_can_change_next_board')   # 9 on unknown columns

    def test_what_a_chain_leaves_confirmed_falls_after_it(self):
        own = own_normal(confirmed=8, garbage_phase=2)
        placement = dict(x=5, r='U')
        result = self.engine.native.ask(dict(op='transition', field=own['field'], piece='2:RR', **placement))
        self.assertTrue(result['links'])
        future = dict(own, field=result['field'])
        self.engine._offset_by_chain(future, own, result['links'], 120)
        left = future['confirmed']
        self.assertGreater(left, 0)
        self.engine._drop_after_chain(self.prepare_request(own, placement) | {'enemy_chain': None}, own, future,
                                      result, result['links'])
        dropped = self.engine.native.ask(dict(op='drop_preview', field=result['field'], count=left, garbage_phase=2))
        self.assertEqual(future['field'], dropped['field'])
        self.assertEqual((future['confirmed'], future['garbage_phase']), (0, (2 + left) % 6))

    def test_the_pace_is_measured_between_prepares(self):
        self.engine.pace, self.engine.pace_states, self.engine.pace_samples = None, {}, {}
        for k, frame in enumerate((0, 55, 115, 170)):
            own = own_normal(piece_id=k)
            self.engine._observe_pace(dict(match_id='pace', frame=frame, placement=dict(x=0, r='U')), own, 'prepare')
        self.assertEqual(self.engine.pace_samples['normal'], [55, 60, 55])
        self.assertEqual(self.engine.pace, 55)
        # a chain of its own between two prepares is not a piece's pace
        own = own_normal(piece_id=4, confirmed=0)
        self.engine._observe_pace(dict(match_id='pace', frame=225, placement=dict(x=5, r='U')), own | {'queue': ['2:RR', '2:GG', 'L:RRG']}, 'prepare')
        self.engine._observe_pace(dict(match_id='pace', frame=400, placement=dict(x=0, r='U')), own_normal(piece_id=5), 'prepare')
        self.assertEqual(len(self.engine.pace_samples['normal']), 4)
        self.engine.pace, self.engine.pace_states, self.engine.pace_samples = None, {}, {}

    def test_the_next_piece_is_decided_as_of_its_start(self):
        own = side('normal', seed3(), ['2:RY', '2:GG', 'L:RRG'])
        message = request(own, bystander())
        message.update(op='prepare', placement=dict(x=0, r='U'))
        seen = []
        think = self.engine._think
        def spy(ahead, *rest, **named):
            seen.append(ahead['frame'])
            return think(ahead, *rest, **named)
        self.engine.pace = None
        with patch.object(self.engine, '_think', side_effect=spy):
            self.engine.answer(message)
        # the fastest piece of the model: placement 14 (no split), spawn 28
        self.assertEqual(seen, [message['frame'] + 14 + 28])


if __name__ == '__main__':
    unittest.main()
