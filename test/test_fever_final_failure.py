"""Final failure preserves ignition; margin conversion follows pop times."""
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'test'))
from fever_fixtures import NATIVE, SOLO, request, side
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.margin import MarginForecast, rate_at
from fever_battle.uncertainty import choose


class FinalFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def one_chain(self, remaining):
        rows = ['......']*13 + ['GGG.RR']
        own = side('fever', rows, ['2:GY'])
        own.update(seed_chain=5, seed_base=5, remaining_frames=remaining, normal_confirmed=50)
        return request(own)

    def test_held_packet_with_time_left_is_weighed_by_expected_points(self):
        req = self.one_chain(300)
        reply = self.engine.answer(req)
        self.assertEqual(reply['seed_forecast']['strategy'], 'value')
        self.assertFalse(reply['seed_forecast']['choice']['dead'])
        self.assertIn('expected_points', reply['seed_forecast']['choice'])

    def test_last_active_piece_fires_even_after_clock_zero_without_new_time(self):
        for remaining in (20, 0):
            reply = self.engine.answer(self.one_chain(remaining))
            self.assertEqual(reply['action'], 'place')
            self.assertGreater(reply['chain'], 0)
            self.assertLess(reply['chain'], 5)
            forecast = reply['seed_forecast']
            self.assertTrue(forecast['intentional_seed_failure'])
            self.assertEqual(forecast['failure_avoidance_status'], 'final_piece_chain_outlasts_clock')
            self.assertEqual(forecast['choice']['time_reward_frames'], 0)
            self.assertEqual(forecast['choice']['remaining_after_rewards'], 0)
            self.assertFalse(forecast['new_seed_spawn_possible'])

    def test_split_range_counts_current_piece_without_reading_future_colors(self):
        budget = self.engine.answer(self.one_chain(300))['seed_forecast']['remaining_piece_budget']
        self.assertTrue(budget['includes_current'])
        self.assertLess(budget['minimum_estimate'], budget['maximum_estimate'])

    def test_cached_build_cannot_spend_last_active_piece_after_a_late_spawn(self):
        own = self.one_chain(50)['self']
        reply = dict(fire=False, seed_forecast=dict(choice=dict(end_at=28)))
        self.assertTrue(self.engine._stacking_still_fits(own, reply))
        own['remaining_frames']=30
        self.assertFalse(self.engine._stacking_still_fits(own, reply))

    def test_margin_boundary_converts_enemy_pop_before_drop_in_both_models(self):
        own = side('fever', queue=['2:RG'])
        events = [dict(type='link', frame=20, points=720), dict(type='end', frame=21)]
        margin = dict(rate_events=[dict(frame=20, target_point=90)],
                      enemy_rate_events=[dict(frame=20, target_point=90)])
        native = self.engine.seed_solver.solve(own,120,True,enemy_events=events,margin=margin)
        self.assertEqual(native['choice']['dropped'],8)
        own = side(queue=['2:RG']); own['garbage_phase']=None
        python = choose(self.engine.native,self.engine.scoring,own,120,enemy_events=events,margin=margin)
        self.assertEqual(python['choice']['dropped'],8)
        normal = self.engine.garbage_search.search('raffina', own['field'], own['queue'],
            0,0,0,120,0,enemy_events=events,margin=margin)
        self.assertEqual(normal['path'][0]['dropped'],8)

    def test_recorded_fever_drop_check_includes_one_row_split(self):
        report=json.loads((ROOT/'data/fever/baselines/2026-10-06-fever-watch-initial.json').read_text(encoding='utf-8'))
        drops=[r for r in report['boundaries']['drops'] if r['mode']=='fever' and 'split_rows' in r]
        self.assertEqual(len(drops),3)
        self.assertTrue(all(r['exact_edge'] and r['lock_edge_exact'] for r in drops))
        self.assertEqual(sorted((r['split_rows'],r['lock_to_drop']) for r in drops),[(0,14),(0,14),(1,24)])
        self.assertEqual({r['lock_to_check_without_split'] for r in drops},{14})


class MarginTests(unittest.TestCase):
    def packet(self, frame, rate=120, **extra):
        return dict(match_id='margin-match',frame=frame,target_point=rate,**extra)

    def test_unknown_setting_does_not_assume_official_default_in_live_match(self):
        report = MarginForecast().observe(self.packet(11510))
        self.assertEqual(report['rate_events'],[])
        self.assertEqual(report['status'],'observed_rate_only_margin_setting_unknown')

    def test_explicit_boundary_changes_rate_at_pop_not_at_start_of_chain(self):
        policy = dict(start_frame=11520,initial_target_point=120)
        report = MarginForecast().observe(self.packet(11500,margin_policy=policy))
        self.assertEqual(rate_at(120,report['rate_events'],19),120)
        self.assertEqual(rate_at(120,report['rate_events'],20),90)
        self.assertEqual(rate_at(120,report['rate_events'],980),60)
        self.assertEqual(rate_at(120,report['rate_events'],1940),45)

    def test_observed_boundaries_keep_opponent_earlier_and_own_later(self):
        model=MarginForecast()
        model.observe(self.packet(11510))
        report=model.observe(self.packet(11530,90))
        self.assertEqual(report['margin_start_frame_bounds'],[11511,11530])
        self.assertEqual(report['enemy_rate_events'][0]['frame'],941)
        self.assertEqual(report['rate_events'][0]['frame'],960)
        model.observe(self.packet(12470,90))
        report=model.observe(self.packet(12490,60))
        self.assertEqual(report['observed_changes'],2)
        self.assertEqual(report['margin_start_frame_bounds'],[11511,11530])

    def test_inconsistent_live_rates_disable_extrapolation(self):
        model=MarginForecast(); model.observe(self.packet(100))
        model.observe(self.packet(110,90))
        report=model.observe(self.packet(130,60))
        self.assertEqual(report['rate_events'],[])
        self.assertEqual(report['status'],'observed_rate_only_margin_setting_unknown')


if __name__ == '__main__': unittest.main()
