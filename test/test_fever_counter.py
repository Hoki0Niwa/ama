"""Do not spend a normal mainline on a counter that loses to the observed tail."""
from pathlib import Path
import sys
import json
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from test_fever_mode import NATIVE, SOLO, request, side, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.fever_defense import choose as defend
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

    def defend(self, own, events=None, enemy=None, **kwargs):
        return defend(self.engine.native, self.engine.scoring, own, 120, 1,
                      enemy_events=events, enemy=enemy or side(), **kwargs)

    def test_builder_mainline_cannot_answer_large_tail_after_it_finishes(self):
        own = self.own()
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=1, r='U')):
            with patch.object(self.engine, '_enemy_events', return_value=self.events()):
                reply = self.engine.answer(request(own))
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['reason'], 'fever_wait_hoard_until_drop')
        forecast = reply['mainline_counter_forecast']
        self.assertEqual(forecast['rejected_move']['chain'], 3)
        self.assertEqual(forecast['pending_after_observed_chains'], 1011)
        self.assertEqual(forecast['gauge_after'], 3)
        self.assertEqual(reply['decision_dependencies'], ['self', 'enemy'])

    def test_pending_packet_alone_also_blocks_insufficient_builder_fire(self):
        reply = self.defend(self.own(), build=lambda: (1, 'U'))
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['mainline_counter_forecast']['pending_after_observed_chains'], 11)

    def test_full_counter_keeps_the_builder_fire(self):
        reply = self.defend(self.own(1), self.events(120), build=lambda: (1, 'U'))
        self.assertEqual(reply['chain'], 3)
        self.assertEqual(reply['reason'], 'fever_wait_builder_clear')
        self.assertNotIn('mainline_counter_forecast', reply)

    def test_one_offset_from_entry_uses_small_clear(self):
        reply = self.defend(self.own(200, gauge=6), self.events(), build=lambda: (1, 'U'))
        self.assertEqual(reply['chain'], 1)
        self.assertEqual(reply['reason'], 'fever_wait_conserve')

    def test_only_reachable_emergency_entry_is_not_forbidden(self):
        reply = self.defend(self.own(200, gauge=4), self.events(),
                            allowed=[dict(x=1, r='U')], build=lambda: (1, 'U'))
        self.assertEqual((reply['x'], reply['r'], reply['chain']), (1, 'U', 3))
        self.assertEqual(reply['reason'], 'fever_wait_conserve')

    def due_mainline(self, pending=1000):
        refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows = list(next(s['field'] for s in refs['seeds'] if s['id'] == 'hirazumi-7'))
        rows[4:7] = ['Y.....']*3
        own = side('normal', rows, ['2:YR'])
        own.update(confirmed=pending, normal_confirmed=pending)
        return own

    def test_due_large_packet_preserves_seven_chain_with_one_chain_offset(self):
        reply = self.engine.answer(request(self.due_mainline()))
        self.assertEqual(reply['chain'], 1)
        self.assertEqual(reply['reason'], 'fever_small_offset_preserve_mainline')
        self.assertEqual(reply['preserved_mainline_chain'], 7)
        self.assertEqual(reply['mainline_counter_forecast']['pending_after_observed_chains'], 905)
        self.assertEqual(reply['gauge_forecast']['gauge_after'], 1)
        self.assertFalse(reply['entry_pending_after_chain'])

    def test_due_packet_that_mainline_can_counter_keeps_entry(self):
        reply = self.engine.answer(request(self.due_mainline(90)))
        self.assertEqual(reply['chain'], 7)
        self.assertTrue(reply['entry_pending_after_chain'])

    def test_due_large_packet_keeps_mainline_when_small_clear_is_unreachable(self):
        reply = self.defend(self.due_mainline(), allowed=[dict(x=3, r='R')])
        self.assertEqual(reply['chain'], 7)
        self.assertEqual(reply['reason'], 'fever_wait_conserve')

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
