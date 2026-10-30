"""Limit timed offsets to sufficient returns or confirmed margin time."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, request
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.timing import ChainTiming
from fever_battle.chain_to_us import flights_to_us
from fever_battle.gauge_wait import hold_permission

RATE = 120
END = 150


class GaugeWaitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.cfg = cls.engine.policy['normal_build']['gauge_wait']
        cls.timing = ChainTiming.for_mode('normal')

    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def choose(self, points, flights, pending=0, gauge=0, contact=4, dead=False, config=None, loses=False, mode='normal', margin=False):
        own = side(mode, queue=['2:RY']); own.update(confirmed=pending, gauge=gauge)
        enemy = side('normal')
        req = request(own, enemy); req.update(frame=1000)
        if margin:req['margin_policy']=dict(start_frame=1000,initial_target_point=160)
        reply = dict(x=2, r='U', fire=bool(points), link_points=points, selected_move_loses=loses, reason='tactics_offset')
        plan = dict(x=2, r='U', dead=dead, contact_height=contact, links=[dict(groups=[4], colors=1)] * len(points),
                    fall_distances=[1] * len(points))
        with patch.object(self.engine.native, 'ask', return_value=dict(placements=[plan])):
            return self.engine.gauge_wait.choose(req, own, enemy, reply, {**self.cfg, **(config or {})}, RATE, flights), req

    def test_the_hold_is_set_from_the_arrival_times(self):
        # An attack of 8 enters the tray at 160: four links of 2 fired now send their first two back.
        flights = [(160, 8)]
        reply, req = self.choose([2 * RATE] * 4, flights, margin=True)
        status = self.engine.gauge_wait.status
        self.assertEqual(status['why'], 'wait')
        self.assertEqual(status['gauge_now'], 2)
        self.assertEqual(status['gauge_then'], 4)
        self.assertEqual(status['returned'], 0)
        self.assertGreaterEqual(status['gauge_then'], self.cfg['min_gauge_gain'])
        self.assertGreater(reply['hold_frames'], 0)
        self.assertEqual(reply['hold_down_until_frame'], 1000 + reply['hold_frames'])
        # the first launch comes after the entry of one of the flights, `margin` later
        floor = self.cfg['launch_frames'] + self.timing.first_link_frames + self.cfg['fast_lock_frames']
        self.assertIn(reply['hold_frames'] + floor - self.cfg['margin_frames'], [f for f, _ in flights])

    def test_normal_weak_chain_is_not_held_for_gauge(self):
        reply,_=self.choose([2*RATE]*4,[(160,8)])
        self.assertIsNone(reply)
        self.assertEqual(self.engine.gauge_wait.status['why'],'extend_before_entry')
        self.assertFalse(self.engine.gauge_wait.status['allowed'])

    def test_normal_sufficient_return_is_eligible_to_hold(self):
        self.choose([2*RATE]*6,[(160,8)])
        self.assertTrue(self.engine.gauge_wait.status['allowed'])
        self.assertFalse(self.engine.gauge_wait.status['margin'])
        self.assertGreater(self.engine.gauge_wait.status['own_nuisance'],self.engine.gauge_wait.status['incoming_total'])

    def test_low_rate_without_margin_evidence_does_not_allow_a_weak_hold(self):
        req=request(side('normal'));req.update(frame=1000,target_point=5)
        allowed=hold_permission(req,req['self'],[20],5,[(160,8)])
        self.assertFalse(allowed['allowed'])
        self.assertFalse(allowed['margin'])

    def test_observed_margin_start_must_be_reached_for_every_possible_start(self):
        req=request(side('normal'));req.update(frame=1000,target_point=5)
        for latest,expected in ((999,True),(1000,True),(1001,False)):
            status=hold_permission(req,req['self'],[20],5,[(160,8)],
                dict(margin_start_frame_bounds=[990,latest]))
            self.assertEqual(status['allowed'],expected)

    def test_a_flight_only_counts_after_it_has_entered_the_tray(self):
        links = [(60, 2 * RATE)]
        early = self.engine.gauge_wait.fire(links, 0, [(100, 2)], 0, RATE, 0, 1, 24, 12)
        late = self.engine.gauge_wait.fire(links, 0, [(60, 2)], 0, RATE, 0, 1, 24, 12)
        self.assertEqual((early['offsets'], early['returned'], early['remaining']), (0, 2, 2))
        self.assertEqual((late['offsets'], late['returned'], late['remaining']), (1, 0, 0))

    def test_no_attack_on_its_way_does_not_wait(self):
        self.assertIsNone(self.choose([RATE] * 5, [], pending=5)[0])

    def test_a_fire_that_sends_back_a_lot_is_not_held(self):
        reply, _ = self.choose([RATE] * 12, [(100, 3)], pending=1)
        self.assertIsNone(reply)
        self.assertIn(self.engine.gauge_wait.status['why'], ('sends_back', 'gauge_not_worth_waiting', 'fire_now'))

    def test_a_small_gauge_gain_is_not_worth_the_wait(self):
        reply, _ = self.choose([RATE] * 2, [(100, 1)], pending=1, margin=True)
        self.assertIsNone(reply)
        self.assertIn(self.engine.gauge_wait.status['why'], ('gauge_not_worth_waiting', 'fire_now'))

    def test_attack_that_would_land_after_the_chain_is_not_waited_for(self):
        reply, _ = self.choose([RATE] * 3, [(100, 20)], pending=1)
        self.assertIsNone(reply)
        self.assertIn(self.engine.gauge_wait.status['why'], ('extend_before_entry','leaves_too_much', 'fire_now'))

    def test_not_longer_than_the_piece_can_fall_and_rest(self):
        reply, _ = self.choose([2 * RATE] * 5, [(100, 2), (200, 2), (300, 2), (400, 2)], contact=11)
        self.assertIsNone(reply)

    def test_a_dead_or_losing_placement_is_never_held(self):
        flights = [(100, 2), (200, 2), (300, 2), (400, 2)]
        self.assertIsNone(self.choose([2 * RATE] * 5, flights, dead=True)[0])
        self.assertIsNone(self.choose([2 * RATE] * 5, flights, loses=True)[0])

    def test_off_with_a_full_gauge_or_when_disabled(self):
        flights = [(100, 2), (200, 2), (300, 2), (400, 2)]
        self.assertIsNone(self.choose([2 * RATE] * 5, flights, gauge=7)[0])
        self.assertIsNone(self.choose([2 * RATE] * 5, flights, config=dict(enabled=False))[0])

    def test_their_remaining_links_become_timed_flights(self):
        enemy = side('normal')
        events = [dict(type='link', frame=10, points=3 * RATE), dict(type='link', frame=90, points=RATE), dict(type='end', frame=150)]
        self.assertEqual(flights_to_us(events, enemy, RATE), [(34, 3), (114, 1)])
        fever = side('fever')
        self.assertEqual(flights_to_us(events[:1], fever, RATE), [(29, 3)])


if __name__ == '__main__':
    unittest.main()
