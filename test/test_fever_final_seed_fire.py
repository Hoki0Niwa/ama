"""A sub-target main fired to end with the opponent's chain when their last Fever seed cannot answer it."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, request
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.timing import ChainTiming
from fever_battle import disruption, tactical_options

RATE = 120
LINKS = 10
WINDOW = 26


class FinalSeedFireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.cfg = cls.engine.policy['normal_build']['final_seed_fire']
        cls.points = cls.engine.scoring.chain('raffina', [dict(groups=[4], colors=1)]*LINKS)
        timing = ChainTiming.for_mode('normal')
        cls.finish = (timing.lock_frames(0, None) + timing.first_link_frames
                      + timing.timeline(cls.points, [1]*LINKS, None, start_offset=0)['end_frame'])
        cls.piece = timing.placement_frames + timing.spawn_frames

    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def placement(self, links=LINKS):
        return dict(x=2, r='U', dead=False, links=[dict(groups=[4], colors=1)]*links, split_distances=[0],
                    fall_distances=[1]*links, field=['......']*14, all_clear=False)

    def choose(self, end_offset=0, hold=(0, 0, 0), incoming=0, links=LINKS, baseline=None, config=None, enemy_pending=0):
        end = self.finish - WINDOW + end_offset
        own = side('normal', queue=['2:RY']); enemy = side('fever'); enemy['seed_chain'] = 8; enemy['fever_confirmed'] = enemy_pending
        events = [dict(type='end', frame=end)]
        if incoming:
            events.insert(0, dict(type='link', frame=end - 10, nuisance=incoming, points=incoming*RATE))
        req = request(own, enemy); req['enemy_chain'] = dict(mode_generation=1, seed_id=1)
        fever = dict(their_end=end)
        with patch.object(self.engine.native, 'ask', return_value=dict(placements=[self.placement(links)])):
            return self.engine.final_seed_fire.choose(req, own, enemy, baseline or dict(fire=False),
                {**self.cfg, **(config or {})}, {}, events=events, hold=hold, fever=fever, rate=RATE,
                after_opening=True), req

    def test_fires_when_our_chain_ends_with_theirs(self):
        reply, _ = self.choose()
        self.assertEqual(reply['reason'], 'normal_final_seed_fire')
        self.assertTrue(reply['fire'])
        self.assertEqual(reply['chain'], LINKS)
        shot = reply['final_seed_fire']
        self.assertEqual(shot['end'], self.finish)
        self.assertEqual(shot['latest_end'], self.finish)

    def test_waits_while_the_next_piece_still_ends_in_the_window(self):
        self.assertIsNone(self.choose(end_offset=self.piece)[0])

    def test_fires_on_the_last_piece_that_can_still_end_in_the_window(self):
        self.assertIsNotNone(self.choose(end_offset=self.piece - 1)[0])

    def test_too_late_for_the_window_does_not_fire(self):
        self.assertIsNone(self.choose(end_offset=-1)[0])

    def test_seventy_must_remain_after_the_main_of_the_board_they_return_to(self):
        sent = sum(self.points) // RATE
        need = self.cfg['min_remaining']
        self.assertEqual(need, 70)
        self.assertIsNotNone(self.choose(hold=(0, 0, 0))[0])
        self.assertIsNotNone(self.choose(hold=(0, 0, (sent - need)*RATE))[0])
        self.assertIsNone(self.choose(hold=(0, 0, (sent - need + 1)*RATE))[0])
        self.assertIsNone(self.choose(hold=(0, 0, (sent + 1)*RATE))[0])

    def test_one_seed_may_follow_but_its_best_score_comes_off_first(self):
        sent = sum(self.points) // RATE
        need = self.cfg['min_remaining']
        self.assertEqual(self.cfg['max_seeds_after'], 1)
        self.assertIsNotNone(self.choose(hold=(1, 0, 0))[0])
        reply, _ = self.choose(hold=(1, (sent - need)*RATE, 0))
        self.assertEqual(reply['final_seed_fire']['fever_reply'], sent - need)
        self.assertIsNone(self.choose(hold=(1, (sent - need + 1)*RATE, 0))[0])
        # Their Fever and then the board they return to, one after the other.
        self.assertIsNotNone(self.choose(hold=(1, (sent - need - 10)*RATE, 10*RATE))[0])
        self.assertIsNone(self.choose(hold=(1, (sent - need - 10)*RATE, 11*RATE))[0])

    def test_two_seeds_after_the_running_chain_is_not_the_last(self):
        self.assertIsNone(self.choose(hold=(2, 0, 0))[0])

    def test_request_switch_overrides_the_policy(self):
        policy = self.engine.policy['normal_build']['final_seed_fire']
        for default, asked, expected in ((True, None, True), (True, False, False), (False, True, True), (False, None, False)):
            policy['enabled'] = default
            req = request(); req['normal_tactics'] = {} if asked is None else dict(final_seed_fire=asked)
            self.assertEqual(self.engine._final_seed_config(req)['enabled'], expected)
        policy['enabled'] = True
        for bad in (1, 'off', None):
            with self.assertRaises(ValueError):
                tactical_options.validate(dict(normal_tactics=dict(final_seed_fire=bad)))
        tactical_options.validate(dict(normal_tactics=dict(final_seed_fire=False)))

    def test_their_remaining_attack_is_offset_before_anything_counts_as_sent(self):
        # While something is pending, every link offsets at least one.
        sent, rest = 0, 0
        for score in self.points:
            amount, rest = divmod(score + rest, RATE)
            sent += max(1, amount)
        reply, _ = self.choose(incoming=6)
        self.assertEqual(reply['final_seed_fire']['sent'], sent - 6)
        self.assertIsNone(self.choose(incoming=sent)[0])
        self.assertIsNone(self.choose(incoming=sent + 31)[0])
        self.assertIsNone(self.choose(incoming=6, hold=(0, 0, (sent - 75)*RATE))[0])

    def test_their_chain_is_offset_by_their_own_pending_before_it_reaches_us(self):
        sent = sum(self.points) // RATE
        self.assertIsNone(self.choose(incoming=sent + 100)[0])
        reply, _ = self.choose(incoming=sent + 100, enemy_pending=sent + 100)
        self.assertGreater(reply['final_seed_fire']['sent'], 0)
        self.assertEqual(reply['final_seed_fire']['incoming'], 0)

    def test_a_chain_below_the_minimum_or_an_existing_fire_is_left_alone(self):
        self.assertIsNone(self.choose(links=self.cfg['min_chain'] - 1)[0])
        self.assertIsNone(self.choose(baseline=dict(fire=True))[0])
        self.assertIsNone(self.choose(config=dict(enabled=False))[0])

    def test_protocol_reply_fires_and_reports_why_not(self):
        probes = json.loads((ROOT/'data/fever/baselines/2026-10-11-second-fire-timing-investigation.json').read_text(encoding='utf-8'))['probes']
        own = deepcopy(next(p for p in probes if p['ai'] == 1 and p['pair'] == 61)['own'])
        for key, value in side('normal').items():
            own.setdefault(key, value)
        own.update(confirmed=0, unconfirmed=0, remainder=0, mode_generation=1, garbage_phase=0)
        enemy = side('fever'); enemy.update(mode_generation=1, seed_id=1)
        req = request(own, enemy); req.update(enemy_chain=dict(mode_generation=1, seed_id=1), second_target_chain=14, op='think')
        for end, reason, why in ((613, 'normal_final_seed_fire', 'fire'), (560, 'normal_build_or_fire', 'outside_window')):
            with patch.object(self.engine, '_observe_enemy_fever', return_value=None),                  patch.object(self.engine, '_enemy_events', return_value=[dict(type='end', frame=end)]),                  patch.object(self.engine, '_enemy_fever', return_value=dict(enemy_fever=True, their_end=end, enemy_seed_level=5, enemy_reply_nuisance=0)),                  patch.object(self.engine, '_enemy_fever_hold', return_value=(0, 0, 0)):
                reply = self.engine.answer(req)
            self.assertEqual((reply['reason'], reply['final_seed_fire_status']['why']), (reason, why))
        self.assertEqual(reply['chain'], 0)
        self.assertTrue(disruption.valid(dict(disruption_timing=dict(kind='jab', target_frame=598, deadline_frame=639,
            duration=636, enemy_generation=1, enemy_seed=1, entering=False, next_seed=True)), dict(enemy=dict(
            mode='fever', mode_generation=1, seed_id=1), frame=0)))

    def test_guard_accepts_only_the_planned_window(self):
        reply, req = self.choose()
        reply = dict(reply, **{'final_seed_fire': reply['final_seed_fire']})
        enemy = req['enemy']
        guard = disruption.contract(req, reply, dict(their_end=self.finish - WINDOW))
        self.assertEqual(guard['kind'], 'jab')
        reply['disruption_timing'] = guard
        self.assertTrue(disruption.valid(reply, req))
        late = deepcopy(req); late['frame'] = 1
        self.assertFalse(disruption.valid(reply, late))


if __name__ == '__main__':
    unittest.main()
