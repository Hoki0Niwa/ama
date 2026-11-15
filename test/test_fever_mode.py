"""Mode boundaries, queue routing, deadlines and real native seed transitions."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode import ModeReferee, next_seed
from fever_battle.model import EMPTY, Scoring
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply
from fever_battle.disruption import score_rebuild_safe, valid as disruption_valid
from fever_battle.replay import replay
from fever_battle.reference_seeds import decode
from fever_battle.worker import JsonProcess
from fever_battle.uncertainty import outcomes
from fever_battle.finish import choose as fast_finish, placement_frames
from fever_battle.normal_colors import inspect as inspect_colors

from fever_fixtures import NATIVE, SOLO, request, seed3, seed_with_small_green, side


# With only 2:RY in sight the search would rather thicken the seed's last group and
# wait; the piece that follows shows there is nothing to wait for.
FIRES = ['2:RY', '2:GG']

class ModeTests(unittest.TestCase):
    def setUp(self):
        self.ref = ModeReferee(['raffina', 'ally'])
        self.order = 0

    def event(self, kind, player=0, frame=0, **kwargs):
        self.order += 1
        return self.ref.apply(dict(type=kind, player=player, frame=frame, order=self.order, **kwargs))

    def settle(self, frame=30):
        """Advance to a frame past the launch of zero-amount links (24F normal, 19F Fever)."""
        return self.event('rate', frame=frame, target_point=self.ref.target_point)

    def chain(self, count=1, player=0, all_clear=False, frame=0, points=40):
        name = str(self.order)
        rows = list(EMPTY)
        if not all_clear:
            rows[-1] = '.Y....'
        self.event('place', player, frame, chain=name, result=dict(field=rows, links=[{}]*count))
        for link in range(1, count+1):
            self.event('link', player, frame, chain=name, link=link, points=points)
        return name

    def enter(self, player=0, frame=0):
        self.ref.players[player].gauge = 7
        return self.event('enter', player, frame, clock_running=True)

    def test_offset_per_link_and_enemy_preparation(self):
        self.event('incoming', count=50, confirmed=True, chain='attack', destination='normal')
        name = self.chain(7)
        self.assertLess(self.ref.players[0].gauge, 7)
        self.settle()
        self.assertEqual(self.ref.players[0].gauge, 7)
        self.assertEqual(self.ref.players[1].prepared_frames, 1380)
        with self.assertRaises(ValueError):
            self.event('enter', frame=30, clock_running=True)
        self.event('end', frame=30, chain=name)
        self.event('enter', frame=30, clock_running=True)
        self.assertEqual(self.ref.players[0].mode, 'fever')

    def test_zero_gain_regression_and_no_unearned_gauge(self):
        self.ref = ModeReferee(['raffina', 'ally'], gauge_gain_on_offset=0)
        self.event('incoming', count=30, confirmed=True, chain='attack', destination='normal')
        self.chain(2, points=40)
        self.settle()
        self.assertEqual(self.ref.players[0].gauge, 0)
        self.assertEqual(self.ref.players[1].prepared_frames, 1080)

    def test_three_stage_tray_flying_garbage_counts_and_is_offset_last(self):
        # attack of player 1 is in the air; player 0 already holds a confirmed 2
        self.event('incoming', count=2, confirmed=True, chain='old', destination='normal')
        name = self.chain(points=600, player=1)
        self.settle()
        p = self.ref.players[0]
        self.assertEqual([(q.count, q.confirmed, q.flying) for q in p.packets], [(2, True, False), (5, False, True)])
        self.assertEqual(p.pending(), 7)
        # a counter takes confirmed, then arrived, then flying garbage
        self.assertEqual(p.consume(3), 3)
        self.assertEqual([(q.count, q.confirmed, q.flying) for q in p.packets], [(4, False, True)])
        # the attacker's own end does not confirm flying garbage; the arrival does, once the chain is over
        self.event('end', player=1, frame=30, chain=name)
        self.assertFalse(p.packets[0].confirmed)
        self.assertTrue(self.event('arrive', player=1, frame=30, chain=name, link=1)['confirmed'])
        self.assertTrue(p.packets[0].confirmed and not p.packets[0].flying)

    def test_counter_offsets_again_on_arrival_and_relaunches_the_rest(self):
        self.event('incoming', count=1, confirmed=False, chain='mine', destination='normal')
        name = self.chain(points=600, player=0)       # amount 5 against 1 pending: a counter
        self.settle()
        p0, p1 = self.ref.players
        self.assertEqual(p0.pending(), 0)              # offset 1 at creation
        self.assertEqual(p1.pending(), 0)
        self.event('incoming', frame=30, count=1, confirmed=False, chain='late', destination='normal')
        effect = self.event('arrive', frame=31, chain=name, link=1)
        self.assertEqual((effect['cancelled'], effect['relaunched']), (1, 3))   # 4 left, 1 pending now
        self.assertEqual([(q.count, q.flying) for q in p1.packets], [(3, True)])
        self.assertEqual(self.event('arrive', frame=32, chain=name, link=1)['arrived'], 3)

    def test_minimum_offset_is_decided_at_launch_from_both_trays(self):
        rows = list(EMPTY)
        rows[-1] = '.Y....'
        self.event('place', chain='a', result=dict(field=rows, links=[{}]))
        self.event('link', chain='a', link=1, points=40)
        self.assertEqual(self.ref.players[0].remainder, 40)
        # garbage arriving before the launch is cancelled by the minimum offset
        self.event('incoming', frame=10, count=3, confirmed=False, chain='x', destination='normal')
        self.event('rate', frame=23, target_point=120)
        self.assertEqual(self.ref.players[0].pending(), 3)
        self.event('rate', frame=24, target_point=120)
        self.assertEqual(self.ref.players[0].pending(), 2)
        # nothing pending at launch: the link disappears without an offset
        self.event('end', frame=24, chain='a')
        self.event('place', frame=30, chain='b', result=dict(field=rows, links=[{}]))
        self.event('link', frame=30, chain='b', link=1, points=40)
        self.ref.players[0].packets.clear()
        self.event('rate', frame=60, target_point=120)
        self.assertEqual(self.ref.players[0].pending(), 0)

    def test_preserve_normal_board_and_merge_both_queues(self):
        self.ref.players[0].rows[-1] = 'G.....'
        self.ref.players[0].garbage_phase = 4
        self.event('incoming', count=8, confirmed=True, chain='old', destination='normal')
        self.enter()
        self.event('incoming', count=3, confirmed=True, chain='new', destination='fever')
        self.event('clock', remaining_frames=0, running=False)
        self.event('exit')
        p = self.ref.players[0]
        self.assertEqual(p.rows[-1], 'G.....')
        self.assertEqual(p.pending(True), 11)
        self.assertEqual((p.garbage_phase, p.gauge, p.prepared_frames), (4, 0, 960))

    def test_fever_offsets_active_before_held_and_drops_only_active(self):
        self.event('incoming', count=5, confirmed=True, chain='held', destination='normal')
        self.enter()
        self.event('seed', field=seed3(), seed_id=1, seed_chain=5)
        self.event('incoming', count=2, confirmed=True, chain='active', destination='fever')
        name = self.chain(points=360)
        self.settle()
        self.assertEqual(self.ref.players[0].active_pending(), 0)
        self.assertEqual(self.ref.players[0].pending(), 4)
        self.event('end', frame=30, chain=name)
        self.event('seed', frame=30, field=seed3(), seed_id=2, seed_chain=3)
        effect = self.event('place', frame=30, result=dict(field=seed3(), links=[]))
        self.assertEqual(effect['dropped'], 0)
        self.assertEqual(self.ref.players[0].pending(), 4)

    def test_confirmation_survives_recipient_mode_switch(self):
        name = self.chain(points=600, player=1)
        self.settle()
        self.assertTrue(self.ref.players[0].packets[0].flying)
        self.enter(frame=30)
        self.event('arrive', player=1, frame=30, chain=name, link=1)
        self.assertFalse(self.ref.players[0].held_packets[0].flying)
        self.assertFalse(self.ref.players[0].held_packets[0].confirmed)  # the sender's chain is still running
        self.event('end', player=1, frame=30, chain=name)
        self.assertEqual(self.ref.players[0].held_packets[0].count, 5)
        self.assertTrue(self.ref.players[0].held_packets[0].confirmed)

    def test_remainder_cursor_continues_through_fever_drop_and_return(self):
        self.ref.players[0].garbage_phase = 4
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        self.event('incoming', count=1, confirmed=True, chain='active', destination='fever')
        effect = self.event('place', result=dict(field=seed3(), links=[]))
        self.assertEqual(effect['garbage_phase'], 5)
        self.event('clock', remaining_frames=0, running=False)
        self.event('exit')
        self.assertEqual(self.ref.players[0].garbage_phase, 5)

    def test_timer_stop_resume_and_no_revival_after_expiry(self):
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        self.event('clock', frame=100, remaining_frames=800, running=False)
        self.event('tick', frame=200)
        self.assertEqual(self.ref.players[0].remaining_frames, 800)
        self.event('clock', frame=200, remaining_frames=800, running=True)
        name = self.chain(3, frame=200, all_clear=True)
        self.event('end', frame=1001, chain=name)
        self.assertEqual(self.ref.players[0].remaining_frames, 0)
        self.assertFalse(self.ref.players[0].awaiting_seed)
        self.event('exit', frame=1001)

    def test_any_clear_requires_observed_next_seed(self):
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        name = self.chain(5)
        effect = self.event('end', chain=name)
        self.assertEqual(effect['seed_chain'], 6)
        self.assertEqual(effect['remaining_frames'], 1050)
        self.assertTrue(effect['awaiting_seed'])
        before = self.ref.snapshot()
        with self.assertRaises(ValueError):
            self.event('seed', field=seed3(), seed_id=1, seed_chain=6)
        self.assertEqual(self.ref.snapshot(), before)
        with self.assertRaises(ValueError):
            self.event('place', result=dict(field=seed3(), links=[]))
        self.event('seed', field=seed3(), seed_id=2, seed_chain=6)

    def test_failure_rules_and_limits(self):
        self.assertEqual([next_seed(7, n) for n in (7, 6, 5, 4)], [8, 7, 6, 5])
        self.assertEqual(next_seed(4, 1), 3)
        self.assertEqual(next_seed(9, 9, True), 12)
        self.assertEqual(next_seed(15, 15, True), 15)
        self.assertEqual(next_seed(5, 3, displayed=7), 4)
        self.assertEqual(next_seed(5, 1, displayed=7), 3)

    def test_all_clear_bonus_precedes_failure_floor_as_in_steam(self):
        # FUN_1400505a0: clamp(max(base-2, chain+1+2), 3, 15). Base 9, one-link all clear -> 7, not 9.
        self.assertEqual(next_seed(9, 1, True), 7)
        self.assertEqual(next_seed(9, 5, True), 8)
        self.assertEqual(next_seed(9, 6, True), 9)
        # After a normal all-clear entry the first seed shows base+2; the update starts from the base.
        self.assertEqual(next_seed(5, 6, displayed=7), 7)
        self.assertEqual(next_seed(5, 5, displayed=7), 6)

    def test_single_clear_fails_seed_and_cannot_continue_cleaned_board(self):
        self.enter()
        self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        name = self.chain(1)
        effect = self.event('end', chain=name)
        self.assertEqual(effect['seed_chain'], 3)
        self.assertTrue(effect['awaiting_seed'])
        with self.assertRaises(ValueError):
            self.event('place', result=dict(field=seed3(), links=[]))
        self.event('seed', field=seed3(), seed_chain=3, seed_id=2)
        self.assertEqual(self.ref.players[0].seed_id, 2)

    def test_all_clear_entry_boost_and_time_cap(self):
        self.ref.players[0].prepared_frames = 1850
        name = self.chain(all_clear=True)
        self.event('end', chain=name)
        effect = self.enter()
        self.assertEqual(effect['seed_chain'], 7)
        self.assertEqual(effect['remaining_frames'], 1860)
        self.assertEqual(self.ref.players[0].seed_base, 5)

    def test_normal_all_clear_seed_consumes_entry_bonus(self):
        name = self.chain(all_clear=True)
        self.event('end', chain=name)
        self.event('seed', field=seed3(), seed_chain=4, seed_id=1)
        self.assertEqual(self.enter()['seed_chain'], 5)

    def test_invalid_event_rolls_back_clock_and_mode_and_replay(self):
        self.event('incoming', count=50, confirmed=True, chain='attack', destination='normal')
        name = self.chain(7)
        self.settle()
        self.event('end', frame=30, chain=name)
        self.event('enter', frame=30, clock_running=True)
        before = self.ref.snapshot()
        with self.assertRaises(ValueError):
            self.event('exit', frame=20)
        self.assertEqual(self.ref.snapshot(), before)
        self.assertTrue(replay(dict(characters=['raffina', 'ally'], events=self.ref.log,
                                    state=self.ref.snapshot()))['state_matches'])


class NativeModeTests(unittest.TestCase):
    def test_maximize_score_prefers_higher_scoring_shorter_chain(self):
        field = ['......'] * 7 + ['.B....', '.Y....', '.BB.Y.', '.GB.R.', 'BBR.R.', 'GGBYBG', 'BYGYYB']
        solo = dict(rule='fever', solo=True, character='arle', dropset_index=0,
                    self=dict(field=field, queue=['2:RY']), beam_width=10, beam_depth=1)
        legacy = self.engine.solo.ask(dict(solo, fire=True))
        self.assertEqual((legacy['chain'], legacy['eval']), (3, 1170))
        result = self.engine.solo.ask(dict(solo, fire=True, maximize_score=True))
        self.assertEqual((result['chain'], result['eval']), (2, 1240))
        self.assertEqual(result['fire_line_points'], 118720)
        build = self.engine.solo.ask(dict(solo, maximize_score=True, include_next=True))
        self.assertFalse(build['fire'])
        self.assertEqual(build['next_chain'], 0)
        self.assertEqual(build['fire_line_points'], 118720)

    def test_maximize_score_keeps_building_toward_recorded_sixteen_chain(self):
        field = ['......', 'B....Y', 'G...GB', 'GY..YB', 'BGBRBG', 'RBBGGR', 'GGRRGB',
                 'GBBGYY', 'RYBYRR', 'RRGYBY', 'BYGGRY', 'BBYRBY', 'RRYRYR', 'GGYBYR']
        pieces = ['2:RG', '2:RG', '2:GY', '2:BR', '2:BG', '2:GB', '2:YR']
        for turn in range(5):
            result = self.engine.solo.ask(dict(
                rule='fever', solo=True, character='arle', dropset_index=turn + 5,
                self=dict(field=field, queue=pieces[turn:turn + 3]), beam_width=250, beam_depth=16,
                maximize_score=True, include_next=True, margin=1, plain_pairs=True, special_moves=True,
                moves=37 + turn))
            self.assertNotIn('score_rebuild', result)
            field = result['next_field']
            if turn < 4:
                self.assertEqual(result['next_chain'], 0, (turn, result))
            if turn == 1:
                self.assertFalse(result['fire'])
        self.assertEqual((result['next_chain'], result['next_score']), (16, 189010))

    def test_score_rebuild_requires_majority_when_safe_build_is_available(self):
        field = ['......', '.....B', '....RB', '....BR', '..YGBB', '..YGRY', '.YBYRR',
                 'YYBRBY', 'BBYBRY', 'YGYBRY', 'RRGRBB', 'YRGRYB', 'YBGBGG', 'YBRRGR']
        solo = dict(rule='fever', solo=True, character='satan', dropset_index=10,
                    self=dict(field=field, queue=['2:YB', '4:GGRR', '2:BB']),
                    beam_width=250, beam_depth=16, maximize_score=True, include_next=True,
                    margin=1, plain_pairs=True, special_moves=True, moves=26)
        result = self.engine.solo.ask(dict(solo, score_rebuild=True))
        self.assertEqual((result['x'], result['r']), (1, 'U'))
        reset = result['score_rebuild']
        self.assertEqual((reset['baseline_target_bags'], reset['rebuild_target_bags']), (2, 5))
        disabled = self.engine.solo.ask(solo)
        cooldown = self.engine.solo.ask(dict(solo, moves=11, score_rebuild=True))
        for answer in (disabled, cooldown):
            self.assertNotIn('score_rebuild', answer)
            self.assertEqual((answer['x'], answer['r'], answer['next_chain']), (0, 'D', 0))
            quiet = next(root for root in answer['root_values'] if (root['x'], root['r']) == (0, 'D'))
            self.assertGreater(quiet['next_room'], 0)

    def test_score_rebuild_uses_light_relief_on_recorded_boards(self):
        cases = (
            (['......', '......', '......', 'RR..Y.', 'BRGYY.', 'RGGBB.', 'RYYRG.',
              'RYBRGY', 'BGGYBY', 'BYYBBR', 'BYBGYR', 'RGBGYG', 'RRGBRY', 'GGYBRY'],
             ['2:YY', '2:RB', '4:RRBB'], 9, 25, 60, 'light', 1),
            (['......', 'YY...G', 'RR..YR', 'BB..BB', 'RB..BR', 'BRRGYB', 'BRGYGB',
              'RYBBGB', 'RGBGRY', 'RYRBRG', 'BBRYBB', 'BYYGGG', 'RRYRYR', 'GGGRYR'],
             ['0:Y', '2:BG', '2:BY'], 15, 31, 69, None, 12),
        )
        for field, queue, index, moves, before, relief, cleared in cases:
            with self.subTest(relief=relief):
                result = self.engine.solo.ask(dict(
                    rule='fever', solo=True, character='satan', dropset_index=index,
                    self=dict(field=field, queue=queue), beam_width=250, beam_depth=16,
                    maximize_score=True, include_next=True, margin=1, plain_pairs=True, special_moves=True,
                    moves=moves, score_rebuild=True))
                self.assertEqual(result['next_chain'], cleared)
                if relief:
                    report = result['score_rebuild']
                    self.assertEqual((report['relief'], report['before_cells'], report['after_cells']),
                                     (relief, before, 57))
                else:
                    self.assertNotIn('score_rebuild', result)
                    self.assertEqual(result['next_score'], 109870)

    def test_score_rebuild_waits_when_opponent_can_have_a_main(self):
        own = dict(side(), moves_since_chain=26)
        enemy = side(rows=['......'] * 5 + ['RGB...'] + ['RYGBRY'] * 8)
        req = request(own, enemy)
        reply = dict(disruption_timing=dict(kind='score_rebuild'))
        self.assertTrue(score_rebuild_safe(req, own))
        self.assertTrue(disruption_valid(reply, req))
        enemy['field'][5] = 'RGBY..'
        self.assertFalse(score_rebuild_safe(req, own))
        self.assertFalse(disruption_valid(reply, req))

    def test_score_lookahead_preserves_build_over_short_fires(self):
        cases = (
            ('schezo', 9, ['2:GY', '0:R', '2:BR'],
             ['......', '....YY', '....RY', '....RR', '..YYGY', '..YBGG', 'RRRYBY',
              'YYYGYY', 'RGRBGR', 'RGRGRR', 'BBGGYB', 'GYRRYB', 'BGGBGR', 'BGBBGR'],
             (0, 'D'), 69590, 0),
            ('satan', 2, ['2:RY', 'L:RRR', '2:YB'],
             ['......', '.....B', '.....R', '.....R', '.....G', '....RR', 'R...BR',
              'Y...YG', 'R...RG', 'R.Y.RG', 'YRBRBB', 'GRBRYB', 'BBGYYG', 'GGRRRG'],
             (3, 'U'), 29920, 370),
        )
        for character, index, queue, field, expected, old_points, new_points in cases:
            with self.subTest(character=character):
                own = dict(side(rows=field, queue=queue), character=character)
                result = self.engine.solo.ask(dict(
                    rule='fever', solo=True, character=character, dropset_index=index,
                    self=dict(field=field, queue=queue), beam_width=250, beam_depth=16,
                    maximize_score=True, include_next=True, margin=1, plain_pairs=True, special_moves=True))
                placements = self.engine.native.ask(dict(op='placements', field=field, piece=queue[0]))['placements']
                choice = next(p for p in placements if (p['x'], p['r']) == (result['x'], result['r']))
                old = self.engine._forced_lookahead(own, placements, choice)
                self.assertEqual(sum(self.engine.scoring.chain(character, old['links'])), old_points)
                selected = self.engine._forced_lookahead(own, placements, choice, result)
                self.assertEqual((selected['x'], selected['r']), expected)
                self.assertEqual(sum(self.engine.scoring.chain(character, selected['links'])), new_points)
                if character == 'satan':
                    self.assertEqual(len(selected['links']), 2)
                    self.assertEqual(sum(c != '.' for row in selected['field'] for c in row), 36)

    def test_score_plan_fire_is_not_replaced_by_a_small_clear(self):
        # Recorded 2026-11-09 (alex, 17:07 round 6, 2P): the score plan fires 2U and an 11 chain follows two
        # pieces on, with no quiet placement left. A 1-5 link "relief" clear in its place left a 3 chain.
        field = ['......', '.R....', 'BG..BY', 'YG..BB', 'GY.BRG', 'GY.GYB', 'RRBYRR',
                 'BRBGGG', 'BBYRRY', 'RGYBGY', 'BBBGGY', 'RRGYRG', 'GRGGBY', 'RBYYBY']
        queue = ['2:BB', '4:RRGG', '0:R']
        own = dict(side(rows=field, queue=queue), character='alex', pattern='2LJL22LJL24022L2', dropset_index=9)
        self.engine.sync_pattern(own)
        self.addCleanup(self.engine.sync_pattern, dict(character='alex'))
        result = self.engine.solo.ask(dict(
            rule='fever', solo=True, character='alex', dropset_index=9, self=dict(field=field, queue=queue),
            beam_width=250, beam_depth=16, maximize_score=True, include_next=True, margin=1,
            plain_pairs=True, special_moves=True, moves=25))
        self.assertTrue(result['fire'])
        placements = self.engine.native.ask(dict(op='placements', field=field, piece=queue[0]))['placements']
        choice = next(p for p in placements if (p['x'], p['r']) == (result['x'], result['r']))
        selected = self.engine._forced_lookahead(own, placements, choice, result)
        self.assertEqual((selected['x'], selected['r']), (result['x'], result['r']))

    def test_score_main_fires_after_a_small_clear(self):
        # Recorded Ciel and Rulue starts, with their original queue lengths.
        cases = (
            ('ciel', '2202422024220224', 7, 23,
             ['0:Y', '2:GY', '4:GGRR', '2:BB', '2:GB', '0:B', '2:RY', '2:BR'],
             ['......', '......', 'B....Y', 'BG...Y', 'GR..GG', 'GR.BRR', 'BGGGRG',
              'GRRYBG', 'BGGBGR', 'BYBRGY', 'BRBRBY', 'GRBRBY', 'GBRBRB', 'RBYBRY'],
             # A one-link clear keeps the 13-link main (score_keep_main_clear) and it grows to 16.
             ((1, 0, 0, 0, 0, 16), 232190)),
            ('rulue', None, 13, 29, ['2:RR', '2:BG', '0:Y'],
             ['......', 'G....B', 'GR..YY', 'BR..RR', 'GBYBYY', 'GYYGRY', 'BBGYYB',
              'GBGBYR', 'GGYRBY', 'BYYGGR', 'BGBBRR', 'BGBRGG', 'GYYYBR', 'GRRRBR'],
             # The visible 14 is below the opening's 15-chain minimum, but one link short of the fire line:
             # no build keeps its route, so it is fired (Configs::score_keep_fallback_chain).
             ((2, 0, 14), 153120)),
        )
        for character, pattern, index, piece_id, queue, field, expected in cases:
            with self.subTest(character=character):
                own = dict(side(rows=field, queue=queue), character=character, dropset_index=index,
                           piece_id=piece_id, moves_since_chain=piece_id, normal_chain_max=0)
                if pattern:
                    own['pattern'] = pattern
                    self.addCleanup(self.engine.sync_pattern, dict(character=character))
                req = request(own)
                req.update(match_id=f'post-clear-main-{character}', second_target_chain=0,
                           solo_options=dict(maximize_score=True, beam_width=250, beam_depth=16))
                chains, score = expected
                for step, chain in enumerate(chains):
                    prepared = self.engine.answer(dict(req, op='prepare_observed'))
                    self.assertTrue(prepared['prepared'], prepared)
                    reply = self.engine.answer(req)
                    self.assertTrue(reply['search_reused'], reply['reason'])
                    self.assertEqual(reply['next_chain'], chain)
                    own.update(field=reply['next_field'], queue=own['queue'][1:],
                               piece_id=piece_id + step + 1, dropset_index=(index + step + 1) % 16,
                               moves_since_chain=0 if chain else own['moves_since_chain'] + 1,
                               normal_chain_max=max(own['normal_chain_max'], chain))
                self.assertEqual(reply['next_score'], score)

    def test_forced_clear_on_next_piece_can_preserve_a_score_build(self):
        # Recorded Alex start. All survivable second placements under the build's root clear, but the search
        # still reaches the standard 14 on most virtual queues: the build goes on rather than the 3-chain relief `1L`.
        field = ['......', '......', 'G....R', 'RR...R', 'RGG.YR', 'BBGYRG', 'GYBBRY',
                 'GGBYGR', 'BYYGBR', 'BRBGBR', 'BYYBGB', 'RRYBRB', 'RBGYGG', 'GGYYGR']
        own = dict(side(rows=field, queue=['L:RRB', '0:B', '2:RG']), character='alex',
                   pattern='2222222202L02J04', dropset_index=10, piece_id=26, moves_since_chain=26)
        self.addCleanup(self.engine.sync_pattern, dict(character='alex'))
        req = request(own)
        req.update(match_id='forced-clear-score-build',
                   solo_options=dict(maximize_score=True, beam_width=250, beam_depth=16))
        reply = self.engine.answer(req)
        self.assertEqual((reply['x'], reply['r'], reply['next_chain']), (0, 'U', 0))

    def test_score_build_keeps_the_visible_main_when_next_pieces_fill_the_board(self):
        # Ciel, round 2, pair 26. The previous clear was two pieces earlier.
        field = ['......', 'B.....', 'YY..Y.', 'BY..YB', 'BB..GB', 'GYYGBR', 'GBGGBY',
                 'RBYRYG', 'BYYGGY', 'BRRRGY', 'BGBGBB', 'RRBRRB', 'RBYRGG', 'GBYYGB']
        pieces = ['2:RG', '2:GY', '0:R', '2:RR', '2:RY', '4:BBGG', '2:BY', '2:BB', '0:G', '2:YB']
        own = dict(side(rows=field, queue=pieces[:8]), character='ciel', pattern='2202422024220224',
                   normal_chain_max=1)
        self.addCleanup(self.engine.sync_pattern, dict(character='ciel'))
        req = request(own)
        req.update(match_id='score-visible-capacity-fire',
                   solo_options=dict(maximize_score=True, beam_width=250, beam_depth=16))
        for turn, expected_chain in enumerate((0, 0, 14)):
            own.update(queue=pieces[turn:turn+8], dropset_index=10+turn, piece_id=26+turn,
                       moves_since_chain=2+turn)
            reply = self.engine.answer(req)
            self.assertFalse(reply.get('selected_move_loses'), reply['reason'])
            self.assertEqual(reply['next_chain'], expected_chain)
            own['field'] = reply['next_field']
        self.assertEqual(reply['next_score'], 187580)

    def test_score_build_keeps_a_visible_main_in_recorded_opening_and_second(self):
        fixture = json.loads((ROOT/'data/fever/golden/visible-normal-main.json').read_text(encoding='utf-8'))
        self.addCleanup(self.engine.sync_pattern, dict(character='ciel'))
        with patch.dict(self.engine.solo.sets, fever=fixture['weights']):
            for case in fixture['cases']:
                with self.subTest(seed=case['seed']):
                    reply = None
                    for req, expected in zip(case['requests'], case['chains'], strict=True):
                        own = req['self']
                        if reply is not None:
                            own.update(field=reply['next_field'], moves_since_chain=own_age)
                        self.assertTrue(self.engine.answer(dict(req, op='prepare_observed'))['prepared'])
                        reply = self.engine.answer(req)
                        self.assertTrue(reply['search_reused'], reply['reason'])
                        self.assertEqual(reply['next_chain'], expected, reply['reason'])
                        self.assertFalse(reply.get('selected_move_loses'), reply['reason'])
                        own_age = 0 if expected else own['moves_since_chain'] + 1
                    self.assertEqual(reply['next_score'], case['score'])

    def test_score_opening_waits_on_twelve_or_thirteen_chains_with_room(self):
        fixture = json.loads((ROOT/'data/fever/golden/opening-and-post-drop.json').read_text(encoding='utf-8'))
        with patch.dict(self.engine.solo.sets, fever=fixture['weights']):
            for req in fixture['openings']:
                with self.subTest(character=req['self']['character']):
                    self.assertTrue(self.engine.answer(dict(req, op='prepare_observed'))['prepared'])
                    reply = self.engine.answer(req)
                    self.assertTrue(reply['search_reused'])
                    self.assertEqual(reply['next_chain'], 0)

    def test_score_opening_fires_below_fourteen_for_capacity_or_offset(self):
        fixture = json.loads((ROOT/'data/fever/golden/opening-and-post-drop.json').read_text(encoding='utf-8'))
        for case in fixture['opening_fires']:
            with self.subTest(chain=case['chain'], reason=case['reason']), \
                    patch.dict(self.engine.solo.sets, fever=case['weights']):
                req = case['request']
                self.assertTrue(self.engine.answer(dict(req, op='prepare_observed'))['prepared'])
                reply = self.engine.answer(req)
                self.assertEqual((reply['next_chain'], reply['reason']), (case['chain'], case['reason']))

    def test_recorded_post_drop_recovery_survives_the_former_death_piece(self):
        fixture = json.loads((ROOT/'data/fever/golden/opening-and-post-drop.json').read_text(encoding='utf-8'))
        with patch.dict(self.engine.solo.sets, fever=fixture['weights']):
            for case in fixture['after_drop']:
                with self.subTest(seed=case['seed']):
                    reply = None
                    for req in case['requests']:
                        own = req['self']
                        if reply is not None:
                            own.update(field=reply['next_field'], moves_since_chain=age)
                        self.assertTrue(self.engine.answer(dict(req, op='prepare_observed'))['prepared'])
                        reply = self.engine.answer(req)
                        self.assertFalse(reply.get('selected_move_loses'), reply['reason'])
                        age = 0 if reply['fire'] else own['moves_since_chain'] + 1
                    self.assertEqual(sum(row.count('#') for row in reply['next_field']), case['remaining_garbage'])

    def test_reachable_recovery_keeps_the_larger_main_in_recorded_positions(self):
        cases = json.loads((ROOT/'data/fever/golden/reachable-main-recovery.json').read_text(encoding='utf-8'))['cases']
        for case, expected in zip(cases, ((2, 'L', 1), (2, 'R', 12)), strict=True):
            req = case['request']
            with self.subTest(piece=req['self']['piece_id']), patch.dict(self.engine.solo.sets, fever=case['weights']):
                reply = self.engine.answer(req)
                self.assertTrue(reply['recovery'])
                self.assertEqual((reply['x'], reply['r'], reply['next_chain']), expected)
                self.assertIn(dict(x=reply['x'], r=reply['r']), req['reachable_placements'])
                for age, following in enumerate(case.get('following', [])):
                    following['self'].update(field=reply['next_field'], moves_since_chain=age)
                    self.assertTrue(self.engine.answer(dict(following, op='prepare_observed'))['prepared'])
                    reply = self.engine.answer(following)
                    self.assertEqual(reply['next_chain'], (0, 12)[age])

    def test_recovery_during_an_absorbed_chain_yields_to_incoming_garbage(self):
        fixture = json.loads((ROOT/'data/fever/golden/opening-and-post-drop.json').read_text(encoding='utf-8'))
        req = fixture['absorbed']
        with patch.dict(self.engine.solo.sets, fever=fixture['weights']):
            reply = self.engine.answer(req)
            self.assertEqual(reply['normal_decision_status'], 'garbage_recovery')
            self.assertEqual(reply['next_chain'], 1)
            req['observation']['in_flight']['self']['incoming_in_flight'] = 1
            self.assertNotIn('normal_recovery', self.engine.answer(req))

    def test_forced_lookahead_preserves_a_subtarget_capacity_fire(self):
        # Ciel, round 2, pair 44. Stacking 0D led to a forced loss on pair 46.
        field = ['......', '....GY', '....YB', '.B..YB', '.RGGGB', '.YRBBR', '.RYRBY',
                 '.YBRYG', 'RYBGGY', 'BYRRGY', 'RRBGBB', 'YRBRRB', 'YBYRGG', 'YRYYGB']
        pieces = ['0:R', '2:RB', '2:BR', '4:GGYY', '2:RB', '2:YB', '0:G', '2:GY', '4:GGYY', '2:RB']
        own = dict(side(rows=field, queue=pieces[:8]), character='ciel', pattern='2202422024220224',
                   normal_chain_max=5, moves_since_chain=None, moves_since_chain_status='unknown')
        self.addCleanup(self.engine.sync_pattern, dict(character='ciel'))
        req = request(own)
        req.update(match_id='score-subtarget-capacity-fire',
                   solo_options=dict(maximize_score=True, beam_width=250, beam_depth=16))
        for turn in range(3):
            own.update(queue=pieces[turn:turn+8], dropset_index=12+turn, piece_id=44+turn)
            reply = self.engine.answer(req)
            self.assertFalse(reply.get('selected_move_loses'), reply['reason'])
            if turn == 0:
                self.assertEqual((reply['x'], reply['r'], reply['next_chain']), (1, 'D', 1))
                own.update(moves_since_chain=0, moves_since_chain_status='observed')
            else:
                own['moves_since_chain'] = 0 if reply['next_chain'] else own['moves_since_chain'] + 1
            own['field'] = reply['next_field']

    def test_prepare_accepts_the_placed_piece_before_a_full_queue(self):
        # queue_depth 12 sends the piece being placed plus the 12 its successor sees; a decision still takes 12.
        fill = {'2': '2:RY', '0': '0:R', '4': '4:RRGG', 'L': 'L:RRG', 'J': 'J:RGR', '3': '3:RRR'}
        cycle = self.engine.patterns['raffina']
        thirteen = dict(side(), queue=[fill[cycle[k % 16]] for k in range(13)])
        self.engine.queue_slack = True
        try:
            self.engine.observed_side(thirteen)
        finally:
            self.engine.queue_slack = False
        with self.assertRaises(ValueError):
            self.engine.observed_side(thirteen)

    def test_maximize_score_can_fire_seventeen_chain(self):
        # A one-cell variant of a recorded Satan 16-chain board.
        field = ['......', 'R...YR', 'BB..RG', 'BY.GRB', 'YY.RYB', 'BGYRYY', 'BYBYBB',
                 'GRRYGB', 'GBYRBG', 'BBGRBG', 'GYBYBG', 'RGYBRR', 'RGBYYR', 'RGBBRG']
        result = self.engine.solo.ask(dict(
            rule='fever', solo=True, character='satan', dropset_index=15,
            self=dict(field=field, queue=['0:Y', '2:RG', '2:GY']), beam_width=250, beam_depth=16,
            maximize_score=True, include_next=True, margin=1, plain_pairs=True, special_moves=True, moves=30))
        self.assertTrue(result['fire'])
        self.assertNotIn('score_rebuild', result)
        self.assertEqual(result['fire_line_points'], 129920)
        self.assertEqual((result['next_chain'], result['next_score']), (17, 228570))

    def test_maximize_score_can_be_selected_for_each_normal_build(self):
        for generation, target, maximize_score, expected in (
            (0, 14, True, 'maximize_score'),
            (0, 0, False, 'initial_target'),
            (1, 0, False, 'maximize_score'),
            (1, None, True, 'fill_then_fire'),
        ):
            with self.subTest(generation=generation, target=target, maximize_score=maximize_score):
                own = dict(side(), mode_generation=generation)
                req = dict(request(own), second_target_chain=target)
                req['solo_options']['maximize_score'] = maximize_score
                result = self.engine.answer(req)
                self.assertEqual(result['normal_fire_policy'], expected)
                if expected == 'maximize_score':
                    self.assertIsNone(result['normal_build_target_chain'])
                    self.assertIsNone(result['normal_fire_required_chain'])
                    self.assertGreater(result['normal_fire_line_points'], 0)

    def test_lethal_nuisance_chooses_fast_contact_and_keeps_all_split_time(self):
        rows=['......']*3 + ['.....#']*5 + ['######']*6
        own=side('normal',rows,['2:RY','2:GB']); own.update(confirmed=120,normal_confirmed=120)
        result=fast_finish(self.engine.native,own,budget_ms=1000)
        self.assertIsNotNone(result)
        self.assertLessEqual(result['selected']['finish_after_drops'],2)
        self.assertEqual(result['selected']['estimated_frames'],min(c['estimated_frames'] for c in result['candidates']))
        self.assertTrue(all(d==0 for d in result['selected']['split_distances']))
        c=dict(x=2,r='R',contact_height=10,split_distances=[0,6])
        self.assertGreater(placement_frames(c),placement_frames({**c,'split_distances':[0,0]}))

    def test_no_rescue_dies_by_second_drop_and_never_waits_for_third(self):
        rows=['......']*12+['######']*2
        own=side('normal',rows,['2:RY','2:GB']); own.update(confirmed=120,normal_confirmed=120,
            garbage_phase=None,garbage_phase_status='unknown')
        result=fast_finish(self.engine.native,own,budget_ms=1000)
        self.assertIsNotNone(result)
        self.assertTrue(all(c['finish_after_drops']<=2 for c in result['candidates']))
        answer=self.engine.answer(request(own))
        self.assertEqual(answer['reason'],'no_rescue_fast_finish')
        self.assertTrue(answer['selected_move_loses'])

    def test_the_fast_closure_of_a_lost_position_is_prepared_before_the_piece_appears(self):
        rows=['......']*12+['######']*2
        own=side('normal',rows,['2:RY','2:GB']); own.update(confirmed=120,normal_confirmed=120,
            garbage_phase=None,garbage_phase_status='unknown')
        req=request(own)
        prep=copy.deepcopy(req); prep['op']='prepare_observed'
        result=self.engine.answer(prep)
        self.assertTrue(result['prepared'])
        self.assertIsNotNone(self.engine.prepared)
        now=copy.deepcopy(req); now['frame']=20
        now['observation'].update(frame_before=20,frame_after=20)
        for side_ in (now['self'],now['enemy']): side_['observed_frame']=20
        with patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as native:
            answer=self.engine.answer(now)
        self.assertEqual(answer['reason'],'no_rescue_fast_finish')
        self.assertTrue(answer['selected_move_loses'])
        self.assertTrue(answer['search_reused'])
        self.assertEqual(answer['search_ms'],0.0)
        self.assertNotIn('finish_probe',[call.args[0].get('op') for call in native.call_args_list])

    def test_possible_offset_and_inconclusive_budget_keep_ordinary_play(self):
        own=side('normal',['......']*13+['RRR...'],['2:RY','2:GB'])
        own.update(confirmed=120,normal_confirmed=120,gauge=6,remainder=100)
        self.assertIsNone(fast_finish(self.engine.native,own,budget_ms=1000))
        self.assertIsNone(fast_finish(self.engine.native,own,budget_ms=0))
        answer=self.engine.answer(request(own))
        self.assertTrue(answer['entry_pending_after_chain'])
        self.assertNotEqual(answer['reason'],'no_rescue_fast_finish')

    def test_empty_board_lethal_queue_selects_second_drop_loss_before_third(self):
        own=side('normal',queue=['2:RY','2:GB','L:YYG'])
        own.update(confirmed=300,normal_confirmed=300,garbage_phase=None,garbage_phase_status='unknown')
        result=fast_finish(self.engine.native,own,budget_ms=1000)
        self.assertIsNotNone(result)
        self.assertTrue(all(c['finish_after_drops']<=2 for c in result['candidates']))
        self.assertIn(result['selected']['x'],(2,3))

    def test_enemy_piece_updates_do_not_discard_own_only_normal_decision(self):
        req=request(side('normal'))
        reply=self.engine.answer(req)
        latest=copy.deepcopy(req); latest['enemy'].update(piece_id=1,dropset_index=1,phase='placing')
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        latest['self'].update(confirmed=30,normal_confirmed=30)
        with self.assertRaises(ValueError):authorize_mode_reply(req,reply,latest)

    def test_live_blocked_spawn_returns_current_drop_without_killing_worker(self):
        own=side('normal',['......']*2+['######']*12)
        own.update(confirmed=300,normal_confirmed=300)
        req=request(own); req['active_placement']=dict(x=2,r='U')
        result=self.engine.answer(req)
        self.assertEqual(result['action'],'place')
        self.assertEqual(result['finish_proof'],'blocked_spawn_observed_current_pose')
        self.assertTrue(result['selected_move_loses'])
        with self.assertRaisesRegex(ValueError,'already dead'):
            self.engine.native.ask(dict(op='placements',field=own['field'],piece=own['queue'][0]))

    def test_observed_current_drop_can_rescue_a_board_above_search_death_threshold(self):
        own=side('normal',['......']*2+['..R...']*3+['.##...']*9)
        own.update(confirmed=120,normal_confirmed=120,remainder=100)
        req=request(own); req['active_placement']=dict(x=1,r='U')
        result=self.engine.answer(req)
        self.assertEqual(result['reason'],'observed_current_pose_drop')
        self.assertFalse(result['selected_move_loses'])
        self.assertTrue(result['fire'])

    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_big_puyo_color_is_present_in_all_live_policy_branches(self):
        for mode in ('normal', 'fever'):
            for unknown in (False, True):
                own=side(mode, seed3() if mode=='fever' else EMPTY,
                    ['0:R','2:GB','2:YY'])
                own['dropset_index']=5
                if unknown:
                    own.update(garbage_phase=None,garbage_phase_status='unknown',confirmed=3)
                    own['fever_confirmed' if mode=='fever' else 'normal_confirmed']=3
                reply=self.engine.answer(request(own))
                self.assertEqual(reply['action'],'place')
                self.assertEqual(reply['color'],'RYGB'['URDL'.index(reply['r'])])

    def test_big_puyo_preparation_has_the_color_required_before_spawn(self):
        own=side('normal',queue=['2:RY','0:R','2:GB']); own['dropset_index']=4
        req=request(own); first=self.engine.answer(req)
        req.update(op='prepare_normal',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(req)
        self.assertTrue(prepared['prepared'])
        placement=prepared['plan']['placement']
        self.assertEqual(placement['color'],'RYGB'['URDL'.index(placement['r'])])

    def prepared_next_request(self):
        original=request(side('normal',queue=['2:RY','2:BB','L:RRY']))
        first=self.engine.answer(original)
        preparation=copy.deepcopy(original)
        preparation.update(op='prepare_normal',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'])
        self.assertEqual(prepared['searched_visible'],2)
        plan=prepared['plan']
        self.assertEqual(plan['field'],first['next_field'])
        self.assertEqual(plan['queue'],original['self']['queue'][1:])
        self.assertEqual(plan['source_queue'],original['self']['queue'])
        self.assertEqual((plan['piece_id'],plan['dropset_index']),(1,1))
        current=copy.deepcopy(original)
        current['self'].update(field=first['next_field'],queue=original['self']['queue'][1:],
            piece_id=1,dropset_index=1,moves_since_chain=1)
        return current

    def test_normal_prefetch_reuses_visible_two_with_fresh_battle_identity(self):
        current=self.prepared_next_request()
        # A newly observed NEXT2 is included in the live request but not in the
        # already completed two-visible-piece preparation.
        current['self']['queue'].append('2:GY')
        current['frame']=20
        current['observation'].update(frame_before=20,frame_after=20)
        for side_ in (current['self'],current['enemy']):side_['observed_frame']=20
        current['enemy']['phase']='placing'
        # Opponent changes do not force repeating the own-board builder.
        with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
            reply=self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_search_reused'])
        self.assertEqual(reply['decision_identity']['frame'],20)
        self.assertEqual(reply['searched_visible'],2)
        self.assertTrue(authorize_mode_reply(current,reply,current))

    def test_normal_prefetch_misses_on_changed_board_piece_or_generation(self):
        for change in ('board','queue','mode_generation'):
            current=self.prepared_next_request()
            if change=='board':current['self']['field'][-1]=current['self']['field'][-1][:5]+'G'
            elif change=='queue':current['self']['queue'][0]='2:GG'
            else:current['self']['mode_generation']+=1
            with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
                reply=self.engine.answer(current)
            self.assertFalse(reply['normal_search_reused'])
            build.assert_called_once()

    def prepared_with_explicit_four_piece_queue(self, ahead='2:GY'):
        original=request(side('normal',queue=['2:RY','2:BB','L:RRY']))
        first=self.engine.answer(original)
        preparation=copy.deepcopy(original)
        preparation['self']['queue'].append(ahead)
        preparation.update(op='prepare_normal',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'],prepared)
        current=copy.deepcopy(original)
        current['self'].update(field=first['next_field'],queue=original['self']['queue'][1:]+[ahead],
            piece_id=1,dropset_index=1,moves_since_chain=1)
        return prepared,current

    def test_explicit_four_piece_queue_prepares_with_three_known_pieces_and_is_reused_when_it_appears(self):
        prepared,current=self.prepared_with_explicit_four_piece_queue()
        self.assertEqual(prepared['searched_visible'],3)
        self.assertEqual(prepared['plan']['queue'],['2:BB','L:RRY','2:GY'])
        current['frame']=20
        current['observation'].update(frame_before=20,frame_after=20)
        for side_ in (current['self'],current['enemy']):side_['observed_frame']=20
        with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
            reply=self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_search_reused'])
        self.assertEqual(reply['searched_visible'],3)
        self.assertTrue(authorize_mode_reply(current,reply,current))

    def test_known_queue_decision_is_discarded_when_another_piece_appears(self):
        _,current=self.prepared_with_explicit_four_piece_queue()
        current['self']['queue'][2]='2:YY'
        with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
            reply=self.engine.answer(current)
        self.assertFalse(reply['normal_search_reused'])
        build.assert_called_once()

    def test_implicit_ahead_piece_is_rejected(self):
        original=request(side('normal',queue=['2:RY','2:BB','L:RRY']))
        first=self.engine.answer(original)
        original.update(op='prepare_normal',placement=dict(x=first['x'],r=first['r']),ahead_piece='L:RRY')
        with self.assertRaisesRegex(ValueError,'ahead_piece'):
            self.engine.answer(original)

    def test_normal_prefetch_bypassed_when_incoming_nuisance_changes(self):
        current=self.prepared_next_request()
        current['self'].update(confirmed=3,normal_confirmed=3,garbage_phase=None,garbage_phase_status='unknown')
        reply=self.engine.answer(current)
        self.assertNotIn('normal_search_reused',reply)
        self.assertIn('tactics_forecast',reply)

    def fired_request(self, enemy_chain=False):
        own=side('normal',queue=['2:RR','2:BB','L:RRY'])
        own['field'][-1]='RRR...'
        req=request(own)
        placements=self.engine.native.ask(dict(op='placements',field=own['field'],piece='2:RR'))['placements']
        fired=next(p for p in placements if p['links'])
        req.update(op='prepare_normal',placement=dict(x=fired['x'],r=fired['r']))
        return req

    def test_normal_prefetch_predicts_the_board_after_a_clear_with_nothing_open(self):
        # What a chain leaves, the offset and the fall of what stays confirmed follow from the rules: the
        # whole decision for the next piece is kept, with a signature that rejects it if the board is another.
        result=self.engine.answer(self.fired_request())
        self.assertTrue(result['build_only'])
        self.assertNotIn('plan',result)
        self.assertIsNotNone(result['prepared_state']['prepared'])
        self.assertIsNotNone(self.engine.prepared)
        self.assertEqual(result['prepared_state']['prepared'][4],len(self.engine.execution_request['self']['queue']))

    def test_the_decision_prepared_across_a_clear_serves_the_piece_that_finds_the_expected_board(self):
        req=self.fired_request()
        self.engine.answer(req)
        expected=copy.deepcopy(self.engine.execution_request)
        now=copy.deepcopy(expected)
        for other in (False,True):
            current=copy.deepcopy(now)
            if other:
                current['self']['field'][-1]=current['self']['field'][-1][:5]+'G'
            self.engine.answer(dict(req))        # prepares again: the prepared decision is kept for one think only
            with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
                reply=self.engine.answer(current)
            self.assertEqual(reply.get('search_reused',False),not other)
            if not other:
                build.assert_not_called()

    def test_predicted_preparation_keeps_its_quality_after_a_slow_search(self):
        original=request(side('normal',queue=['2:RY','2:BB','L:RRY']))
        first=self.engine.answer(original)
        prep=copy.deepcopy(original); prep.update(op='prepare_normal',placement=dict(x=first['x'],r=first['r']))
        cold=[]
        think=self.engine._think
        def spy(req,*args,**kwargs):
            cold.append(bool(req.get('cold_spawn')))
            return think(req,*args,**kwargs)
        with patch.object(self.engine,'_think',side_effect=spy):
            for taken in (1,5000,1):
                self.engine.prepare_ms['normal']=taken
                self.engine.answer(copy.deepcopy(prep))
        self.assertEqual(cold,[False,False,False])

    def test_a_preparation_made_while_the_seed_drops_counts_the_clock_to_the_piece(self):
        own=side('fever',seed3(),['2:RY','2:GB']); own['remaining_frames']=900
        req=request(own,side('normal')); req['op']='prepare_observed'
        self.engine.answer(copy.deepcopy(req))
        usual=self.engine.execution_request['self']['remaining_frames']
        early=copy.deepcopy(req); early['spawn_in_frames']=40
        self.engine.answer(early)
        self.assertEqual(usual-self.engine.execution_request['self']['remaining_frames'],40-self.engine.OBSERVED_SPAWN_FRAMES)
        for bad in (-1,601,'x'):
            with self.assertRaises(ValueError):
                self.engine.answer(dict(copy.deepcopy(req),spawn_in_frames=bad))

    def test_normal_prefetch_keeps_only_the_builder_after_a_clear_while_an_opposing_chain_runs(self):
        req=self.fired_request()
        req['enemy_chain']=dict(mode_generation=0,seed_id=1,trigger_field=seed3(),elapsed=0,scored_links=0)
        result=self.engine.answer(req)
        self.assertTrue(result['build_only'])
        self.assertIsNone(result['prepared_state']['prepared'])
        self.assertIsNone(self.engine.prepared)

    def build_prepared_after_a_clear(self, ahead='2:GY'):
        own=side('normal',queue=['2:RR','2:BB','L:RRY'])
        own['field'][-1]='RRR...'
        req=request(own)
        placements=self.engine.native.ask(dict(op='placements',field=own['field'],piece='2:RR'))['placements']
        fired=next(p for p in placements if p['links'])
        prep=copy.deepcopy(req)
        prep['self']['queue'].append(ahead)
        prep.update(op='prepare',placement=dict(x=fired['x'],r=fired['r']))
        result=self.engine.answer(prep)
        self.assertTrue(result['build_only'],result)
        self.assertEqual(result['searched_visible'],3)
        current=copy.deepcopy(req)
        current['self'].update(field=fired['field'],queue=['2:BB','L:RRY',ahead],piece_id=1,dropset_index=1,
            moves_since_chain=0)
        return current

    def test_the_builder_prepared_after_a_clear_is_used_on_the_expected_board_only(self):
        current=self.build_prepared_after_a_clear()
        current['frame']=40
        current['observation'].update(frame_before=40,frame_after=40)
        for side_ in (current['self'],current['enemy']):side_['observed_frame']=40
        with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
            reply=self.engine.answer(current)
        build.assert_not_called()
        self.assertTrue(reply['normal_build_search_reused'])
        self.assertEqual(reply['action'],'place')
        # another board (a delivery landed) or another piece behind it is searched again
        other=self.build_prepared_after_a_clear()
        other['self']['field'][-1]=other['self']['field'][-1][:5]+'G'
        with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
            self.engine.answer(other)
        build.assert_called()

    def test_nuisance_held_after_a_chain_is_what_the_chain_leaves_of_it(self):
        own=side('normal',queue=['2:RR','2:BB','L:RRY']); own['field'][-1]='RRR...'
        own.update(confirmed=3,normal_confirmed=3)
        placements=self.engine.native.ask(dict(op='placements',field=own['field'],piece='2:RR'))['placements']
        fired=next(p for p in placements if p['links'])
        future=copy.deepcopy(own)
        self.engine._offset_by_chain(future,own,fired['links'],120)
        # a pending packet is offset by at least one per link; what is left is held on both counts
        self.assertLess(future['confirmed'],3)
        self.assertEqual((future['unconfirmed'],future['normal_confirmed']),(0,future['confirmed']))
        # nothing pending: nothing to offset
        clean=copy.deepcopy(own); clean.update(confirmed=0,normal_confirmed=0)
        after=copy.deepcopy(clean); self.engine._offset_by_chain(after,clean,fired['links'],120)
        self.assertEqual((after['confirmed'],after['unconfirmed']),(0,0))

    def test_a_fever_chain_with_little_clock_left_prepares_the_normal_board_it_returns_to(self):
        stored=list(EMPTY); stored[-1]='GG....'
        own=side('fever',seed3(),['2:RY','2:BB','L:RRY'])
        own.update(stored_field=stored,remaining_frames=113,prepared_frames=113)
        req=request(own)
        placements=self.engine.native.ask(dict(op='placements',field=own['field'],piece='2:RY'))['placements']
        fired=next((p for p in placements if p['links']),None)
        if fired is None:self.skipTest('no placement of the fixture seed fires')
        prep=copy.deepcopy(req)
        prep['self']['queue'].append('2:GY')
        prep.update(op='prepare',placement=dict(x=fired['x'],r=fired['r']))
        result=self.engine.answer(prep)
        self.assertTrue(result['build_only'],result)
        # a seed with a long clock left continues in Fever: nothing is prepared for a normal board
        long=copy.deepcopy(prep); long['self']['remaining_frames']=1800
        self.assertFalse(self.engine.answer(long)['prepared'])

    def prepared_seed_request(self, remaining=900):
        original=request(side('fever',seed3(),['2:GG','2:RY','L:RRY']))
        original['self'].update(remaining_frames=remaining)
        first=self.engine.answer(original)
        self.assertEqual((first['action'],first['chain']),('place',0))
        preparation=copy.deepcopy(original)
        preparation.update(op='prepare',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'],prepared)
        plan=prepared['plan']
        self.assertEqual((plan['mode'],plan['piece_id'],plan['dropset_index']),('fever',1,1))
        self.assertEqual(plan['field'],first['next_field'])
        self.assertEqual((plan['queue'],plan['source_queue']),(original['self']['queue'][1:],original['self']['queue']))
        current=copy.deepcopy(original)
        # Fever mode: estimated input 14 + measured nonclearing lock-to-ready 26.
        current['self'].update(field=first['next_field'],queue=original['self']['queue'][1:]+['2:BY'],
            piece_id=1,dropset_index=1,moves_since_chain=1,remaining_frames=remaining-40)
        return current,plan

    def seed_searches(self, current):
        with patch.object(self.engine.native,'ask',wraps=self.engine.native.ask) as ask:
            reply=self.engine.answer(current)
        return reply,sum(call.args[0]['op']=='seed_search' for call in ask.call_args_list)

    def test_fever_prefetch_reuses_the_seed_search_made_while_the_piece_fell(self):
        current,plan=self.prepared_seed_request()
        reply,searches=self.seed_searches(current)
        self.assertEqual(searches,0)
        self.assertTrue(reply['seed_search_reused'])
        self.assertEqual(reply['searched_visible'],2)
        self.assertEqual((reply['x'],reply['r']),(plan['placement']['x'],plan['placement']['r']))
        self.assertEqual(reply['decision_identity']['piece_id'],1)
        self.assertTrue(authorize_mode_reply(current,reply,current))
        # One use: the same request asked again is searched.
        reply,searches=self.seed_searches(current)
        self.assertEqual((searches,reply['seed_search_reused']),(1,False))

    def test_fever_prefetch_misses_on_another_board_piece_seed_or_delivery(self):
        for change in ('board','queue','seed_id','delivery'):
            current,_=self.prepared_seed_request()
            if change=='board':current['self']['field'][-1]=('B' if current['self']['field'][-1][0]=='G' else 'G')+current['self']['field'][-1][1:]
            elif change=='queue':current['self']['queue'][0]='2:BB'
            elif change=='seed_id':current['self']['seed_id']+=1
            else:current['self'].update(confirmed=4,fever_confirmed=4)
            reply,searches=self.seed_searches(current)
            self.assertEqual((searches,reply['seed_search_reused']),(1,False),change)

    def test_fever_prefetch_rechecks_flying_and_held_nuisance_for_strategy_selection(self):
        current,plan=self.prepared_seed_request()
        self.assertEqual(plan['nuisance'],dict(confirmed=0))
        current['self'].update(unconfirmed=54,fever_unconfirmed=54,remainder=31)
        reply,searches=self.seed_searches(current)
        self.assertEqual((searches,reply['seed_search_reused']),(1,False))
        self.assertTrue(authorize_mode_reply(current,reply,current))
        current,_=self.prepared_seed_request()
        current['self']['normal_unconfirmed']=12
        reply,searches=self.seed_searches(current)
        self.assertEqual((searches,reply['seed_search_reused']),(1,False))

    def test_one_preparation_serves_both_modes_from_an_observed_board(self):
        # After a chain, a delivery or a new seed there is no placement to predict from: the board
        # standing between two pieces is read, with the two pieces visible by then.
        for mode in ('normal','fever'):
            own=side(mode,seed3(),['2:RY','L:RRY'])
            own.update(dropset_index=1,piece_id=1)
            if mode=='normal':own['field'][-1]='#'+own['field'][-1][1:]       # a delivery has landed
            ahead=request(own); ahead['op']='prepare_observed'
            prepared=self.engine.answer(ahead)
            self.assertTrue(prepared['prepared'],prepared)
            plan=prepared['plan']
            self.assertEqual((plan['mode'],plan['field'],plan['queue']),(mode,own['field'],own['queue']))
            self.assertNotIn('source_queue',plan)
            current=request(copy.deepcopy(own)); current['self']['queue'].append('2:GB')
            if mode=='fever':current['self']['remaining_frames']-=14
            with patch.object(self.engine.solo,'ask',wraps=self.engine.solo.ask) as build:
                reply,searches=self.seed_searches(current)
            build.assert_not_called()
            self.assertEqual(searches,0)
            self.assertTrue(reply['search_reused'])
            self.assertEqual((reply['x'],reply['r']),(plan['placement']['x'],plan['placement']['r']))
            self.assertTrue(authorize_mode_reply(current,reply,current))

    def test_normal_preparation_inherits_nuisance_in_flight_but_not_a_changed_count(self):
        original=request(side('normal',queue=['2:RY','2:BB','L:RRY']))
        original['self'].update(unconfirmed=6,normal_unconfirmed=6)
        first=self.engine.answer(original)
        self.assertEqual(first['action'],'place')
        if first['fire']:self.skipTest('the first move clears; nothing to predict')
        preparation=copy.deepcopy(original)
        preparation.update(op='prepare',placement=dict(x=first['x'],r=first['r']))
        prepared=self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'],prepared)
        self.assertEqual(prepared['plan']['nuisance'],dict(confirmed=0,unconfirmed=6))
        kept=self.engine.prepared
        for unconfirmed,reused in ((6,True),(9,False)):
            self.engine.prepared=kept
            current=copy.deepcopy(original)
            current['self'].update(field=first['next_field'],queue=original['self']['queue'][1:]+['2:GY'],
                piece_id=1,dropset_index=1,moves_since_chain=1,unconfirmed=unconfirmed,normal_unconfirmed=unconfirmed)
            reply=self.engine.answer(current)
            self.assertEqual(bool(reply.get('search_reused')),reused,unconfirmed)
        # A confirmed delivery falls with a placement that clears nothing: no board to predict.
        original['self'].update(confirmed=2,normal_confirmed=2,garbage_phase=None,garbage_phase_status='unknown')
        preparation=copy.deepcopy(original)
        preparation.update(op='prepare',placement=dict(x=first['x'],r=first['r']))
        self.assertFalse(self.engine.answer(preparation)['prepared'])

    def test_fever_prefetch_checks_the_clock_only_when_time_is_short(self):
        # Plenty of time: a split or a long fall beyond the estimate changes nothing the search weighed.
        current,_=self.prepared_seed_request()
        current['self']['remaining_frames']-=60
        self.assertEqual(self.seed_searches(current)[1],0)
        # Short of time (the seed is being fired): 30 frames of slack, then it is searched again.
        for late,searches in ((30,0),(31,1)):
            current,_=self.prepared_seed_request(remaining=230)
            current['self']['remaining_frames']-=late
            self.assertEqual(self.seed_searches(current)[1],searches,late)

    def test_fever_prefetch_refuses_clear_or_unknown_partial_delivery(self):
        fire=request(side('fever',seed3(),['2:GG','2:RY','L:RRY']))
        moves=self.engine.native.ask(dict(op='placements',field=fire['self']['field'],piece='2:GG'))['placements']
        quiet=next(p for p in moves if not p['links'] and not p['dead'])
        for change in ('clear','nuisance'):
            req=copy.deepcopy(fire); placement=dict(x=quiet['x'],r=quiet['r'])
            if change=='clear':
                req['self']['field'][-1]='GG'+req['self']['field'][-1][2:]
                moves=self.engine.native.ask(dict(op='placements',field=req['self']['field'],piece='2:GG'))['placements']
                fired=next(p for p in moves if p['links'])
                placement=dict(x=fired['x'],r=fired['r'])
            else:req['self'].update(confirmed=2,fever_confirmed=2,garbage_phase=None,garbage_phase_status='unknown')
            req.update(op='prepare',placement=placement)
            self.assertFalse(self.engine.answer(req)['prepared'],change)
            self.assertIsNone(self.engine.prepared)

    def test_opponent_changes_never_take_back_a_decided_move(self):
        for own in (side('fever',seed3()),side('normal',queue=['2:RY','2:BB','L:RRY'])):
            req=request(own); reply=self.engine.answer(req)
            reply.pop('decision_dependencies',None)       # whatever the policy says it looked at
            latest=copy.deepcopy(req)
            latest['enemy']=side('fever',seed3(),['2:BG'])
            latest['enemy'].update(piece_id=7,remainder=55,phase='waiting_seed',remaining_frames=411,
                                   unconfirmed=30,fever_unconfirmed=30)
            self.assertTrue(authorize_mode_reply(req,reply,latest))
            latest['self']['field']=list(latest['self']['field']); latest['self']['field'][-1]='G.....'
            with self.assertRaisesRegex(ValueError,'self state changed'):
                authorize_mode_reply(req,reply,latest)

    def test_unknown_history_continues_without_inventing_a_cursor(self):
        own = side('normal')
        own.update(garbage_phase=None, garbage_phase_status='unknown',
                   moves_since_chain=None, moves_since_chain_status='unknown')
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['action'], 'place')
        self.assertIsNone(own['garbage_phase'])
        own.update(confirmed=3, normal_confirmed=3)
        reply = self.engine.answer(request(own))
        forecast = reply['tactics_forecast']
        self.assertEqual(forecast['choice']['possible_drop_boards'], 20)
        self.assertFalse(forecast['choice']['post_drop_field_known'])
        self.assertIsNone(reply['next_field'])
        self.assertEqual(forecast['unknown_drop_policy'], 'worst_column_choice_then_reobserve')

    def test_fever_unknown_preparation_and_cursor_use_observed_seed(self):
        own = side('fever', seed3(), ['2:RY', '2:BB', 'L:RRY'])
        own.update(garbage_phase=None, garbage_phase_status='unknown',
                   prepared_frames=None, prepared_frames_status='unknown',
                   moves_since_chain=None, moves_since_chain_status='unknown')
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['action'], 'place')
        self.assertEqual(reply['seed_forecast']['garbage_phase_status'], 'unknown_no_confirmed_drop_forecast')
        own.update(confirmed=3, fever_confirmed=3)
        reply = self.engine.answer(request(own))
        self.assertEqual(len(reply['seed_forecast']['path']), 1)
        self.assertEqual(reply['seed_forecast']['strategy'], 'value')
        self.assertEqual(reply['seed_forecast']['garbage_phase_status'], 'unknown_all_remainder_column_subsets')
        rows=list(EMPTY); rows[-1]='RRR...'
        own.update(field=rows,queue=['2:RR'],normal_confirmed=500)
        reply=self.engine.answer(request(own)); first=reply['seed_forecast']['choice']
        actual=self.engine.native.ask(dict(op='transition',field=rows,piece='2:RR',x=first['x'],r=first['r']))
        self.assertEqual(first['locked_field'],actual['locked_field'])
        self.assertEqual(first['field'],actual['field'])
        self.assertGreater(first['end_at'],first['fire_at'])
        self.assertEqual(first['sent'],0)  # active and held nuisance both absorb the chain
        self.assertFalse(reply['seed_forecast']['solved'])  # one clear still fails a three-chain seed

    def test_unknown_without_provenance_is_rejected(self):
        own = side()
        own['garbage_phase'] = None
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.engine.answer(request(own))

    def test_unknown_columns_do_not_bypass_solver_option_validation(self):
        own=side('fever',seed3())
        own.update(garbage_phase=None,garbage_phase_status='unknown',confirmed=3,fever_confirmed=3)
        for options in (dict(strategy='invalid'),dict(width=0),dict(hidden_queue=True)):
            req=request(own); req['seed_options']=options
            with self.assertRaises(ValueError):self.engine.answer(req)

    def test_remainder_uncertainty_includes_noncyclic_columns_and_loss(self):
        cases = list(outcomes(EMPTY, 3))
        self.assertEqual(len(cases), 20)
        self.assertIn('###...', [rows[-1] for rows, _ in cases])
        rows = list(EMPTY)
        rows[-11:] = ['..R...']*11
        cases = list(outcomes(rows, 1))
        self.assertEqual(sum(losing for _, losing in cases), 1)

    def test_tables_and_mode_dependent_score(self):
        score = Scoring()
        self.assertEqual(score.link('raffina', 10, [4], 1, 'fever'), 6760)
        self.assertEqual(score.link('paprisu', 17, [4], 1, 'fever'), 16400)
        self.assertEqual(score.link('schezo', 17, [4], 1, 'fever'), 13120)
        self.assertEqual(score.link('schezo', 19, [4], 1, 'fever'), 15120)
        for c in score.data['characters']:
            self.assertEqual(len(score.data['characters'][c]['fever']), 19)
        with self.assertRaises(ValueError):
            score.link('raffina', 20, [4], 1, 'fever')

    def test_steam_internal_clock_keeps_the_full_observed_deadline(self):
        req = request()
        req['clock_policy']['frame_domain'] = 'pc_15209927_internal'
        req['self']['prepared_frames'] = req['self']['remaining_frames'] = 1860
        reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        latest = copy.deepcopy(req)
        latest['frame'] = latest['observation']['frame_before'] = latest['observation']['frame_after'] = 5
        for name in ('self', 'enemy'):
            latest[name]['observed_frame'] = 5
        latest['self']['remaining_frames'] -= 5
        self.assertTrue(authorize_mode_reply(req, reply, latest))
        latest['clock_policy']['frame_domain'] = 'model'
        with self.assertRaisesRegex(ValueError, 'clock_policy changed'):
            authorize_mode_reply(req, reply, latest)

    def test_clock_rejects_unknown_units_and_values_above_the_internal_cap(self):
        req = request()
        req['self']['prepared_frames'] = 1860
        self.assertEqual(self.engine.answer(req)['action'], 'place')
        req['clock_policy']['frame_domain'] = 'seconds'
        with self.assertRaisesRegex(ValueError, 'clock frame domain'):
            self.engine.answer(req)
        req['clock_policy']['frame_domain'] = 'pc_15209927_internal'
        req['self']['remaining_frames'] = 1861
        with self.assertRaises(ValueError):
            self.engine.answer(req)

    def test_three_chain_native_path_matches_scoring(self):
        req = request(side('fever', seed3(), FIRES))
        reply = self.engine.answer(req)
        self.assertTrue(reply['seed_forecast']['solved'])
        self.assertGreaterEqual(reply['chain'], 3)
        step = self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:RY',
                                          x=reply['x'], r=reply['r']))
        self.assertEqual(step['field'], reply['next_field'])
        self.assertEqual(self.engine.scoring.chain('raffina', step['links'], 'fever'), reply['link_points'])
        self.assertTrue(authorize_mode_reply(req, reply, copy.deepcopy(req)))

    def test_seed_decision_survives_enemy_soft_drop_score_and_observation_updates(self):
        req=request(); reply=self.engine.answer(req)
        self.assertEqual(reply['decision_dependencies'],['self'])
        latest=copy.deepcopy(req)
        latest['enemy'].update(remainder=17,board_observed_frame=3,moves_since_chain=1)
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        for key,value in (('field',seed3()),('queue',['2:BG']),('phase','chain')):
            changed=copy.deepcopy(latest); changed['enemy'][key]=value
            self.assertTrue(authorize_mode_reply(req,reply,changed))

    def test_recovery_excludes_cached_unreachable_move_and_scores_real_alternative(self):
        req=request(side(rows='....../....../....../....../.....B/.....B/.....R/.....R/....BG/....BG/...GGB/...RYB/.RRGRG/.BBRRG'.split('/'),queue=['L:RRR','0:G','2:YB']))
        req['self'].update(character='rafisol', dropset_index=10)
        req.update(op='recover_placement',reachable_placements=[dict(x=2,r='U'),dict(x=3,r='U')])
        self.engine.prepared=('stale',0,dict(x=4,r='D'))
        reply=self.engine.answer(req)
        self.assertIn((reply['x'],reply['r']),[(2,'U'),(3,'U')])
        self.assertTrue(reply['recovery'])
        self.assertIsNone(self.engine.prepared)
        step=self.engine.native.ask(dict(op='transition',field=req['self']['field'],piece='L:RRR',x=reply['x'],r=reply['r']))
        self.assertEqual(step['field'],reply['next_field'])
        self.assertTrue(authorize_mode_reply(req,reply,req))
        req['reachable_placements']=[]
        with self.assertRaisesRegex(ValueError,'requires observed'):self.engine.answer(req)

    def test_threatened_seed_ignores_enemy_motion_and_flying_packets_but_rejects_delivery(self):
        req=request(side('fever', seed3(), ['2:GG'])); req['self'].update(unconfirmed=206,fever_unconfirmed=206)
        reply=self.engine.answer(req)
        self.assertFalse(reply['fire'])
        self.assertEqual(reply['decision_dependencies'],['self'])
        latest=copy.deepcopy(req)
        latest['enemy'].update(piece_id=2,queue=['2:BG'],field=seed3(),phase='placing',remainder=3)
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        latest['self'].update(unconfirmed=205,fever_unconfirmed=205)
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        latest['self'].update(confirmed=1,fever_confirmed=1)
        with self.assertRaisesRegex(ValueError,'self state changed'):
            authorize_mode_reply(req,reply,latest)

    def test_two_move_solution_and_stop_at_first_clear(self):
        req = request(side('fever', seed3(), ['2:GG', '2:RY']))
        req['self']['character'] = 'arle'    # Only pairs to come: nothing but the visible fire is near.
        reply = self.engine.answer(req)
        forecast = reply['seed_forecast']
        self.assertTrue(forecast['solved'])
        self.assertEqual(len(forecast['path']), 2)
        self.assertEqual(forecast['path'][0]['chain'], 0)
        self.assertGreaterEqual(forecast['path'][1]['chain'], 3)

    def test_cutoff_returns_legal_fallback_and_no_hidden_colors(self):
        req = request(side('fever', queue=['2:GY']))
        req['seed_options']['max_nodes'] = 1
        reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        self.assertFalse(reply['seed_forecast']['solved'])
        self.assertTrue(reply['seed_forecast']['cutoff'])
        self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:GY',
                                    x=reply['x'], r=reply['r']))
        req['self']['queue'] = ['2:GY'] * 4
        with self.assertRaises(ValueError):
            self.engine.answer(req)

    def test_normal_identifies_mainline_color_deficits_and_separate_counter_colors(self):
        own = side('normal', seed_with_small_green(), ['2:GB'])
        needs = inspect_colors(self.engine.native, own)['needs']
        self.assertEqual(needs['mainline_chain'], 3)
        self.assertTrue(any(p['color'] == 'Y' and p['needed_cells'] == 1 and
                            p['missing_visible_cells'] == 1 for p in needs['mainline']))
        self.assertTrue(any(p['color'] == 'G' and p['chain'] == 1 and
                            p['visible_supply'] == 1 for p in needs['offsets']))
        self.assertGreater(needs['reserve_weights']['Y'], needs['reserve_weights']['G'])

    def test_mainline_builder_move_stands_when_nothing_is_incoming(self):
        own = side('normal', seed3(), ['2:GB', '2:RR', '2:BB']); own['character'] = 'arle'
        req = request(own); req['match_id'] = 'protect-next-red'
        self.engine.prepared = None
        # The one-piece colour heuristic would move this elsewhere to keep the
        # red trigger. Measured builds were shorter with that override (9.0
        # against 12.7 links), so the needs are reported and the move kept.
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=4, r='R')):
            reply = self.engine.answer(req)
        self.assertEqual(reply['reason'], 'normal_build_or_fire')
        self.assertEqual((reply['x'], reply['r']), (4, 'R'))
        self.assertEqual(reply['normal_color_needs']['mainline_chain'], 3)
        self.assertFalse(reply['fire'])
        self.assertTrue(authorize_mode_reply(req, reply, req))

    def test_prepared_normal_choice_is_the_builder_move_and_is_reused(self):
        own = side('normal', seed3(), ['2:GB', '2:RR', '2:BB']); own['character'] = 'arle'
        req = request(own); req['match_id'] = 'prepared-protect-next-red'
        preparation = copy.deepcopy(req); preparation['op'] = 'prepare_observed'
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=4, r='R')):
            prepared = self.engine.answer(preparation)
        self.assertTrue(prepared['prepared'])
        self.assertEqual(prepared['plan']['reason'], 'normal_build_or_fire')
        self.assertEqual(prepared['plan']['placement'], dict(x=4, r='R'))
        with patch.object(self.engine.solo, 'ask', side_effect=AssertionError('unexpected new search')):
            reply = self.engine.answer(req)
        self.assertTrue(reply['normal_search_reused'])
        self.assertEqual(reply['reason'], 'normal_build_or_fire')
        self.assertEqual(reply['searched_visible'], 3)
        self.assertTrue(authorize_mode_reply(req, reply, req))

    def test_gauge_free_battle_stops_a_due_drop_with_the_clear_it_has(self):
        own = side('normal', seed_with_small_green(), ['2:GB'])
        own.update(confirmed=18, normal_confirmed=18, garbage_phase=None, garbage_phase_status='unknown')
        req = request(own); req['gauge_gain_on_offset'] = 0
        reply = self.engine.answer(req)
        self.assertEqual(reply['chain'], 1)
        self.assertEqual(reply['nuisance_uncertainty']['dropped'], 0)
        self.assertEqual(reply['needed_color_consumed'], 0)
        self.assertEqual(reply['normal_color_needs']['mainline_chain'], 3)

    def test_fever_wait_preserves_mainline_colors_with_the_same_small_counter(self):
        own = side('normal', seed_with_small_green(), ['2:GB'])
        own.update(gauge=6, unconfirmed=200, normal_unconfirmed=200)
        reply = self.engine.answer(request(own, side('fever', seed3())))
        self.assertEqual(reply['chain'], 1)
        self.assertTrue(reply['entry_pending_after_chain'])
        self.assertEqual(reply['needed_color_consumed'], 0)
        self.assertGreater(reply['normal_color_needs']['reserve_weights']['Y'], 0)

    def test_matching_color_keeps_mainline_fire_instead_of_small_hold(self):
        own = side('normal', seed_with_small_green(), ['2:GY'])
        own.update(confirmed=18, normal_confirmed=18, garbage_phase=None, garbage_phase_status='unknown')
        req = request(own); req['gauge_gain_on_offset'] = 0
        reply = self.engine.answer(req)
        self.assertGreaterEqual(reply['chain'], 3)

    def test_confirmed_drop_on_a_seed_is_answered_without_losing(self):
        own = side('fever', seed_with_small_green(), ['2:GB'])
        own.update(confirmed=18, fever_confirmed=18, garbage_phase=None, garbage_phase_status='unknown')
        reply = self.engine.answer(request(own))
        first = reply['seed_forecast']['choice']
        self.assertFalse(first['dead'])
        self.assertIn('expected_points', first)
        # A clear stops the drop; a placement that pops nothing takes all of it.
        self.assertEqual(first['dropped'], 0 if reply['chain'] else 18)

    def test_offline_seed_geometry_keeps_missing_history_explicit(self):
        own = side('fever', seed3(), FIRES)
        for key in ('mode_generation','seed_id','piece_id'):
            del own[key]
        result = self.engine.seed_solver.solve(own, 120, True, {})
        self.assertTrue(result['solved'])

    def test_unconfirmed_pressure_does_not_stop_a_seed_fired_at_its_level(self):
        own = side('fever', seed3(), FIRES)
        own.update(unconfirmed=206, fever_unconfirmed=206)
        reply = self.engine.answer(request(own))
        self.assertGreaterEqual(reply['chain'], own['seed_chain'])
        self.assertEqual(reply['seed_forecast']['choice']['dropped'], 0)

    def live_seed5(self, queue, remaining):
        # A 5-chain seed of the 2026-10-07 session log, where a 4-chain was fired.
        rows = list(EMPTY)
        rows[-7:] = ['.....B', '.....B', '.....G', '..YRBG', '..YYBB', '.GGRRG', '.GYRBG']
        own = side('fever', rows, queue)
        own.update(seed_base=5, seed_chain=5, remaining_frames=remaining)
        return self.engine.seed_solver.solve(own, 120, True, dict(budget_ms=500))

    def test_a_seed_that_can_be_fired_at_its_level_is_not_fired_below_it(self):
        result = self.live_seed5(['2:RG', 'L:BBY', '2:RB'], 1353)
        kinds = result['alternatives']
        self.assertEqual(kinds['regular_fire']['chain'], 5)
        self.assertEqual(kinds['short_fire']['chain'], 4)
        self.assertGreater(kinds['regular_fire']['expected_points'], kinds['short_fire']['expected_points'])
        self.assertNotIn(result['path'][-1]['chain'], range(1, 5))

    def test_a_seed_whose_colour_is_not_in_sight_is_kept_while_the_clock_is_long(self):
        result = self.live_seed5(['L:YYY', '2:RB', '2:RY'], 873)
        self.assertNotIn('regular_fire', result['alternatives'])
        self.assertEqual([step['chain'] for step in result['path']], [0, 0, 0])
        last = result['path'][-1]
        self.assertGreaterEqual(last['extension_potential']['chain'], 5)
        self.assertGreater(last['extension_potential']['odds'], 0.9)
        # On the last piece of the clock there is nothing to wait for: what can be fired is.
        self.assertGreater(self.live_seed5(['L:YYY', '2:RB', '2:RY'], 40)['choice']['chain'], 0)

    def test_a_placement_followed_by_a_visible_piece_is_ranked_by_what_follows(self):
        result = self.live_seed5(['L:YYY', '2:RB', '2:RY'], 873)
        self.assertFalse(result['cutoff'])
        self.assertEqual(result['alternatives']['no_pop']['placements'], 3)

    def test_an_enemy_chain_still_scoring_does_not_make_a_short_fire_look_better(self):
        # 2026-10-07 session log: a 9-chain seed was popped for one link while the opponent's
        # chain was landing. The whole of that chain arrives whichever line is played.
        rows = list(EMPTY)
        rows[-11:] = ['R.....', 'G.....', 'Y.....', 'G.....', 'RG....', 'GR....',
                      'GRRYBY', 'GBYRYY', 'RGBYRB', 'RGBYRB', 'RGBYRB']
        own = side('fever', rows, ['0:Y', '2:BB', '2:RG'])
        own.update(seed_base=9, seed_chain=9, remaining_frames=137, unconfirmed=26, fever_unconfirmed=26)
        events = [dict(type='link', frame=30, points=6000), dict(type='link', frame=100, points=9000),
                  dict(type='link', frame=170, points=12000), dict(type='link', frame=240, points=12000),
                  dict(type='end', frame=300)]
        result = self.engine.seed_solver.solve(own, 120, True, dict(budget_ms=500), enemy_events=events)
        self.assertEqual(result['choice']['chain'], 9)
        fired, short = result['choice'], result['alternatives']['short_fire']
        self.assertEqual(short['chain'], 1)
        self.assertGreater(fired['expected_points'], short['expected_points'])
        # 26 on the tray and 325 still to come, less what each line offsets.
        self.assertEqual(fired['carried_nuisance'], 26 + 325 - fired['cancelled'])

    def test_a_large_seed_is_built_on_by_a_link_when_the_risk_is_small(self):
        rows = list(EMPTY)
        rows[-11:] = ['...YRG', 'RBRGYB', 'GBBYRR', 'BGRRYY', 'BGRYRR', 'YYGRYY', 'GGRBBY',
                      'YYGRRB', 'BBRYGG', 'BGGRYY', 'GRRYGG']
        own = side('fever', rows, ['J:RBR', '2:YB', '2:RY'])
        own.update(seed_base=14, seed_chain=14, remaining_frames=214)
        solver = self.engine.seed_solver
        result = solver.solve(own, 120, True, dict(budget_ms=500))
        # A 15 is reached with two more pieces: the links past the 14th earn credit and the risk is small.
        self.assertEqual([step['chain'] for step in result['path']], [0, 0, 15])
        # With the earlier risk (6) and no credit for them, the seed is fired at its level.
        model = solver.value_model
        try:
            solver.value_model = dict(model, crowded_cells=6, overflow_credit=0)
            fired = solver.solve(own, 120, True, dict(budget_ms=500))
        finally:
            solver.value_model = model
        self.assertEqual([step['chain'] for step in fired['path']], [14])

    def test_uncertain_seed_drop_checks_all_subsets_before_reobservation(self):
        own = side('fever', seed3(), ['2:GG'])
        own.update(confirmed=3, fever_confirmed=3, garbage_phase=None, garbage_phase_status='unknown')
        reply = self.engine.answer(request(own)); result = reply['seed_forecast']; first = result['choice']
        self.assertEqual(first['chain'], 0)
        self.assertEqual(first['possible_drop_boards'], 20)
        self.assertEqual(len(result['path']), 1)
        self.assertFalse(first['post_drop_field_known'])
        self.assertIsNone(reply['next_field'])
        self.assertEqual(result['searched_visible'], 1)
        self.assertEqual(first['target_ignition_preserved'], first['all_drop_cases_preserve_target'])

    def test_all_clear_can_outweigh_an_under_target_chain(self):
        own = side('fever', list(EMPTY), ['2:RR'])
        own['field'][-1] = 'RRR...'
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['chain'], 1)
        self.assertTrue(reply['next_all_clear'])
        self.assertEqual(reply['next_field'], list(EMPTY))
        self.assertTrue(reply['replaces_seed_on_clear'])
        self.assertFalse(reply['seed_forecast']['solved'])

    def test_deadline_scores_whole_chain_and_separates_next_seed_opportunity(self):
        req = request(side('fever', seed3(), FIRES)); req['self']['remaining_frames'] = 50
        reply = self.engine.answer(req); last = reply['seed_forecast']['path'][-1]
        self.assertEqual(reply['chain'], 3)
        self.assertGreater(last['end_at'], 50)
        self.assertFalse(last['completed_before_timeout'])
        self.assertFalse(last['next_seed_input_fits'])
        self.assertEqual(last['total_points'], sum(last['link_points']))
        self.assertGreater(last['total_points'], last['points_before_timeout'])
        req['self']['remaining_frames'] = 900
        last = self.engine.answer(req)['seed_forecast']['path'][-1]
        self.assertTrue(last['completed_before_timeout'])
        self.assertTrue(last['next_seed_input_fits'])

    def test_mode_or_seed_change_rejects_old_input(self):
        req = request()
        reply = self.engine.answer(req)
        for key in ('seed_id', 'mode_generation'):
            latest = copy.deepcopy(req)
            latest['self'][key] += 1
            with self.assertRaises(ValueError):
                authorize_mode_reply(req, reply, latest)
        latest = copy.deepcopy(req)
        latest['frame'] = 5
        latest['observation'].update(frame_before=5, frame_after=5)
        for name in ('self', 'enemy'):
            latest[name]['observed_frame'] = 5
        latest['self']['remaining_frames'] -= 5
        self.assertTrue(authorize_mode_reply(req, reply, latest))

    def test_short_and_expired_timer_finish_the_observed_active_piece(self):
        req = request()
        req['self']['remaining_frames'] = 1
        self.assertEqual(self.engine.answer(req)['action'], 'place')
        req['self']['remaining_frames'] = 0
        self.assertEqual(self.engine.answer(req)['action'], 'place')

    def test_normal_return_uses_normal_scoring_with_fever_enemy(self):
        req = request(side(), side('fever', seed3()))
        req['self']['field'][-1] = 'RRR.BB'
        req['self']['queue'] = ['2:RG']
        reply = self.engine.answer(req)
        self.assertEqual(reply['mode'], 'normal')
        result = self.engine.native.ask(dict(op='transition', field=req['self']['field'], piece='2:RG',
                                            x=reply['x'], r=reply['r']))
        self.assertEqual(reply['link_points'], self.engine.scoring.chain('raffina', result['links']))

    def test_active_and_held_queues_and_observation_fields_required(self):
        req = request(side('fever', seed3(), FIRES))
        req['self']['normal_confirmed'] = 100
        reply = self.engine.answer(req)
        self.assertTrue(reply['seed_forecast']['solved'])
        for step in reply['seed_forecast']['path']:
            self.assertEqual(step['dropped'], 0)
        for key in ('stored_field', 'seed_id', 'mode_generation', 'clock_running'):
            invalid = copy.deepcopy(req)
            del invalid['self'][key]
            with self.assertRaises((ValueError, KeyError)):
                self.engine.answer(invalid)

    def test_all_characters_and_cycle_positions_in_fever_mode(self):
        for character in self.engine.patterns:
            queue = self.engine.native.ask(dict(op='queue', character=character, seed=1, count=16))['queue']
            for index, piece in enumerate(queue):
                own = side('fever', seed3(), [piece])
                own.update(character=character, piece_id=index, dropset_index=index)
                req = request(own)
                reply = self.engine.answer(req)
                self.assertEqual(reply['action'], 'place', (character, index))
                actual = self.engine.native.ask(dict(op='transition', field=own['field'], piece=piece,
                                                     x=reply['x'], r=reply['r']))
                self.assertEqual(actual['field'], reply['next_field'])
                self.assertTrue(authorize_mode_reply(req, reply, copy.deepcopy(req)))

    def test_normal_offset_forecasts_fever_entry(self):
        own = side()
        own['gauge'] = 6
        own['field'][-1] = 'RRR.BB'
        own['confirmed'] = own['normal_confirmed'] = 6
        safe_reply=self.engine.answer(request(own,side('fever',seed3())))
        self.assertTrue(safe_reply['tactics_forecast']['can_receive_attack'])
        self.assertFalse(safe_reply['entry_pending_after_chain'])
        # Large packets require a response even if a single drop would fit.
        own['confirmed'] = own['normal_confirmed'] = 72
        reply = self.engine.answer(request(own, side('fever', seed3())))
        self.assertFalse(reply['tactics_forecast']['can_receive_attack'])
        self.assertTrue(reply['entry_pending_after_chain'])
        self.assertEqual(reply['gauge_forecast']['gauge_after'], 7)

    @staticmethod
    def popped(candidate):
        return sum(sum(link['groups']) for link in candidate['links'])

    def test_entry_spends_four_puyos_when_four_are_enough(self):
        own=side('normal',list(EMPTY[:-1])+['RRRBBB'],['2:RB','2:RY','2:GY'])
        own.update(character='arle',gauge=6,unconfirmed=100,normal_unconfirmed=100)
        reply=self.engine.answer(request(own, side('fever', seed3())))
        self.assertEqual(reply['reason'],'tactics_offset')
        self.assertTrue(reply['entry_pending_after_chain'])
        candidates=reply['tactics_forecast']['candidates']
        self.assertTrue(any(self.popped(c)==4 and c['gauge_after']==7 for c in candidates))
        # Four would enter Fever; the eight that also clear the board whole are taken (2026-10-08).
        choice=reply['tactics_forecast']['choice']
        self.assertEqual(self.popped(choice),8)
        self.assertTrue(choice['all_clear'])

    def test_search_reads_the_explicit_fourth_piece(self):
        own=side('normal',list(EMPTY[:-2])+['RRRBBB','GGGYYY'],['2:RB','2:GG','2:RR'])
        own.update(character='arle',gauge=4,unconfirmed=200,normal_unconfirmed=200)
        with patch.dict(self.engine.policy['normal_tactics'],max_nodes=1000000,budget_ms=1000):
            reply=self.engine.answer(request(own))
        self.assertEqual(reply['tactics_forecast']['visible'],3)
        self.assertEqual(reply['searched_visible'],3)
        own['queue'].append('2:RY')
        reply=self.engine.answer(request(own))
        self.assertEqual(reply['tactics_forecast']['visible'],4)

    def test_due_packet_enters_at_once_and_nothing_is_searched_past_entry(self):
        own=side('normal',list(EMPTY[:-1])+['RRRBBB'],['2:RB','2:RY','2:GY'])
        own.update(character='arle',gauge=6,confirmed=1000,normal_confirmed=1000)
        reply=self.engine.answer(request(own))
        choice=reply['tactics_forecast']['choice']
        self.assertTrue(reply['entry_pending_after_chain'])
        self.assertTrue(choice['survives'])
        self.assertEqual((choice['gauge_after'],choice['projected_gauge']),(7,7))
        # With nothing pending the same piece clears the board whole, and that is taken (2026-10-08):
        # under the Fever rule a four-chain seed drops for it.
        own.update(confirmed=0,normal_confirmed=0)
        quiet=self.engine.answer(request(own))
        self.assertEqual(quiet['reason'],'tactics_all_clear')
        self.assertTrue(quiet['next_all_clear'])

    def test_nothing_is_forecast_on_an_unknown_all_clear_seed(self):
        own=side('normal',list(EMPTY[:-1])+['RRRBBB'],['2:RB','2:RR','2:BB'])
        own.update(character='arle',gauge=3,unconfirmed=200,normal_unconfirmed=200)
        reply=self.engine.answer(request(own))
        # Clearing all eight puyos ends at the all-clear seed, which must be
        # observed before another placement is weighed.
        direct=next(c for c in reply['tactics_forecast']['candidates'] if c['all_clear'])
        self.assertEqual(direct['projected_gauge'],direct['gauge_after'])

    def test_wait_recovery_respects_reachable_whitelist(self):
        own=side('normal',list(EMPTY[:-1])+['RRRBBB'],['2:RB','2:RY','2:GY'])
        own.update(character='arle',gauge=6,unconfirmed=100,normal_unconfirmed=100)
        req=request(own);req.update(op='recover_placement',reachable_placements=[dict(x=5,r='U')])
        reply=self.engine.answer(req)
        self.assertEqual((reply['x'],reply['r']),(5,'U'))
        self.assertTrue(reply['recovery'])
        self.assertEqual(reply['chain'],0)
        self.assertEqual(reply['tactics_forecast']['choice']['projected_gauge'],6)
        self.assertFalse(reply.get('entry_pending_after_chain', False))

    def test_reference_metadata_and_decoder_do_not_guess_missing_entries(self):
        data = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['seeds']), 50)
        self.assertEqual([(p['kind'],p['seed_chain']) for p in data['missing']], [('kaidan',4),('zabuton',6)])
        self.assertFalse(data['color_mapping_verified_on_steam'])
        for seed in data['seeds']:
            self.assertEqual(decode(seed['encoding']), seed['field'])
            self.assertEqual(self.engine.native.ask(dict(op='resolve',field=seed['field']))['links'], [])
        for bad in ('a78x', 'a0b78', 'a999999999999', 'a77'):
            with self.assertRaises(ValueError):
                decode(bad)

    def test_countdown_can_finish_active_chain_but_never_accept_stale_deadline(self):
        req = request()
        req['self']['remaining_frames'] = 50
        reply = self.engine.answer(req)
        self.assertEqual(reply['action'], 'place')
        self.assertTrue(reply['seed_forecast']['solved'])
        latest = copy.deepcopy(req)
        elapsed = 15
        latest['frame'] = elapsed
        latest['observation'].update(frame_before=elapsed, frame_after=elapsed)
        for who in ('self', 'enemy'):
            latest[who]['observed_frame'] = elapsed
        latest['self']['remaining_frames'] -= elapsed
        self.assertTrue(authorize_mode_reply(req, reply, latest))

    def test_json_lines_refuses_non_object_and_keeps_session_alive(self):
        with JsonProcess([sys.executable, '-m', 'fever_battle.mode_engine', '--native', NATIVE,
                          '--solo', SOLO, '--config', ROOT/'config.json'], cwd=ROOT) as engine:
            with self.assertRaises(ValueError):
                engine.ask(['not', 'an', 'observation'])
            self.assertEqual(engine.ask(request())['action'], 'place')


if __name__ == '__main__':
    unittest.main()
