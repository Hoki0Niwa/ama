"""Recorded small attacks must not be answered by the largest future main."""
import json
import unittest
import tempfile
from pathlib import Path
from fever_fixtures import ROOT,NATIVE,SOLO
from fever_battle.mode_engine import ModeBattleEngine


class SmallAttackPreservationTests(unittest.TestCase):
    def test_recorded_build_keeps_an_accessible_main_after_rejecting_a_costly_jab(self):
        case=json.loads((ROOT/'data/fever/golden/pressure-main-extension.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory(dir=ROOT/'bin') as tmp:
            config=Path(tmp)/'weights.json';config.write_text(json.dumps(case['weights']),encoding='utf-8')
            engine=ModeBattleEngine(NATIVE,SOLO,config)
            try:
                engine.answer(dict(case['request'],op='prepare_observed'))
                reply=engine.prepared[2]
                roots=reply['normal_root_values']
                best=max(c['held_main'] for c in roots if c['next_room']>0)
                chosen=next(c for c in roots if (c['x'],c['r'])==(reply['x'],reply['r']))
                self.assertGreaterEqual(best,5)
                self.assertGreaterEqual(chosen['held_main'],best-1)
                self.assertGreaterEqual(engine.native.ask(dict(op='holding',field=reply['next_field']))['longest'],5)
            finally:engine.close()

    def test_recorded_recoveries_keep_more_main_while_covering_the_packet(self):
        cases=json.loads((ROOT/'data/fever/golden/small-attack-main-preservation.json').read_text(encoding='utf-8'))['cases']
        engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
        try:
            # Old projected main-link losses were 8,8,8 respectively.
            for case in cases:
                with self.subTest(line=case['line']):
                    reply=engine.answer(case['request'])
                    choice=reply['tactics_forecast']['choice']
                    self.assertTrue(choice['projected_sufficient_return'])
                    self.assertTrue(choice['current_survives'])
                    self.assertLess(choice['main_links_lost'],8)
                    if case['line']==176:
                        self.assertNotEqual((reply['x'],reply['r']),(0,'D'))
        finally:engine.close()


if __name__=='__main__':unittest.main()
