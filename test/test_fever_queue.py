"""Check T3's queue generators against an independent Python model of the color rules."""
from collections import Counter
from pathlib import Path
import json
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
MASK = (1 << 64) - 1
COLORS = 'RYGB'
BAGS = ['RYGB', 'RGYB', 'RBYG', 'YGRB', 'YBRG', 'GBRY']


def splitmix(state):
    while True:
        state = (state + 0x9E3779B97F4A7C15) & MASK
        z = state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        yield z ^ (z >> 31)


def layout(symbol, a, b):
    return {'2': '2:' + a + b, 'L': '3:' + a + a + b, 'J': '3:' + a + b + a,
            '4': '4:' + a + a + b + b, '0': '0:' + a}[symbol]


def real(pattern, seed, start, count):
    rng = splitmix(seed)
    result = []
    for i in range(count):
        symbol = pattern[(start + i) % 16]
        a = next(rng) >> 62
        if symbol == '4':
            b = (a + 1 + (((next(rng) >> 32) * 3) >> 32)) % 4
        elif symbol == '0':
            b = a
        else:
            b = next(rng) >> 62
        result.append(layout(symbol, COLORS[a], COLORS[b]))
    return result


def virtual(pattern, bag, start, count):
    dealt = 0
    result = []
    for i in range(count):
        symbol = pattern[(start + i) % 16]
        if symbol == '0':
            result.append('0:R')
            continue
        a, b = BAGS[bag][dealt % 4], BAGS[bag][(dealt + 1) % 4]
        dealt += 2
        result.append(layout(symbol, a, b))
    return result


class FeverQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = r'C:\msys64\mingw64\bin\g++.exe' if os.name == 'nt' else 'g++'
        compiler = shutil.which(os.environ.get('AMA_CXX', default))
        if not compiler:
            raise RuntimeError('C++20 compiler unavailable; set AMA_CXX')
        output = ROOT / 'bin/test/fever-queue.exe'
        output.parent.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, PATH=str(Path(compiler).parent) + os.pathsep + os.environ.get('PATH', ''))
        compiled = subprocess.run([compiler, '-std=c++20', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
                                   str(ROOT / 'core/dropset.cpp'), str(ROOT / 'core/fever_queue.cpp'),
                                   str(ROOT / 'test/fever_queue_test.cc'), '-o', str(output)],
                                  env=environment, capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + compiled.stderr)
        cls.native = subprocess.run([str(output)], env=environment, capture_output=True, text=True, timeout=30)
        if cls.native.returncode:
            raise RuntimeError(cls.native.stdout + cls.native.stderr)
        cls.rows = [line.split('\t') for line in cls.native.stdout.splitlines()]
        data = json.loads((ROOT / 'data/fever/dropsets.json').read_text(encoding='utf-8'))
        cls.patterns = {c['id']: c['pattern'] for c in data['characters']}

    def test_native_contracts(self):
        self.assertIn('checks passed', self.native.stderr)

    def test_queues_match_independent_model(self):
        kinds = Counter()
        for kind, ident, key, start, pieces in self.rows:
            pieces = pieces.split(' ')
            pattern = self.patterns[ident].replace('*', '0')
            make = real if kind == 'real' else virtual
            with self.subTest(kind=kind, character=ident, key=key, start=start):
                self.assertEqual(pieces, make(pattern, int(key), int(start), len(pieces)))
            kinds[kind] += 1
        self.assertEqual(kinds, {'real': 26 * 5 * 4, 'virtual': 26 * 6 * 3})

    def test_color_constraints_and_spread(self):
        for kind, _, _, _, pieces in self.rows:
            for piece in pieces.split(' '):
                shape, cells = piece.split(':')
                self.assertTrue(set(cells) <= set(COLORS))
                if shape == '4':
                    self.assertEqual(len(set(cells)), 2)
                if kind == 'virtual':
                    self.assertTrue(shape == '0' or len(set(cells)) == 2)
        # The native rows reuse five seeds, so the spread is measured on the model
        # they were just matched against: every color near 1/4, same-color triples
        # near 1/4, each ordered color pair of a quad near 1/12.
        colors = Counter()
        triples = Counter()
        quads = Counter()
        for seed in range(1000, 3000):
            for piece in real(self.patterns['raffina'], seed, 0, 32):
                shape, cells = piece.split(':')
                colors.update(cells if shape in '20' else '')
                if shape == '3':
                    triples[len(set(cells)) == 1] += 1
                if shape == '4':
                    quads[cells[1:3]] += 1
        total = sum(colors.values())
        for color in COLORS:
            self.assertAlmostEqual(colors[color] / total, 0.25, delta=0.01)
        self.assertAlmostEqual(triples[True] / sum(triples.values()), 0.25, delta=0.02)
        self.assertEqual(len(quads), 12)
        for count in quads.values():
            self.assertAlmostEqual(count / sum(quads.values()), 1 / 12, delta=0.02)


if __name__ == '__main__':
    unittest.main(verbosity=2)
