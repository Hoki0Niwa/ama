"""Do not spend a normal mainline on a counter that loses to the observed tail."""
from pathlib import Path
import sys
import json
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, request, side, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.uncertainty import choose


class CounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def own(self, pending=20, gauge=0):
        own = side('normal', seed_with_small_green(), ['2:GY'])
        own.update(unconfirmed=pending, normal_unconfirmed=pending, gauge=gauge)
        return own

    def events(self, points=120000):
        return [dict(type='link', frame=500, points=points), dict(type='end', frame=550)]

    def answer(self, own, events=None, builder=(1, 'U'), allowed=None):
        """The engine's reply with the builder's move and the opponent's chain given."""
        req = request(own)
        if allowed is not None:
            req.update(op='recover_placement', reachable_placements=allowed)
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=builder[0], r=builder[1])):
            with patch.object(self.engine, '_enemy_events', return_value=events or []):
                return self.engine.answer(req)

    def test_builder_mainline_cannot_answer_large_tail_after_it_finishes(self):
        reply = self.answer(self.own(), self.events())
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['reason'], 'tactics_stack')
        rejected = next(c for c in reply['tactics_forecast']['candidates'] if (c['x'], c['r']) == (1, 'U'))
        self.assertEqual(rejected['chain'], 3)
        self.assertLess(rejected['value'], reply['tactics_forecast']['choice']['value'])
        self.assertEqual(reply['decision_dependencies'], ['self', 'enemy'])

    def test_pending_packet_alone_also_blocks_insufficient_builder_fire(self):
        reply = self.answer(self.own())
        self.assertEqual(reply['chain'], 0)

    def test_countering_two_harmless_nuisance_does_not_justify_builder_fire(self):
        reply = self.answer(self.own(1), self.events(120))
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['reason'], 'tactics_stack')

    def test_a_normal_opponents_large_tail_does_not_buy_early_entry(self):
        reply = self.answer(self.own(200, gauge=6), self.events())
        self.assertEqual(reply['chain'], 0)
        self.assertFalse(reply['entry_pending_after_chain'])

    def test_only_reachable_emergency_entry_is_not_forbidden(self):
        reply = self.answer(self.own(200, gauge=4), self.events(), allowed=[dict(x=1, r='U')])
        self.assertEqual((reply['x'], reply['r'], reply['chain']), (1, 'U', 3))

    def due_mainline(self, pending=1000):
        refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows = list(next(s['field'] for s in refs['seeds'] if s['id'] == 'hirazumi-7'))
        rows[4:7] = ['Y.....']*3
        own = side('normal', rows, ['2:YR'])
        own.update(confirmed=pending, normal_confirmed=pending)
        return own

    def test_due_large_packet_preserves_seven_chain_with_one_chain_offset(self):
        # Seven links leave nine hundred: fired, the puyos that enter Fever are gone and the packet is not.
        reply = self.engine.answer(request(self.due_mainline()))
        self.assertEqual(reply['chain'], 1)
        self.assertEqual(reply['reason'], 'tactics_offset')
        self.assertEqual(reply['tactics_forecast']['root_stock']['longest'], 7)
        self.assertEqual(reply['gauge_forecast']['gauge_after'], 1)
        self.assertFalse(reply['entry_pending_after_chain'])

    def landing(self, pieces, amount=150, queue=('2:YR', '2:GB', '2:GB'), hold=0):
        """An unconfirmed packet landing after `pieces` more pieces; the seven chain's trigger is in hand."""
        own = self.due_mainline(0)
        own.update(character='arle', queue=list(queue), unconfirmed=amount, normal_unconfirmed=amount)
        with patch.object(self.engine, '_enemy_hold', return_value=hold):
            return self.answer(own, [dict(type='end', frame=pieces * 42)], builder=(5, 'U'))

    def open_to(self, defense):
        """A small packet far from landing, the seven chain's trigger in hand, against an opponent with this defense."""
        own = self.due_mainline(0)
        own.update(character='arle', queue=['2:YR', '2:GB', '2:GB'], unconfirmed=18, normal_unconfirmed=18)
        with patch.object(self.engine, '_enemy_defense', return_value=defense):
            return self.answer(own, [dict(type='end', frame=8 * 42)], builder=(5, 'U'))

    def test_main_chain_is_fired_at_once_when_what_it_sends_kills(self):
        # Their board fills with 72, they hold nothing and have no link to offset with.
        self.assertEqual(self.open_to(dict(hold=0, kill=72, links=0, need=7))['chain'], 7)

    def test_main_counter_uses_score_even_when_opponent_can_escape_into_fever(self):
        # Restored main policy returns a sufficient attack when the packet exceeds
        # the acceptable drop; predicted Fever escape does not classify it away.
        self.assertEqual(self.open_to(dict(hold=0, kill=72, links=1, need=1))['chain'], 7)

    def test_insufficient_mainline_is_not_fired_just_for_entry_before_landing(self):
        # Seven links leave 52 nuisance. Entry no longer funds spending the mainline.
        reply = self.landing(2)
        self.assertEqual(reply['chain'], 0)
        self.assertFalse(reply['entry_pending_after_chain'])

    def test_main_chain_is_held_while_many_pieces_are_still_to_come(self):
        self.assertEqual(self.landing(8)['chain'], 0)

    def test_main_chain_is_not_fired_at_a_packet_it_leaves_beyond_a_fevers_reach(self):
        self.assertLess(self.landing(2, amount=600)['chain'], 7)

    def test_main_counter_is_not_vetoed_by_the_removed_fever_reach_model(self):
        self.assertEqual(self.landing(2, amount=60)['chain'], 7)
        self.assertEqual(self.landing(2, amount=60, hold=600)['chain'], 7)

    def test_due_packet_that_mainline_can_counter_keeps_entry(self):
        reply = self.engine.answer(request(self.due_mainline(90)))
        self.assertEqual(reply['chain'], 7)
        self.assertTrue(reply['entry_pending_after_chain'])

    def test_due_large_packet_keeps_mainline_when_small_clear_is_unreachable(self):
        reply = self.answer(self.due_mainline(), allowed=[dict(x=3, r='R')])
        self.assertEqual(reply['chain'], 7)

    def simulate(self, own=None, events=None, enemy=None, margin=None, points=240):
        # Isolate causal packet accounting from the character's chain table.
        own = own or side()
        native = type('Native', (), {'ask': lambda _, req: dict(placements=[dict(
            x=0, r='U', field=own['field'], locked_field=own['field'], links=[{}],
            split_distances=[0], fall_distances=[0], fall_features=[None],
            dead=False, all_clear=False)])})()
        scoring = type('Scoring', (), {'chain': lambda *args: [points]})()
        return choose(native, scoring, own, 120, enemy_events=events or self.events(240),
                      enemy=enemy or side(), margin=margin)['choice']

    def test_sent_counter_offsets_enemy_tail_before_it_reaches_us(self):
        first = self.simulate()
        self.assertEqual(first['sent'], 2)
        self.assertEqual(first['pending_after_observed_chains'], 0)
        self.assertEqual(first['offset_links'], 0)
        self.assertLess(first['end_at'], 500)
        self.assertEqual(first['exchange_at'], 550)

    def test_enemy_own_pending_is_offset_before_attack_reaches_us(self):
        enemy = side(); enemy.update(confirmed=100, normal_confirmed=100)
        first = self.simulate(enemy=enemy, events=self.events())
        self.assertEqual(first['pending_after_observed_chains'], 898)

    def test_margin_rates_apply_at_each_sides_actual_link(self):
        change = [dict(frame=400, target_point=60)]
        first = self.simulate(margin=dict(enemy_rate_events=change))
        self.assertEqual(first['pending_after_observed_chains'], 2)
        first = self.simulate(margin=dict(enemy_rate_events=change,
                                         rate_events=[dict(frame=0, target_point=60)]))
        self.assertEqual(first['pending_after_observed_chains'], 0)

    def test_sub_rate_offset_earns_one_gauge_step(self):
        own = side(); own.update(confirmed=1, normal_confirmed=1)
        first = self.simulate(own=own, points=40)
        self.assertEqual(first['cancelled'], 1)
        self.assertEqual(first['offset_links'], 1)
        self.assertEqual(first['pending_after_observed_chains'], 2)

    def test_forecast_removes_nuisance_already_dropped_on_this_move(self):
        own = side(); own.update(confirmed=35, normal_confirmed=35)
        first = choose(self.engine.native, self.engine.scoring, own, 120,
                       allowed_placements={(0, 'U')})['choice']
        self.assertEqual(first['chain'], 0)
        self.assertEqual(first['dropped'], 30)
        self.assertEqual(first['pending_after_observed_chains'], 5)


if __name__ == '__main__':
    unittest.main()
