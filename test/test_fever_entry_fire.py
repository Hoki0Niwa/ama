"""Retiming a fire to start after the opponent's Fever entry (a held piece), and the jab sent that way."""
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
ENTRY = 166


class EntryFireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.cfg = cls.engine.policy['normal_build']['entry_fire']
        cls.timing = ChainTiming.for_mode('normal')
        cls.first = cls.timing.lock_frames(0, None) + cls.timing.first_link_frames

    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def placement(self, links, contact=4, tag='a', x=2, group=4):
        return dict(x=x, r='U', dead=False, links=[dict(groups=[group], colors=1)]*links, split_distances=[0],
                    fall_distances=[1]*links, field=[tag]*14, all_clear=False, contact_height=contact)

    def choose(self, plans, baseline=None, held=None, incoming=0, entry=ENTRY, config=None, enemy_gauge=7, end=150, enemy_pending=0, own_pending=0):
        own = side('normal', queue=['2:RY']); own.update(confirmed=own_pending, normal_confirmed=own_pending); enemy = side('normal'); enemy.update(gauge=enemy_gauge, normal_confirmed=enemy_pending)
        events = [dict(type='end', frame=end)]
        if incoming:
            events.insert(0, dict(type='link', frame=end - 10, nuisance=incoming, points=incoming*RATE))
        req = request(own, enemy); req.update(enemy_chain=dict(mode_generation=0, seed_id=0), frame=1000)
        fever = dict(enemy_fever=True, enemy_fever_at=entry, disrupt_window=122)
        longest = held or {}
        def ask(query):
            if query['op'] == 'placements': return dict(placements=plans)
            return dict(longest=longest.get((query['field'][0],), 0))
        # The geometry fixtures put entry 166F away. Relax the policy wait cap
        # here; the production cap has its own explicit regression test.
        with patch.object(self.engine.native, 'ask', side_effect=ask):
            return self.engine.entry_fire.choose(req, own, enemy, baseline or dict(fire=False), {**self.cfg, 'max_jab_hold_frames':1000, **(config or {})},
                {}, events=events, fever=fever, rate=RATE, pace=None), req

    def test_automatic_jab_does_not_freeze_a_piece_for_multiple_build_turns(self):
        limit=self.cfg.get('max_jab_hold_frames',60)
        reply,_=self.choose([self.placement(1,group=12)],config=dict(max_jab_hold_frames=limit))
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'],'jab_waits_too_long')
        reply,_=self.choose([self.placement(1,group=12)],entry=40,config=dict(max_jab_hold_frames=limit))
        self.assertIsNotNone(reply)
        self.assertLessEqual(reply['hold_frames'],limit)

    def test_a_chosen_fire_is_held_until_its_first_link_starts_at_the_entry(self):
        plan = self.placement(10)
        reply, req = self.choose([plan], baseline=dict(fire=True, x=2, r='U', reason='normal_build_or_fire'))
        shot = reply['entry_fire']
        self.assertEqual(shot['kind'], 'retimed')
        floor = self.timing.first_link_frames + self.cfg['fast_lock_frames']
        self.assertEqual(shot['hold_frames'], ENTRY + self.cfg['margin_frames'] - floor)
        self.assertEqual(shot['first_link'], ENTRY + self.cfg['margin_frames'])
        self.assertEqual(reply['hold_down_until_frame'], 1000 + shot['hold_frames'])
        self.assertEqual(reply['reason'], 'normal_build_or_fire')

    def test_no_hold_when_the_fastest_first_link_already_starts_after_the_entry(self):
        reply, _ = self.choose([self.placement(10)], baseline=dict(fire=True, x=2, r='U'), entry=1,
                               config=dict(margin_frames=0))
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'nothing_to_retime')
        # With the policy's margin for the error of the entry's prediction, a few frames of hold remain.
        reply, _ = self.choose([self.placement(10)], baseline=dict(fire=True, x=2, r='U'), entry=1)
        self.assertEqual(reply['entry_fire']['hold_frames'], 1 + self.cfg['margin_frames'] - 15 - self.cfg['fast_lock_frames'])

    def test_a_piece_that_cannot_be_held_that_long_is_left_alone(self):
        # Resting at the 11th row: almost no natural fall to wait in.
        reply, _ = self.choose([self.placement(10, contact=11)], baseline=dict(fire=True, x=2, r='U'))
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'cannot_hold_long_enough')

    def test_a_fire_that_sends_nothing_is_not_retimed(self):
        reply, _ = self.choose([self.placement(10)], baseline=dict(fire=True, x=2, r='U'), incoming=10000)
        self.assertIsNone(reply)

    def test_jab_is_sent_when_nothing_was_chosen_and_the_main_is_kept(self):
        jab = self.placement(1, tag='j', group=12)
        reply, req = self.choose([jab, self.placement(1, tag='s')], held={('j',): 8, ('a',): 0}, config=dict(main_min=8))
        self.assertEqual(reply['reason'], 'normal_entry_jab')
        self.assertEqual(reply['entry_fire']['kind'], 'jab')
        self.assertGreaterEqual(reply['entry_fire']['sent'], self.cfg['min_jab_sent'])
        self.assertLessEqual(reply['entry_fire']['end'], ENTRY + 122)

    def test_jab_that_spends_the_main_or_is_too_slow_is_not_sent(self):
        jab = self.placement(1, tag='j', group=12)
        # The main it leaves is shorter than the one held before.
        reply, _ = self.choose([jab], held={('......',): 9, ('j',): 5}, config=dict(main_min=8))
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'jab_spends_the_main')
        reply, _ = self.choose([jab], held={('......',): 9, ('j',): 9}, config=dict(main_min=8))
        self.assertIsNotNone(reply)
        reply, _ = self.choose([jab], config=dict(min_jab_sent=10**6))
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'no_jab_fits')
        # Two links miss the turnover window; a long free fall is not justified by a late jab.
        late = self.placement(2, tag='j', group=14)
        reply, _ = self.choose([late])
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'no_jab_fits')
        reply, _ = self.choose([late], config=dict(max_late_frames=0))
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'no_jab_fits')

    def test_their_chain_is_offset_by_their_own_pending_before_it_reaches_us(self):
        # 2026-10-25: 898 still to come from their chain, 1236 pending on them: nothing of it flies at us.
        jab = self.placement(1, tag='j', group=12)
        reply, _ = self.choose([jab], incoming=898)
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['incoming'], 898)
        self.assertEqual(self.engine.entry_fire.status['why'], 'nuisance_comes_back')
        reply, _ = self.choose([jab], incoming=898, enemy_pending=1236)
        self.assertEqual(reply['entry_fire']['sent'], 8)
        # Whatever their pending cannot take reaches us as a notice: no jab, no held piece, however much the shot sends.
        for pending in (898 - 2, 898 - 800):
            reply, _ = self.choose([jab, self.placement(10)], incoming=898, enemy_pending=pending,
                                   baseline=dict(fire=True, x=2, r='U'))
            self.assertIsNone(reply)
            self.assertEqual(self.engine.entry_fire.status['why'], 'nuisance_comes_back')
        # A notice already waiting on us says the same.
        reply, _ = self.choose([jab], own_pending=3)
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'nuisance_comes_back')

    def test_a_counter_in_flight_is_not_offset_by_their_pending_again(self):
        # 2026-10-25, 1P pair 31: 81 nuisance of their counter object in flight, 90 pending on them: it still comes back.
        from fever_battle.chain_to_us import chain_to_us
        enemy = side('normal'); enemy.update(normal_confirmed=90)
        counter = dict(type='link', frame=6, nuisance=81, points=81, source='observed_counter_flight')
        self.assertEqual(chain_to_us([counter, dict(type='end', frame=6)], enemy, RATE), 81)
        link = dict(type='link', frame=6, nuisance=81, points=81*RATE)
        self.assertEqual(chain_to_us([link, dict(type='end', frame=6)], enemy, RATE), 0)

    def test_a_chain_that_returns_nuisance_is_never_weighed_for_a_jab(self):
        own = side('normal', queue=['2:RY']); enemy = side('normal'); enemy.update(gauge=7)
        req = request(own, enemy); req.update(enemy_chain=dict(mode_generation=0, seed_id=0), frame=1000)
        fever = dict(enemy_fever=True, enemy_fever_at=ENTRY, disrupt_window=122)
        with patch.object(self.engine.native, 'ask') as native:
            reply = self.engine.entry_fire.choose(req, own, enemy, dict(fire=False), self.cfg, {},
                events=[dict(type='end', frame=150)], fever=fever, rate=RATE, pace=None, chain_returns=True)
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status, dict(why='chain_returns_nuisance'))
        native.assert_not_called()          # nothing is searched for it

    def test_the_verdict_on_a_chain_is_judged_whole_and_then_only_turns_to_yes(self):
        # 2026-10-25, pair 31: 789 sent by their chain, 708 pending on them: 81 come back, from the first decision on.
        links = [dict(type='link', frame=100 + 60*i, points=0, nuisance=n) for i, n in enumerate((300, 200, 189, 100))]
        enemy = side('normal'); enemy.update(gauge=7, normal_confirmed=708)
        req = request(side('normal'), enemy)
        def verdict(model, events=(), flying=0):
            self.engine.enemy_analysis = model
            req['observation']['in_flight'] = dict(self=dict(incoming_in_flight=flying), enemy={})
            return self.engine._chain_returns(req, model['enemy'] if model else enemy, list(events), RATE)
        model = dict(firing=[0, 0, 0], events=links + [dict(type='end', frame=400)], enemy=enemy)
        try:
            self.assertTrue(verdict(model))
            model['enemy']['normal_confirmed'] = 10**6
            self.assertTrue(verdict(model))                                    # later observations do not undo it
            covered = dict(firing=[0, 0, 0], events=links, enemy=dict(enemy, normal_confirmed=789))
            self.assertFalse(verdict(covered))                                 # their pending takes all of it
            self.assertFalse(verdict(covered, events=[dict(type='end', frame=1)]))
            # The last link was scored, not yet launched: the remaining links and flights show nothing, the verdict stands.
            seen = dict(firing=[0, 0, 0], events=links, enemy=dict(enemy, normal_confirmed=789))
            self.assertFalse(verdict(seen))
            rest = [dict(type='link', frame=900, nuisance=81, points=0)]
            late = dict(enemy, normal_confirmed=0)
            self.engine.enemy_analysis = seen
            self.assertTrue(self.engine._chain_returns(req, late, rest, RATE))
            self.assertTrue(self.engine._chain_returns(req, late, [], RATE))
            self.assertTrue(verdict(dict(covered, events=links), flying=5))
            self.assertFalse(verdict(dict(model, firing=None)))
            self.assertFalse(verdict(None))
        finally:
            self.engine.enemy_analysis = None

    def test_an_attack_in_flight_at_us_skips_the_jab(self):
        jab = self.placement(1, tag='j', group=12)
        own = side('normal', queue=['2:RY']); enemy = side('normal'); enemy.update(gauge=7)
        req = request(own, enemy); req.update(enemy_chain=dict(mode_generation=0, seed_id=0), frame=1000)
        req['observation']['in_flight'] = dict(self=dict(incoming_in_flight=20), enemy={})
        fever = dict(enemy_fever=True, enemy_fever_at=ENTRY, disrupt_window=122)
        with patch.object(self.engine.native, 'ask', return_value=dict(placements=[jab], longest=0)):
            reply = self.engine.entry_fire.choose(req, own, enemy, dict(fire=False), self.cfg, {},
                events=[dict(type='end', frame=150)], fever=fever, rate=RATE, pace=None)
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'nuisance_comes_back')
        self.assertEqual(self.engine.entry_fire.status['in_flight'], 20)

    def test_a_long_chain_is_never_a_jab(self):
        # 2026-10-25: a 6-chain (78 nuisance) was sent as the jab; here four links stand for it; a jab is at most three links.
        long = self.placement(4, tag='j', group=8)
        reply, _ = self.choose([long])
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'jab_too_long')
        self.assertEqual(self.cfg['max_jab_chain'], 3)
        reply, _ = self.choose([long], config=dict(max_jab_chain=4))
        self.assertIsNone(reply)
        self.assertEqual(self.engine.entry_fire.status['why'], 'no_jab_fits')

    def test_a_jab_confirmed_inside_the_window_is_preferred_to_a_bigger_late_one(self):
        quick = self.placement(1, tag='q', group=12)
        slow = self.placement(2, tag='s', group=24, x=3)
        reply, _ = self.choose([slow, quick])
        self.assertEqual(reply['x'], 2)
        self.assertTrue(reply['entry_fire']['in_window'])

    def test_only_an_entering_opponent_with_a_chain_is_a_target(self):
        self.assertIsNone(self.choose([self.placement(10)], baseline=dict(fire=True, x=2, r='U'), enemy_gauge=3)[0])
        self.assertIsNone(self.engine.entry_fire.status)
        self.assertIsNone(self.choose([self.placement(10)], baseline=dict(fire=True, x=2, r='U'),
                                      config=dict(enabled=False))[0])

    def test_protocol_reply_carries_the_hold_and_its_guard(self):
        probes = json.loads((ROOT/'data/fever/baselines/2026-10-11-second-fire-timing-investigation.json').read_text(encoding='utf-8'))['probes']
        own = deepcopy(next(p for p in probes if p['ai'] == 1 and p['pair'] == 61)['own'])
        for key, value in side('normal').items():
            own.setdefault(key, value)
        own.update(confirmed=0, unconfirmed=0, remainder=0, mode_generation=1, garbage_phase=0)
        placements = self.engine.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
        shot = max((p for p in placements if not p['dead']), key=lambda p: len(p['links']))
        points = self.engine.scoring.chain(own['character'], shot['links'])
        chosen = dict(x=shot['x'], r=shot['r'], shape=own['queue'][0][0], reason='normal_build_or_fire', fire=True,
            chain=len(points), next_chain=len(points), next_score=sum(points), next_field=shot['field'],
            link_points=points, next_all_clear=shot['all_clear'], normal_decision_status='build')
        enemy = side('normal'); enemy.update(gauge=7)
        req = request(own, enemy); req.update(enemy_chain=dict(mode_generation=0, seed_id=0), second_target_chain=8, op='think', frame=500)
        req['observation'].update(frame_before=500, frame_after=500)
        req['self']['observed_frame'] = req['enemy']['observed_frame'] = 500
        fever = dict(enemy_fever=True, enemy_fever_at=100, their_end=100, disrupt_window=122, enemy_seed_level=5, enemy_reply_nuisance=0)
        self.engine._normal_options(req, own)
        with patch.object(self.engine, '_observe_enemy_fever', return_value=None),              patch.object(self.engine, '_enemy_events', return_value=[dict(type='end', frame=84)]),              patch.object(self.engine, '_enemy_fever', return_value=fever),              patch.object(self.engine, '_normal', return_value=dict(chosen)):
            reply = self.engine.answer(req)
        hold = reply['hold_frames']
        first = (self.timing.lock_frames(self.timing.split_extra_frames[max(shot['split_distances'], default=0)], None)
                 + self.timing.first_link_frames)
        self.assertEqual(hold, 100 + self.cfg['margin_frames'] - self.timing.first_link_frames - self.cfg['fast_lock_frames'])
        self.assertEqual(reply['hold_down_until_frame'], 500 + hold)
        self.assertEqual(reply['disruption_timing']['kind'], 'entry')
        self.assertEqual(reply['disruption_timing']['first_link_frame'], 500 + 100 + self.cfg['margin_frames'])
        self.assertEqual(reply['entry_fire_status']['why'], 'retimed')
        self.assertEqual((reply['x'], reply['r']), (chosen['x'], chosen['r']))

    def test_guard_follows_the_planned_first_link_and_end(self):
        reply, req = self.choose([self.placement(10)], baseline=dict(fire=True, x=2, r='U'))
        guard = disruption.contract(req, reply, {})
        self.assertEqual(guard['kind'], 'entry')
        reply['disruption_timing'] = guard
        latest = deepcopy(req)
        latest['enemy'].update(mode_generation=0, fever_destination_frame=None)
        self.assertTrue(disruption.valid(reply, latest))
        latest['enemy']['fever_destination_frame'] = guard['first_link_frame'] + 1
        self.assertFalse(disruption.valid(reply, latest))
        latest['enemy']['fever_destination_frame'] = None
        # 2026-10-25: the jab was decided at frame 2930, their counter object (81) was launched at 2941.
        latest['observation']['in_flight'] = dict(self={}, enemy=dict(attacks_in_flight=[dict(amount=81, counter=True)]))
        self.assertFalse(disruption.valid(reply, latest))
        latest['observation']['in_flight'] = dict(self=dict(incoming_in_flight=5), enemy={})
        self.assertFalse(disruption.valid(reply, latest))
        latest['observation']['in_flight'] = dict(self={}, enemy={})
        latest['self']['unconfirmed'] = 3
        self.assertFalse(disruption.valid(reply, latest))
        latest['self']['unconfirmed'] = 0
        latest['enemy']['fever_destination_frame'] = guard['first_link_frame']
        self.assertTrue(disruption.valid(reply, latest))

    def test_request_switch_overrides_the_policy(self):
        policy = self.engine.policy['normal_build']['entry_fire']
        for default, asked, expected in ((True, None, True), (True, False, False), (False, True, True)):
            policy['enabled'] = default
            req = request(); req['normal_tactics'] = {} if asked is None else dict(entry_fire=asked)
            self.assertEqual(self.engine._final_seed_config(req, 'entry_fire')['enabled'], expected)
        policy['enabled'] = True
        with self.assertRaises(ValueError):
            tactical_options.validate(dict(normal_tactics=dict(entry_fire='yes')))
        tactical_options.validate(dict(normal_tactics=dict(entry_fire=False)))


if __name__ == '__main__': unittest.main()
