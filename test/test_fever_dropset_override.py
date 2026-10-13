"""A game with modified drop sets: the bridge sends side['pattern']; the engine follows it.

Uses a built fever_battle.exe (AMA_FEVER_BATTLE_EXE, or bin/fever_battle/fever_battle.exe). Skipped if absent.
"""
import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(os.environ.get('AMA_FEVER_BATTLE_EXE', ROOT / 'bin/fever_battle/fever_battle.exe'))
MODDED = '22L2220JJ0222L22'


@unittest.skipUnless(EXE.exists(), 'fever_battle.exe not built')
class DropsetOverrideTest(unittest.TestCase):
    def setUp(self):
        self.p = subprocess.Popen([str(EXE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def tearDown(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)

    def ask(self, request):
        self.p.stdin.write(json.dumps(request) + '\n')
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def cycle(self, character):
        reply = self.ask({'op': 'queue', 'character': character, 'seed': 1, 'count': 16})
        return ''.join(text[0] for text in reply['queue'])

    def test_override_applies_and_clears(self):
        official = self.cycle('rafisol')
        self.assertEqual(official, '222L222J24L024J0')
        self.assertEqual(self.ask({'op': 'dropset_override', 'character': 'rafisol', 'pattern': MODDED})['pattern'], MODDED)
        self.assertEqual(self.cycle('rafisol'), MODDED)
        self.assertEqual(self.cycle('ragnus'), '2222L242J202L242')      # other characters untouched
        self.ask({'op': 'dropset_override', 'character': 'rafisol', 'pattern': ''})
        self.assertEqual(self.cycle('rafisol'), official)

    def test_invalid_requests_are_errors(self):
        for request in ({'op': 'dropset_override', 'character': 'rafisol', 'pattern': '22L2'},
                        {'op': 'dropset_override', 'character': 'nobody', 'pattern': MODDED}):
            self.assertIn('error', self.ask(request))
        self.assertEqual(self.cycle('rafisol'), '222L222J24L024J0')

    def test_scoring_override_applies_and_clears(self):
        modified = [0, 8, 17, 23, 40, 71, 118, 178, 239, 300, 377, 454, 534, 613, 693, 699, 699, 699, 699]
        official = self.ask({'op': 'scoring_override', 'character': 'arle'})['normal']
        self.assertEqual(official[4], 35)
        self.assertEqual(self.ask({'op': 'scoring_override', 'character': 'arle', 'normal': modified})['normal'], modified)
        self.assertEqual(self.ask({'op': 'scoring_override', 'character': 'amitie'})['normal'][4], 34)   # others untouched
        self.assertEqual(self.ask({'op': 'scoring_override', 'character': 'arle', 'normal': []})['normal'], official)

    def test_invalid_scoring_overrides_are_errors(self):
        for request in ({'op': 'scoring_override', 'character': 'arle', 'normal': [0, 1, 2]},
                        {'op': 'scoring_override', 'character': 'arle', 'normal': [1000] * 19},
                        {'op': 'scoring_override', 'character': 'nobody', 'normal': [0] * 19}):
            self.assertIn('error', self.ask(request))


if __name__ == '__main__':
    unittest.main()
