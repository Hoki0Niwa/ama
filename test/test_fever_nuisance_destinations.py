"""Packets remain in their destination across entry and counter prediction."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'test'))
from fever_fixtures import NATIVE, SOLO, side, request, seed3
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.nuisance import Trays
from fever_battle import tactics


class DestinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT / 'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_fever_offsets_its_flying_tray_before_held_normal_confirmed(self):
        enemy = side('fever')
        enemy.update(normal_confirmed=10, fever_unconfirmed=6, unconfirmed=6)
        trays = Trays(enemy)
        self.assertEqual(trays.offset(10), 0)
        self.assertEqual(trays.values, dict(normal=[6, 0], fever=[0, 0]))
        own = side('normal', queue=['2:RY'])
        result = tactics.choose(self.engine.native, self.engine.scoring, own, 120, 1,
            self.engine.policy['normal_tactics'], enemy=enemy,
            enemy_events=[dict(type='link', frame=1, points=1200), dict(type='end', frame=2)],
            allowed=[dict(x=0, r='U')])
        observed = result['tactics_forecast']['choice']['enemy_trays']
        self.assertEqual(observed['normal_confirmed'], 6)
        self.assertEqual(observed['fever_unconfirmed'], 0)

    def test_native_does_not_merge_normal_and_fever_pending(self):
        own = side('normal', queue=['2:RY'])
        outputs = []
        for destination in ('normal', 'fever'):
            enemy = side('fever')
            enemy[destination + '_confirmed'] = 12
            enemy['confirmed'] = enemy['fever_confirmed']
            result = tactics.choose(self.engine.native, self.engine.scoring, own, 120, 1,
                self.engine.policy['normal_tactics'], enemy=enemy, allowed=[dict(x=0, r='U')])
            outputs.append(result['tactics_forecast']['choice']['enemy_trays'])
        self.assertNotEqual(*outputs)
        self.assertEqual(outputs[0]['normal_confirmed'], 12)
        self.assertEqual(outputs[1]['fever_confirmed'], 12)

    def test_full_gauge_does_not_reroute_a_link_before_the_entry_edge(self):
        own = side('normal', seed3(), ['2:RY'])
        own['character'] = 'arle'
        enemy = side()
        enemy.update(gauge=7, nuisance_destination='normal')
        result = tactics.choose(self.engine.native, self.engine.scoring, own, 30, 1,
            self.engine.policy['normal_tactics'], enemy=enemy,
            fever=dict(enemy_fever=True, enemy_fever_at=100000, their_end=100000))
        fires = [c for c in result['tactics_forecast']['candidates'] if c['sent']]
        self.assertTrue(fires)
        for c in fires:
            self.assertEqual(c['enemy_trays']['fever_confirmed'], 0)
            self.assertGreater(c['enemy_trays']['normal_confirmed'], 0)
            self.assertEqual(c['projected_disrupt'], 0)

    def test_prepared_settings_reuse_the_second_decision_without_search(self):
        own = side('normal', queue=['2:BG', '2:RY', '2:GB'])
        own.update(character='arle', mode_generation=2)
        req = request(own)
        req.update(decision_budget_ms=100, second_target_chain=14)
        prepared = self.engine.answer(dict(req, op='prepare', placement=dict(x=0, r='U')))
        self.assertTrue(prepared['prepared'])
        # Apply the actual predicted board and queue shift, as the bridge observes them.
        locked = self.engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0], x=0, r='U'))
        born = dict(own, field=locked['field'], queue=own['queue'][1:], piece_id=1, dropset_index=1, moves_since_chain=1)
        current = dict(req, self=born)
        with patch.object(self.engine.solo, 'ask', wraps=self.engine.solo.ask) as solo:
            result = self.engine.answer(current)
        self.assertTrue(result['search_reused'])
        solo.assert_not_called()


if __name__ == '__main__':
    unittest.main()
