"""BattleEngine follows a modified game: side['pattern'] (drop set) and side['powers'] (chain powers).

Uses a built fever_battle.exe (AMA_FEVER_BATTLE_EXE, or bin/fever_battle/fever_battle.exe). Skipped if absent.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXE = Path(os.environ.get('AMA_FEVER_BATTLE_EXE', ROOT / 'bin/fever_battle/fever_battle.exe'))
MODIFIED = [0, 8, 17, 23, 40, 71, 118, 178, 239, 300, 377, 454, 534, 613, 693, 699, 699, 699, 699]


@unittest.skipUnless(EXE.exists(), 'fever_battle.exe not built')
class EngineFollowsGameTest(unittest.TestCase):
    def setUp(self):
        from fever_battle.engine import BattleEngine
        self.engine = BattleEngine(EXE, ROOT / 'bin/fever/fever.exe', ROOT / 'config.json')

    def tearDown(self):
        self.engine.close()

    def test_powers_follow_and_restore(self):
        engine = self.engine
        engine.sync_powers(dict(character='arle', powers={'normal': MODIFIED}))
        self.assertEqual(engine.scoring.data['characters']['arle']['normal'], MODIFIED)
        self.assertEqual(engine.native.ask({'op': 'scoring_override', 'character': 'arle', 'normal': MODIFIED})['normal'], MODIFIED)
        # the Fever table was not sent: scoring.json stays
        self.assertEqual(engine.scoring.data['characters']['arle']['fever'][:3], [0, 6, 11])
        engine.sync_powers(dict(character='arle'))
        self.assertEqual(engine.scoring.data['characters']['arle']['normal'][4], 35)

    def test_invalid_powers_are_rejected(self):
        for powers in ({'normal': [0, 1]}, {'normal': [1000] * 19}, 'x'):
            with self.assertRaises(ValueError):
                self.engine.sync_powers(dict(character='arle', powers=powers))
        self.assertEqual(self.engine.scoring.data['characters']['arle']['normal'][4], 35)


if __name__ == '__main__':
    unittest.main()
