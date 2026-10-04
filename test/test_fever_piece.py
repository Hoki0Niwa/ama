"""Compile T1's API and compare its complete table with the tracked JSON data."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FeverPieceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = r'C:\msys64\mingw64\bin\g++.exe' if os.name == 'nt' else 'g++'
        compiler = shutil.which(os.environ.get('AMA_CXX', default))
        if not compiler:
            raise RuntimeError('C++20 compiler unavailable; set AMA_CXX')
        output = ROOT / 'bin/test/fever-piece.exe'
        output.parent.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, PATH=str(Path(compiler).parent) + os.pathsep + os.environ.get('PATH', ''))
        compiled = subprocess.run([compiler, '-std=c++20', '-O2', '-Wall', '-Wextra', '-Werror',
                                   '-static', str(ROOT / 'core/dropset.cpp'),
                                   str(ROOT / 'test/fever_piece_test.cc'), '-o', str(output)],
                                  env=environment, capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + compiled.stderr)
        cls.native = subprocess.run([str(output)], env=environment, capture_output=True, text=True, timeout=15)
        if cls.native.returncode:
            raise RuntimeError(cls.native.stdout + cls.native.stderr)
        cls.rows = [line.split('\t') for line in cls.native.stdout.splitlines()]
        cls.data = json.loads((ROOT / 'data/fever/dropsets.json').read_text(encoding='utf-8'))

    def test_native_piece_and_lookup_contracts(self):
        self.assertIn('checks passed', self.native.stderr)

    def test_compiled_table_matches_json(self):
        characters = self.data['characters']
        self.assertEqual(len(characters), 26)
        self.assertEqual(len({c['id'] for c in characters}), 26)
        self.assertEqual([r[0] for r in self.rows], [c['id'] for c in characters])
        self.assertEqual(self.data['triple_mapping']['L'], 'vertical')
        self.assertEqual(self.data['triple_mapping']['J'], 'horizontal')
        for row, character in zip(self.rows, characters):
            with self.subTest(character=character['id']):
                ident, status, pattern, alt, three_cycles, last = row
                self.assertEqual(status, character['status'])
                self.assertEqual(pattern, character['pattern'] or '')
                self.assertEqual(alt, character['pattern_alt'] or '')
                expected = pattern or alt
                if status == 'unknown':
                    self.assertFalse(expected)
                    self.assertEqual(three_cycles, '?' * 48)
                    self.assertEqual(last, '?')
                    continue
                self.assertEqual(len(expected), 16)
                self.assertTrue(set(expected) <= set('2LJ340*'))
                expected = expected.replace('*', '0')
                self.assertEqual(three_cycles, expected * 3)
                self.assertEqual(last, expected[-1])
                counts = dict(pair=expected.count('2'), triple=sum(expected.count(c) for c in 'LJ3'),
                              quad=expected.count('4'), big=expected.count('0'))
                self.assertEqual(counts, character['counts'])
                self.assertEqual(sum(counts.values()), 16)
                self.assertEqual(2 * counts['pair'] + 3 * counts['triple'] +
                                 4 * (counts['quad'] + counts['big']), character['total'])
                if pattern and alt:
                    self.assertEqual(pattern.replace('L', '3').replace('J', '3').replace('0', '*'), alt)
                for move, orientation in character.get('triple_orientation', {}).items():
                    self.assertEqual(expected[int(move) - 1], {'vertical': 'L', 'horizontal': 'J'}[orientation])


if __name__ == '__main__':
    unittest.main(verbosity=2)
