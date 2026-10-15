"""A late quiet board keeps the main chain it holds (policy normal_build.retain_*).

Boards: AI 2 (ally, the mod's cycle 22222220222222J4) of the 2026-10-14 11:07 session, seeds 4 and 0
(doc/OVERNIGHT_LOG_ANALYSIS_2026-10-14.md, 11.2). The build chose a placement that buried the main it held
(11 to 1 at 59 puyos, 12 to 1 at 63); neither was rebuilt and both rounds were lost.
"""
from pathlib import Path
import itertools
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test'), str(ROOT/'tools')]
from fever_fixtures import NATIVE, SOLO
from fever_battle.mode_engine import ModeBattleEngine
from bench_fever_normal_build import side

ALLY = '22222220222222J4'
RAFISOL = '2JL4222422202LJ0'
# field, queue, piece id, dropset index
SEED_4 = ('....../....../.....Y/.....R/..BYRB/RGGRBB/GRGBGR/#RBRYG/YYBRRY/RGRBBY/RYBRBY/RYGBRG/YGGBBG/YBBRRG',
          ['2:RY', '2:GR', '2:GB'], 26, 10)
SEED_0 = ('....../RR..GY/YB..GB/#R..GR/GG..YR/BG.GBR/BY.GBB/YY.BYG/RB.BRG/RB.YRG/GG.YBB/BBBRGB/RGYRYG/RGYYRR',
          ['2:BG', 'J:BRB', '4:GGYY'], 29, 13)
RETAIN = ('forced_lookahead', 'retain_floor', 'retain_when', 'retain_cells', 'retain_fire_cells', 'retain_fire_chain', 'retain_fire_safe_moves')


class RetainTests(unittest.TestCase):
    calls = itertools.count()

    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.policy = {k: cls.engine.policy['normal_build'].get(k) for k in RETAIN}
        cls.set_value = cls.policy['retain_fire_safe_moves']
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def set_policy(self, on):
        build = self.engine.policy['normal_build']
        for key in RETAIN:
            if on and self.policy[key] is not None:
                build[key] = self.policy[key]
            else:
                build.pop(key, None)

    def reply(self, case, on):
        self.set_policy(on)
        field, queue, piece, index = case
        own, enemy = side('ally'), side('rafisol')
        own.update(field=field.split('/'), queue=queue, piece_id=piece, dropset_index=index, pattern=ALLY,
                   moves_since_chain=20, observed_frame=1500)
        enemy.update(pattern=RAFISOL, queue=['2:RG', 'J:BRB', 'L:GGG'], observed_frame=1500)
        request = dict(protocol_version=3, rule='fever_battle', match_id=f'retain-{piece}-{on}-{next(self.calls)}', frame=1500,
            observation=dict(frame_before=1500, frame_after=1500, match_status='running'), target_point=120,
            gauge_gain_on_offset=1, clock_policy=dict(count_chain_frames=True), self=own, enemy=enemy,
            solo_options=dict(beam_width=100, beam_depth=8, margin=1, trigger=15, panic_chain=13,
                              panic_count=70, panic_step=2, patience=46),
            second_target_chain=14, decision_budget_ms=100)
        self.engine.normal_build_cache = None
        return self.engine.answer(dict(request, op='think'))

    def held(self, rows):
        return self.engine.native.ask(dict(op='holding', field=rows))['longest']

    def test_the_policy_is_on_for_a_quiet_late_board(self):
        self.assertEqual(self.policy['retain_when'], 'quiet')
        self.assertLessEqual(self.policy['retain_cells'], self.policy['retain_fire_cells'])

    def test_a_placement_that_keeps_the_main_is_taken_where_the_build_buried_it(self):
        field, *_ = SEED_4
        held = self.held(field.split('/'))
        self.assertEqual(held, 11)
        before = self.reply(SEED_4, on=False)
        after = self.reply(SEED_4, on=True)
        self.assertEqual((before['x'], before['r']), (0, 'R'))       # the logged move
        buried = self.held(before['next_field']) if not before['fire'] else 0
        self.assertLessEqual(buried, 1)
        self.assertFalse(after['fire'])
        self.assertGreaterEqual(self.held(after['next_field']), held)

    def test_with_no_room_left_the_main_is_fired_whatever_its_length(self):
        before = self.reply(SEED_0, on=False)
        self.assertEqual((before['x'], before['r']), (2, 'D'))       # the logged move: buried 12 to 1
        self.assertFalse(before['fire'])
        after = self.reply(SEED_0, on=True)
        self.assertIsNotNone(self.policy['retain_fire_safe_moves'])
        self.assertTrue(after['fire'])                                # 12 is below the fire chain (13)
        self.assertGreaterEqual(after['chain'], 12)
        # the same board with room left is left to the build: the safe-move limit is what fires it
        self.policy['retain_fire_safe_moves'] = None
        self.policy['forced_lookahead'] = False
        try:
            held = self.reply(SEED_0, on=True)
        finally:
            self.policy['retain_fire_safe_moves'] = self.set_value
            self.policy['forced_lookahead'] = True
        self.assertFalse(held['fire'])


if __name__ == '__main__':
    unittest.main()
