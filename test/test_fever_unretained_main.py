"""A real main is held while it can still grow and cashed in when nothing keeps it.

Boards: the 2026-10-11 live round where a side stacked beside an available 11
chain until a 2-nuisance packet, plus saved solo builds for the natural clears.
"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test')]
from fever_fixtures import NATIVE, SOLO, side, request
from fever_battle.mode_engine import ModeBattleEngine

LIVE = '....../.Y...R/GY..RR/GR..RY/BY..GY/YRB.GG/GRY.RR/GBRGRG/BYYGGB/BBYBRR/GGBYYB/BYGRBB/GGYYGG/GBBYRG'
ENEMY = '....../GR..BB/BB..GG/GY..RR/GYBBGR/BBYRBB/BYYRGG/GBGRBG/GRRGYR/BRYYRG/BYRBYR/BGRGBR/GRYRBR/GRYRBY'


class UnretainedMainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.saved = json.loads((ROOT/'data/fever/baselines/2026-10-11-second-final.json').read_text(encoding='utf-8'))
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def capacity(self, field, queue, character='rafisol', **extra):
        return self.engine.native.ask(dict(op='normal_capacity', field=field.split('/') if isinstance(field, str) else field,
            queue=queue, character=character, margin=1, target=15, **extra))

    def test_no_quiet_continuation_keeps_a_visible_main_only_under_no_threat(self):
        queue = ['2:BG', '2:BB', '2:YY']
        calm = self.capacity(LIVE, queue)
        self.assertEqual(calm['available_chain'], 11)
        self.assertEqual((calm['retaining_moves'], calm['improving_moves']), (0, 0))
        self.assertFalse(calm['release'])
        hit = self.capacity(LIVE, queue, threat=True)
        self.assertTrue(hit['release'])
        self.assertEqual(hit['reason'], 'unretained_main')

    def test_attacked_side_fires_the_main_it_cannot_keep(self):
        own = side('normal', LIVE.split('/'), ['2:BG', '2:BB', '2:YY'])
        own.update(character='rafisol', gauge=1, moves_since_chain=31, normal_chain_max=1,
                   dropset_index=0, piece_id=32, unconfirmed=2, normal_unconfirmed=2)
        enemy = side('normal', ENEMY.split('/'), ['2:BG']); enemy.update(character='raffina', gauge=2)
        req = request(own, enemy)
        req['solo_options'] = dict(beam_width=200, beam_depth=8, trigger=15, panic_chain=13,
                                   panic_count=70, panic_step=2, patience=46, margin=1)
        events = [dict(type='link', frame=23, points=140), dict(type='end', frame=43)]
        self.engine.pace = None
        with patch.object(self.engine, '_enemy_events', return_value=events):
            reply = self.engine.answer(req)
        self.assertTrue(reply['fire'], reply['reason'])
        self.assertEqual(reply['chain'], 11)

    def test_a_natural_clear_that_leaves_room_is_not_a_lack_of_space(self):
        run = next(r for r in self.saved['runs'] if r['character'] == 'rafisol' and r['seed'] == 2)
        item = next(r for r in run['trace'] if r['move'] == 78)
        c = self.capacity(item['before'], [r['piece'] for r in run['trace'] if 78 <= r['move'] < 81])
        self.assertEqual(c['safe_moves'], 0)
        self.assertGreater(c['survivable_moves'], 0)
        self.assertLess(c['available_chain'], c['main_floor'])
        self.assertFalse(c['release'])
        self.assertEqual(c['reason'], 'natural_clear_continues')

    def test_nothing_that_survives_still_cashes_in_whatever_is_visible(self):
        c = self.capacity(['......']*3 + ['..#...']*11, ['2:RG', '2:GB'], character='raffina')
        self.assertEqual(c['survivable_moves'], 0)
        self.assertTrue(c['release'])
        self.assertEqual(c['reason'], 'no_safe_stack')

    def build(self, field, queue, dropset_index, piece_id):
        own = side('normal', field.split('/'), queue)
        own.update(character='ally', dropset_index=dropset_index, piece_id=piece_id, normal_chain_max=3, moves_since_chain=piece_id)
        req = request(own, side('normal')); req['solo_options'] = dict(trigger=15, beam_width=60, beam_depth=6)
        options = self.engine._normal_options(req, own)
        return options, self.engine._solo_build(own, options)

    def test_opening_cashes_a_visible_main_at_the_firing_chain_when_it_cannot_be_kept(self):
        # Live ally board: a 14 chain was visible at 62 puyos (kept building) and again at 70.
        roomy = '....../G...../B...../G...GR/G...YY/BBYBRB/BYYRGG/GBGRBG/GRRGYR/BRYYRG/BYRBYR/BGRGBR/GRYRBR/GRYRBY'
        full = '....../G...BB/B...GG/GY..RR/GYBBGR/BBYBRB/BYYRGG/GBGRBG/GRRGYR/BRYYRG/BYRBYR/BGRGBR/GRYRBR/GRYRBY'
        options, reply = self.build(roomy, ['2:YY', '2:RR', '4:BBGG'], 13, 29)
        self.assertEqual((options['trigger'], options['panic_chain']), (15, 13))
        # Not a plain target fire: no placement keeps this 14 while stacking on, so
        # it is cashed at the configured firing chain rather than left to decay.
        self.assertTrue(reply['fire'])
        self.assertTrue(reply.get('normal_main_retained'))
        self.assertGreaterEqual(reply['chain'], 13)
        options, reply = self.build(full, ['2:RB', '2:GR', 'L:YYB'], 2, 34)
        self.assertEqual(options['trigger'], 15)
        self.assertTrue(reply['fire'])
        self.assertGreaterEqual(reply['chain'], 13)

    def test_a_visible_main_is_kept_or_fired_not_left_to_decay_into_a_small_dump(self):
        # Solo rafisol build (prototype colors): a 13-14 chain was visible for six
        # moves from move 35; the old opening kept stacking until it was gone and
        # the full board fired a 3 chain at move 42.
        field = '....../....../YR..../YG..YB/GY..RB/GY.YYB/BB.BGG/YGBYYB/RGYGYB/RGYGGB/YBGRYY/RBRYGY/BRYGBB/BRYYGG'
        pieces = ['L:RRR', '2:GR', '2:RB', '2:BG', 'J:GYG', '2:GB', '4:BBRR', 'L:GGR', '0:Y', '2:BG', '4:BBGG', 'J:RRR', '0:G', '2:BY', '2:RB', '2:GR']
        own = side('normal', field.split('/'), pieces[:3])
        own.update(character='rafisol', normal_chain_max=0)
        enemy = side('normal')
        fired = None
        for step in range(len(pieces) - 2):
            own.update(queue=pieces[step:step + 3], dropset_index=35 + step, piece_id=35 + step, observed_frame=step)
            req = request(own, enemy); req['solo_options'] = dict(trigger=15, beam_width=60, beam_depth=6)
            options = self.engine._normal_options(req, own)
            result = self.engine._solo_build(own, options)
            move = self.engine.native.ask(dict(op='transition', field=own['field'], piece=own['queue'][0],
                                               x=result['x'], r=result['r']))
            if len(move['links']) >= 3:
                fired = len(move['links']); break
            own['field'] = move['field']
            own['moves_since_chain'] = own['moves_since_chain'] + 1
        self.assertIsNotNone(fired)
        self.assertGreaterEqual(fired, 13)

    def test_the_threat_flag_is_read_from_pending_nuisance_or_an_observed_chain(self):
        own = side('normal', queue=['2:RY']); req = request(own)
        self.assertFalse(self.engine._under_attack(req, own))
        pending = {**own, 'unconfirmed': 3, 'normal_unconfirmed': 3}
        self.assertTrue(self.engine._under_attack(req, pending))


if __name__ == '__main__': unittest.main()
