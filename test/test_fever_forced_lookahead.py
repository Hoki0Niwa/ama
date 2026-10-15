"""A build that leaves no room for the next visible piece takes the placement that forces the biggest chain.

Boards: AI 1 (rafisol, the mod's cycle 2JL4222422202LJ0) of the 2026-10-14 13:44 session, seed 17-ish rounds
19 and 24 (doc/OVERNIGHT_LOG_ANALYSIS_2026-10-14.md, 15). The build's placement forced an 8 (and a 1) chain
the next move; another placement forced 11 (and 7). Work B of doc/HANDOFF_2026-10-13.md.
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
CASES = (
    # field, queue, piece id, dropset index, the logged move, the chain it forces, the best that is forced
    ('....../....B./.B..B./.R..R./YG..BY/YY.RBR/RR.BYB/BG.RYG/BGGRBG/BRBRBG/RRYGYB/BBYGRB/BGBYGR/RGGBGR',
     ['2:YG', '4:RRGG', '2:GY'], 22, 6, (0, 'D'), 8, 11),
    ('....../R....R/R...G#/RY..RG/GRBBYG/YRYRYR/BYRRYR/BRYBGY/GYYGGY/BRBYBR/RRBYBY/BBRGYG/BGYRGG/RGGYYY',
     ['2:RG', '4:GGBB', '2:RR'], 38, 6, (1, 'D'), 1, 7),
)


class ForcedLookaheadTests(unittest.TestCase):
    calls = itertools.count()

    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        cls.configured = cls.engine.policy['normal_build'].get('forced_lookahead')
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def reply(self, case, on):
        field, queue, piece, index = case[:4]
        build = self.engine.policy['normal_build']
        build['forced_lookahead'] = on
        own, enemy = side('rafisol'), side('ally')
        own.update(field=field.split('/'), queue=queue, piece_id=piece, dropset_index=index, pattern=RAFISOL,
                   moves_since_chain=20, observed_frame=1500)
        enemy.update(pattern=ALLY, queue=['2:RG', '2:BR', '2:GG'], observed_frame=1500)
        request = dict(protocol_version=3, rule='fever_battle', match_id=f'forced-{piece}-{on}-{next(self.calls)}', frame=1500,
            observation=dict(frame_before=1500, frame_after=1500, match_status='running'), target_point=120,
            gauge_gain_on_offset=1, clock_policy=dict(count_chain_frames=True), self=own, enemy=enemy,
            solo_options=dict(beam_width=200, beam_depth=8, margin=1, trigger=15, panic_chain=13,
                              panic_count=70, panic_step=2, patience=46),
            second_target_chain=14, decision_budget_ms=100)
        self.engine.normal_build_cache = None
        return self.engine.answer(dict(request, op='think'))

    def rating(self, case, field, piece_index=0):
        """{(x, r): ('fire', chain) | ('room', 0) | ('forced', best chain next move) | ('dead', -1)}"""
        native = self.engine.native
        rated = {}
        for p in native.ask(dict(op='placements', field=field.split('/'), piece=case[1][piece_index]))['placements']:
            if p['dead']:
                continue
            if p['links']:
                rated[(p['x'], p['r'])] = ('fire', len(p['links']))
                continue
            following = native.ask(dict(op='placements', field=p['field'], piece=case[1][piece_index + 1]))['placements']
            alive = [q for q in following if not q['dead']]
            if any(not q['links'] for q in alive):
                rated[(p['x'], p['r'])] = ('room', 0)
            else:
                rated[(p['x'], p['r'])] = ('forced', max((len(q['links']) for q in alive), default=-1))
        return rated

    def test_the_policy_is_on(self):
        self.assertTrue(self.configured)

    def test_a_forced_move_is_the_biggest_chain_that_can_be_forced(self):
        for case in CASES:
            with self.subTest(case=case[4]):
                rated = self.rating(case, case[0])
                best = max(v[1] for v in rated.values() if v[0] in ('fire', 'forced'))
                self.assertGreaterEqual(best, case[6])                       # the board offers it
                after = self.reply(case, on=True)
                mine = rated[(after['x'], after['r'])]
                self.assertTrue(mine[0] == 'room' or mine[1] >= best, (mine, best))
                if rated[case[4]][0] == 'forced':                            # the logged placement is rated, not rebuilt
                    self.assertEqual(rated[case[4]][1], case[5])
                    self.assertNotEqual((after['x'], after['r']), case[4])


if __name__ == '__main__':
    unittest.main()
