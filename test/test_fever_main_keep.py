"""While the opponent's chain still runs, a placement that pops nothing does not bury the main chain.

Boards: AI 2 of seed 2 on 2026-10-13 (doc/WORK_LOG.md), a 12 chain held against a 13 under way with
twelve pieces' time left. Piece 28 was stood upright on the trigger column and left a 3 chain. The
opponent's remaining links are synthetic (tools/investigate_main_keep.py); boards and pieces are logged.
"""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'test'), str(ROOT/'tools')]
from fever_fixtures import NATIVE, SOLO
from fever_battle import tactics
from fever_battle.mode_engine import ModeBattleEngine
from investigate_main_keep import events

BOARD_27 = '....../....Y./B...B./Y...B./BG..YB/BR..YR/YG.GRB/RR.BGB/RGGBGB/GRGYRG/RRYRRG/GBRYYB/GGBBRG/RRBYYY'
BOARD_28 = '....../R...Y./B...B./Y...B./BG..YB/BR..YR/YG.GRB/RR.BGB/RGGBGB/GRGYRG/RRYRRG/GBRYYB/GGBBRG/RRBYYY'


class MainKeepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def longest(self, rows):
        return self.engine.native.ask(dict(op='holding', field=rows))['longest']

    def search(self, board, queue, piece, unconfirmed, scored, ends_in):
        rows = board.split('/')
        own = dict(character='ally', field=rows, queue=queue, confirmed=0, unconfirmed=unconfirmed, remainder=0,
                   garbage_phase=0, gauge=0, piece_id=piece - 1, mode_generation=0, normal_chain_max=0)
        policy = dict(self.engine.policy['normal_tactics'], budget_ms=0)
        forecast = tactics.evaluate(self.engine.native, self.engine.scoring, own, 120, 1, policy,
                                    enemy_events=events(scored, ends_in), enemy=dict(mode='normal', gauge=0), pace=63).forecast
        placed = self.engine.native.ask(dict(op='placements', field=rows, piece=queue[0]))['placements']
        left = {(p['x'], p['r']): self.longest(p['field']) for p in placed if not p['dead'] and not p['links']}
        return rows, forecast, left

    def test_the_trigger_column_is_not_stood_on_while_there_is_time(self):
        for board, queue, piece, unconfirmed, scored, ends_in in (
                (BOARD_27, ['2:RY', '2:BG', '2:BR'], 27, 9, 1080, 752),
                (BOARD_28, ['2:BG', '2:BR', '2:RR'], 28, 17, 2040, 699),
                # more on its way: every placement is then "due" (what is coming kills the board whenever
                # it lands) though none of it falls yet. In play the pair was stood on the trigger here.
                (BOARD_28, ['2:BG', '2:BR', '2:RR'], 28, 29, 3480, 699),
                (BOARD_28, ['2:BG', '2:BR', '2:RR'], 28, 94, 11280, 699)):
            rows, forecast, left = self.search(board, queue, piece, unconfirmed, scored, ends_in)
            held = self.longest(rows)
            self.assertEqual(held, 12)
            piece = (piece, unconfirmed)
            buried = [key for key, main in left.items() if main <= held - 4]
            self.assertTrue(buried, piece)                      # the board offers such placements
            choice = forecast['choice']
            self.assertGreaterEqual(left[(choice['x'], choice['r'])], held, piece)
            ranked = sorted((c for c in forecast['candidates'] if (c['x'], c['r']) in left),
                            key=lambda c: -c['value'])
            # of the placements that pop nothing, none that buries the main is valued above the best
            # that keeps it, and each is charged the links it buries
            best_kept = next(c for c in ranked if left[(c['x'], c['r'])] >= held)
            for c in ranked:
                if left[(c['x'], c['r'])] <= held - 4:
                    self.assertLess(c['value'], best_kept['value'], (piece, c['x'], c['r']))
                    self.assertGreaterEqual(c['main_links_lost'], 4, (piece, c['x'], c['r']))


if __name__ == '__main__':
    unittest.main()
