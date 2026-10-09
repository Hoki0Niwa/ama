"""Fever-rule tactics: stock up until a drop is due, and end Fever without an idle fire."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'test'))
from fever_fixtures import NATIVE, SOLO, bystander, request, side, seed3, seed_with_small_green
from fever_battle.mode_engine import ModeBattleEngine


class TacticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def setUp(self):
        self.engine.enemy_analysis = None

    def test_opening_target_is_released_only_by_observed_mainline_or_fever_entry(self):
        own=side('normal',seed3(),['2:RY'])
        for history, released in (({},False),({'normal_chain_max':3},False),
                                  ({'normal_chain_max':4},False),({'normal_chain_max':5},False),({'normal_chain_max':14},True),({'mode_generation':2},True)):
            current={**own,**history}
            req=request(current);req['solo_options']=dict(trigger=15,panic_chain=13,patience=46)
            opts=self.engine._normal_options(req,current)
            if released:
                self.assertEqual((opts['trigger'],opts['panic_chain'],opts['patience']),(19,19,0))
            else:self.assertEqual((opts['trigger'],opts['panic_chain'],opts['patience']),(15,15,0))

    def test_unfilled_second_keeps_building_instead_of_firing_a_small_mainline(self):
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows=next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7')
        own=side('normal',rows,['2:RY']);own.update(character='arle',normal_chain_max=14)
        req=request(own);req['solo_options']=dict(trigger=15,beam_width=20,beam_depth=4)
        reply=self.engine.answer(req)
        self.assertFalse(reply['fire'])
        self.assertEqual(reply['normal_fire_policy'],'fill_then_fire')

    def test_unfilled_second_is_not_spent_on_an_untimed_fever_attack(self):
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows=next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7')
        own=side('normal',rows,['2:RY']);own.update(character='arle',mode_generation=2)
        req=request(own,self.in_fever());req['solo_options']=dict(trigger=15,beam_width=20,beam_depth=4)
        reply=self.engine.answer(req)
        self.assertFalse(reply['fire'])

    def test_full_second_fires_even_a_single_instead_of_waiting_for_fifteen(self):
        heights=[12,12,10,10,12,12]
        rows=[['.']*6 for _ in range(14)]
        for x,height in enumerate(heights):
            for y in range(14-height,14):rows[y][x]='RG'[(x+y)%2]
        for y in range(4,7):rows[y][2]='Y'
        own=side('normal',[''.join(row) for row in rows],['2:YY'])
        own.update(character='arle',normal_chain_max=14)
        req=request(own);req['solo_options']=dict(trigger=15,beam_width=20,beam_depth=4)
        options=self.engine._normal_options(req,own)
        self.assertEqual(options['trigger'],1)
        reply=self.engine.answer(req)
        self.assertTrue(reply['fire'])
        self.assertLess(reply['chain'],4)

    def test_entry_target_uses_the_end_of_the_observed_normal_chain(self):
        enemy=side();enemy['gauge']=7
        self.assertEqual(self.engine._calculate_enemy_fever(enemy,[dict(type='end',frame=180)])['their_end'],196)

    def test_disruption_alone_does_not_spend_the_whole_second_mainline(self):
        refs=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows=next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7')
        own=side('normal',rows,['2:RY']);own.update(character='arle',normal_chain_max=14)
        req=request(own,self.in_fever())
        for frame in range(100,701,50):
            with patch.object(self.engine, '_enemy_events', return_value=[dict(type='end',frame=frame)]):
                reply=self.engine.answer(req)
            self.assertFalse(reply['fire'], (frame,reply['reason']))

    def waiting(self, **nuisance):
        own = side('normal', seed_with_small_green(), ['2:GY'])
        own.update(nuisance)
        return own

    def test_unconfirmed_attack_is_not_answered_with_the_main_chain(self):
        for phase in (0, None):
            own = self.waiting(unconfirmed=200, normal_unconfirmed=200, garbage_phase=phase)
            if phase is None:
                own['garbage_phase_status'] = 'unknown'
            reply = self.engine.answer(request(own))
            self.assertEqual(reply['reason'], 'tactics_stack')
            self.assertEqual(reply['chain'], 0)
            self.assertFalse(reply['tactics_forecast']['choice']['drop_due'])
            self.assertEqual(reply['decision_dependencies'], ['self'])

    def test_enemy_fever_chain_in_progress_is_stocked_against_until_it_ends(self):
        enemy = side('fever', ['......']*13 + ['RRR...'])
        req = request(self.waiting(), enemy)
        req['enemy_chain'] = dict(trigger_field=['......']*13 + ['RRRR..'], elapsed=0, scored_links=0,
            mode_generation=enemy['mode_generation'], seed_id=enemy['seed_id'])
        events = self.engine._enemy_events(req, enemy)
        self.assertTrue(events)
        reply = self.engine.answer(req)
        self.assertLess(reply['chain'], 3)
        self.assertIn(reply['reason'], ('tactics_stack', 'tactics_offset'))

    def test_packet_of_a_chain_seen_to_end_is_due_before_it_shows_confirmed(self):
        # The opponent's chain has ended and the tray still shows its packet unconfirmed for a few frames.
        own = self.waiting(unconfirmed=40, normal_unconfirmed=40)
        enemy = side()
        req = request(own, enemy)
        self.assertFalse(self.engine.answer(req)['tactics_forecast']['choice']['drop_due'])
        req['enemy_chain'] = dict(trigger_field=['......']*13 + ['RRRR..'], elapsed=300, scored_links=1,
            mode_generation=enemy['mode_generation'], seed_id=enemy['seed_id'], ended=True)
        reply = self.engine.answer(req)
        self.assertTrue(reply['tactics_forecast']['choice']['drop_due'])
        self.assertEqual(reply['reason'], 'tactics_offset')

    def test_pace_is_the_upper_quartile_of_this_modes_own_pieces(self):
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        try:
            paces = []
            for piece, frame in enumerate((0, 50, 104, 160, 230)):
                own, enemy = side(), side()
                own.update(piece_id=piece, observed_frame=frame)
                enemy.update(observed_frame=frame, gauge=6)
                req = request(own, enemy)
                req.update(frame=frame, observation=dict(frame_before=frame, frame_after=frame, match_status='running'))
                paces.append(engine.answer(req)['arrival']['measured_pace'])
            # 50, 54, 56, 70 frames a piece: none until three are measured, then the upper quartile.
            self.assertEqual(paces, [None, None, None, 54, 56])
        finally:
            engine.close()

    def test_acceptable_due_drop_keeps_the_main_chain(self):
        reply = self.engine.answer(request(self.waiting(confirmed=18, normal_confirmed=18)))
        self.assertEqual(reply['reason'], 'tactics_take_drop')
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['gauge_forecast']['gauge_after'], 0)

    def test_one_offset_from_fever_enters_during_a_fever_battle(self):
        own = self.waiting(gauge=6, unconfirmed=200, normal_unconfirmed=200)
        reply = self.engine.answer(request(own, side('fever', seed3())))
        self.assertEqual(reply['chain'], 1)
        self.assertTrue(reply['entry_pending_after_chain'])

    def test_large_unconfirmed_normal_attack_does_not_buy_fever_entry(self):
        own = self.waiting(gauge=6, unconfirmed=200, normal_unconfirmed=200)
        reply = self.engine.answer(request(own))
        self.assertEqual(reply['chain'], 0)
        self.assertFalse(reply['entry_pending_after_chain'])

    def test_tactical_override_keeps_central_input_margin_when_possible(self):
        heights = [2,2,10,10,2,2]
        rows = [''.join('RG'[(x+y)%2] if y >= 14-heights[x] else '.' for x in range(6)) for y in range(14)]
        own = side('normal', rows, ['2:GB'])
        own.update(confirmed=1, normal_confirmed=1)
        reply = self.engine.answer(request(own))
        for candidate in reply['tactics_forecast']['candidates']:
            self.assertTrue(all(sum(row[x] != '.' for row in candidate['field']) <= 10 for x in (2,3)))

    def test_board_too_high_to_take_a_drop_counts_a_clear_as_due(self):
        rows = ['......']*5 + ['RYRY..', 'YRYR..']*4 + ['RYRYGB']
        own = side('normal', rows, ['2:GB'])
        own.update(unconfirmed=60, normal_unconfirmed=60)
        forecast = self.engine.answer(request(own))['tactics_forecast']
        # Nothing has been confirmed, but the board would not stand it: an
        # offset here is not an early one. (This piece pops nothing anywhere.)
        self.assertTrue(all(c['drop_due'] for c in forecast['candidates']))
        low = side('normal', seed_with_small_green(), ['2:GB'])
        low.update(unconfirmed=60, normal_unconfirmed=60)
        forecast = self.engine.answer(request(low))['tactics_forecast']
        self.assertFalse(any(c['drop_due'] for c in forecast['candidates']))

    def test_zero_gain_keeps_the_gauge_free_routine(self):
        own = self.waiting(unconfirmed=200, normal_unconfirmed=200)
        req = request(own); req['gauge_gain_on_offset'] = 0
        self.assertNotIn('tactics_forecast', self.engine.answer(req))

    def test_stacking_plays_the_chain_builder_move(self):
        own = self.waiting(unconfirmed=12, normal_unconfirmed=12)
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=5, r='U')):
            reply = self.engine.answer(request(own))
        self.assertEqual((reply['x'], reply['r'], reply['reason']), (5, 'U', 'tactics_stack'))

    def test_recovery_without_nuisance_does_not_fire_the_longest_reachable_chain(self):
        req = request(self.waiting())
        req.update(op='recover_placement', reachable_placements=[dict(x=x, r='U') for x in range(6)])
        reply = self.engine.answer(req)
        self.assertEqual(reply['chain'], 0)

    def test_enemy_chain_with_an_empty_tray_is_not_answered_with_the_main_chain(self):
        enemy = side('fever', ['......']*13 + ['RRR...'])
        for phase in (0, None):
            own = side('normal', seed_with_small_green(), ['2:GY'])
            own['garbage_phase'] = phase
            if phase is None:
                own['garbage_phase_status'] = 'unknown'
            req = request(own, enemy)
            req['enemy_chain'] = dict(trigger_field=['......']*13 + ['RRRR..'], elapsed=0, scored_links=0,
                mode_generation=enemy['mode_generation'], seed_id=enemy['seed_id'])
            reply = self.engine.answer(req)
            self.assertLess(reply['chain'], 3, reply['reason'])

    def ending(self, **nuisance):
        own = side('fever', ['......']*13 + ['GGG.RR'], ['2:GY'])
        own.update(seed_chain=5, seed_base=5, remaining_frames=20)
        own.update(nuisance)
        return own

    def test_fever_ends_without_a_fire_when_nothing_is_carried(self):
        reply = self.engine.answer(request(self.ending()))
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['seed_forecast']['choice']['carried_nuisance'], 0)

    def test_harmless_held_nuisance_does_not_force_a_failed_fire(self):
        reply = self.engine.answer(request(self.ending(normal_confirmed=4)))
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(reply['seed_forecast']['choice']['carried_nuisance'], 4)

    def test_harmful_held_nuisance_keeps_the_last_offset(self):
        reply = self.engine.answer(request(self.ending(normal_confirmed=50)))
        self.assertGreater(reply['chain'], 0)

    def test_stored_board_that_cannot_take_the_drop_is_not_called_harmless(self):
        own = self.ending(normal_confirmed=4)
        own['stored_field'] = ['......', '..RY..'] + ['..YR..', '..RY..']*6
        self.assertEqual(self.engine._quiet_carry_limit(own), 0)
        self.assertGreater(self.engine.answer(request(own))['chain'], 0)

    def test_fever_side_drop_is_taken_on_the_fever_board_instead_of_carried(self):
        own = self.ending(confirmed=24, fever_confirmed=24)
        own['remaining_frames'] = 60
        reply = self.engine.answer(request(own))
        first = reply['seed_forecast']['choice']
        self.assertEqual(reply['chain'], 0)
        self.assertEqual(first['dropped'], 24)
        self.assertEqual(first['carried_nuisance'], 0)
        self.assertFalse(first['dead'])

    def test_seed_reaching_fire_is_still_made_at_the_end(self):
        own = side('fever', seed3(), ['2:RY'])
        own.update(remaining_frames=60)
        self.assertGreaterEqual(self.engine.answer(request(own))['chain'], 3)

    def first_seed(self, enemy=None, **nuisance):
        """A five-chain seed with its fire in hand and room to build on."""
        refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        self.boards = {s['id']: s['field'] for s in refs['seeds']}
        own = side('fever', self.boards['zabuton-5'], ['2:BR', '2:YR', '2:GR'])
        own.update(character='arle', seed_chain=5, seed_base=5, remaining_frames=900)
        own.update(nuisance)
        enemy = enemy or side('normal')
        enemy['character'] = 'arle'
        return self.engine.answer(request(own, enemy))

    def their_board(self, rows=None, **changes):
        enemy = side('normal', rows)
        enemy.update(changes)
        return enemy

    def their_fever(self, held):
        enemy = side('fever', seed3())
        enemy.update(normal_confirmed=held)
        return enemy

    def test_seed_is_fired_at_once_when_it_lands_on_their_normal_board(self):
        reply = self.first_seed()
        self.assertEqual(reply['seed_forecast']['press_reason'], 'lands_on_their_normal_board')
        self.assertEqual(reply['chain'], 5)

    def test_seed_is_built_on_against_an_opponent_who_holds_a_main_chain(self):
        self.first_seed()
        reply = self.first_seed(self.their_board(self.boards['hirazumi-12']))
        self.assertIsNone(reply['seed_forecast']['press_reason'])
        self.assertEqual(reply['chain'], 0)

    def test_seed_is_built_on_while_nuisance_is_held_for_this_side(self):
        self.assertEqual(self.first_seed(normal_confirmed=60)['chain'], 0)

    def test_seed_is_built_on_when_their_board_already_has_all_it_can_take(self):
        # A little more on top of what already fills the board changes nothing.
        reply = self.first_seed(self.their_board(confirmed=200, normal_confirmed=200))
        self.assertIsNone(reply['seed_forecast']['press_reason'])
        self.assertEqual(reply['chain'], 0)

    def test_seed_is_fired_at_once_when_both_are_in_fever_and_they_hold_nuisance(self):
        reply = self.first_seed(self.their_fever(30))
        self.assertEqual(reply['seed_forecast']['press_reason'], 'opponent_in_fever_holds_nuisance')
        self.assertEqual(reply['chain'], 5)

    def test_seed_is_built_on_when_both_are_in_fever_and_they_hold_none(self):
        self.assertEqual(self.first_seed(self.their_fever(0))['chain'], 0)

    def jab(self, rate, enemy, events=None):
        self.engine.enemy_analysis = None
        """A seven chain with a single ready beside it, the single's colour in hand, nothing pending."""
        refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows = list(next(s['field'] for s in refs['seeds'] if s['id'] == 'hirazumi-7'))
        rows[4:7] = ['Y.....']*3
        own = side('normal', rows, ['2:YG', '2:GB', '2:GB'])
        own['character'] = enemy['character'] = 'arle'
        req = request(own, enemy)
        req['target_point'] = rate
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=5, r='U')):
            with patch.object(self.engine, '_enemy_events', return_value=events or []):
                return self.engine.answer(req)

    def in_fever(self):
        # A grown opponent seed keeps these timing tests about the jab;
        # against a low seed the seven-chain main can now overpower it.
        enemy = side('fever', seed3())
        enemy['seed_chain'] = 15
        return enemy

    def test_single_is_not_fired_at_a_fever_opponent_while_it_sends_nothing(self):
        reply = self.jab(120, self.in_fever())
        self.assertEqual((reply['reason'], reply['chain']), ('normal_build_or_fire', 0))

    def test_single_waits_when_the_next_seed_time_is_unknown(self):
        reply = self.jab(30, self.in_fever())
        self.assertEqual((reply['reason'], reply['chain']), ('normal_build_or_fire', 0))

    def test_single_waits_if_its_end_is_too_early_or_too_late(self):
        for frame in (0, 1000):
            reply = self.jab(30, self.in_fever(), [dict(type='end', frame=frame)])
            self.assertEqual(reply['chain'], 0)

    def test_adequate_packet_at_the_end_of_their_chain_counts_in_full(self):
        reply = self.jab(3, self.in_fever(), [dict(type='end', frame=105)])
        self.assertEqual(reply['chain'], 1)
        self.assertEqual(reply['tactics_forecast']['choice']['projected_disrupt'], 1.0)

    def test_a_later_timed_attack_does_not_pay_for_an_early_clear(self):
        from fever_battle import tactics
        own = side('normal', ['......']*13+['RRRGGG'], ['2:RY','2:GY'])
        own['character'] = 'arle'
        reply = tactics.choose(self.engine.native, self.engine.scoring, own, 30, 1,
            self.engine.policy['normal_tactics'], enemy_events=[dict(type='end',frame=140)],
            enemy=self.in_fever(), fever=dict(enemy_fever=True,their_end=140))
        clearing = [c for c in reply['tactics_forecast']['candidates'] if c['chain']]
        self.assertTrue(clearing)
        self.assertTrue(all(c['projected_disrupt'] == 0 for c in clearing))

    def test_future_large_attack_uses_main_counter_without_false_disruption(self):
        reply = self.jab(30, self.in_fever(), [dict(type='link', frame=300, points=3000), dict(type='end', frame=350)])
        # main's sufficient-counter policy can fire the main chain here; its
        # label must not falsely claim a turnover disruption by a small shot.
        self.assertGreaterEqual(sum(reply['link_points']), 3000)
        self.assertEqual(reply['tactics_forecast']['choice']['projected_disrupt'], 0)

    def test_entry_does_not_authorize_an_unready_main_pressure(self):
        entering = side()
        entering['gauge'] = 7
        reply = self.jab(30, entering, [dict(type='end', frame=60)])
        self.assertEqual(reply['reason'], 'normal_build_or_fire')
        self.assertFalse(reply['fire'])

    def test_single_is_not_sent_at_an_opponent_on_a_normal_board(self):
        self.assertEqual(self.jab(30, bystander())['chain'], 0)

    def clearable(self, enemy):
        own = side('normal', ['......']*13 + ['RRRBBB'], ['2:RB', '2:RY', '2:GY'])
        own['character'] = enemy['character'] = 'arle'
        return self.engine.answer(request(own, enemy))

    def test_board_is_cleared_whole_when_the_piece_allows(self):
        reply = self.clearable(bystander())
        self.assertEqual(reply['reason'], 'tactics_all_clear')
        self.assertTrue(reply['next_all_clear'])

    def test_board_is_not_cleared_into_an_opponent_who_holds_a_main_chain(self):
        refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        holding = side('normal', next(s['field'] for s in refs['seeds'] if s['id'] == 'hirazumi-12'))
        self.assertNotEqual(self.clearable(holding)['reason'], 'tactics_all_clear')

    def test_next2_all_clear_is_searched_and_its_setup_is_played(self):
        own = side('normal', ['......']*13 + ['RRBBYY'], ['2:RR', '2:BB', '2:YY'])
        own['character'] = 'arle'
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=5, r='U')):
            reply = self.engine.answer(request(own))
        self.assertEqual(reply['reason'], 'tactics_all_clear')
        self.assertEqual(reply['tactics_forecast']['completed_depth'], 3)
        self.assertTrue(reply['tactics_forecast']['choice']['projected_all_clear'])
        # Follow the selected setups, rather than asserting only a forecast.
        for _ in range(3):
            result = self.engine.native.ask(dict(op='transition', field=own['field'],
                piece=own['queue'][0], x=reply['x'], r=reply['r']))
            if result['all_clear']:
                break
            own['field'] = result['field']
            own['queue'] = own['queue'][1:]
            own['piece_id'] += 1
            own['dropset_index'] += 1
            reply = self.engine.answer(request(own))
        self.assertTrue(result['all_clear'])

    def test_six_chain_all_clear_does_not_spend_an_unfinished_large_main(self):
        refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows = next(s['field'] for s in refs['seeds'] if s['id'] == 'hirazumi-6')
        own = side('normal', rows, ['2:BG']); own['character'] = 'arle'
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=5, r='U')):
            reply = self.engine.answer(request(own))
        self.assertEqual(reply['reason'], 'normal_build_or_fire')
        self.assertFalse(reply['fire'])
        self.assertEqual(reply['normal_build_target_chain'],15)

    def test_few_nuisance_do_not_buy_an_unnecessary_fever_entry(self):
        for amount in (1, 3, 5):
            own = self.waiting(confirmed=amount, normal_confirmed=amount, gauge=6)
            with patch.object(self.engine.solo, 'ask', return_value=dict(x=1, r='U')):
                reply = self.engine.answer(request(own))
            self.assertEqual(reply['chain'], 0, (amount, reply['reason']))
            self.assertEqual(reply['reason'], 'tactics_take_drop')

    def test_a_disruption_can_be_prepared_with_a_non_clearing_piece(self):
        refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows = list(next(s['field'] for s in refs['seeds'] if s['id'] == 'hirazumi-7'))
        rows[5:7] = ['Y.....']*2
        own = side('normal', rows, ['2:YG', '2:YG'])
        own['character'] = 'arle'
        req = request(own, self.in_fever()); req['target_point'] = 3
        with patch.object(self.engine.solo, 'ask', return_value=dict(x=5, r='U')), \
             patch.object(self.engine, '_enemy_events', return_value=[dict(type='end', frame=140)]):
            reply = self.engine.answer(req)
        self.assertEqual((reply['reason'], reply['chain']), ('tactics_disrupt', 0))
        self.assertGreater(reply['tactics_forecast']['choice']['projected_disrupt'], 0)


if __name__ == '__main__':
    unittest.main()
