"""Fever engine protocol (T5) and continuous solo play through bench_fever (T4).

Build first: build.ps1 -Target fever; build.ps1 -Target bench_fever
"""
from collections import Counter
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'test'))
from test_fever_queue import real  # independent color model, checked against the generator there

ENGINE = Path(os.environ.get('AMA_TEST_FEVER_ENGINE', ROOT / 'bin/fever/fever.exe'))
BENCH = Path(os.environ.get('AMA_TEST_FEVER_BENCH', ROOT / 'bin/bench_fever/bench_fever.exe'))
PATTERNS = {c['id']: c['pattern'] for c in
            json.loads((ROOT / 'data/fever/dropsets.json').read_text(encoding='utf-8'))['characters']}
EMPTY = ['......'] * 14
WIDTH, DEPTH, TRIGGER = 40, 8, 13


def request(queue, index=0, field=EMPTY, character='raffina', **extra):
    return dict(rule='fever', character=character, dropset_index=index, solo=True,
                self=dict(field=field, queue=queue), beam_width=WIDTH, beam_depth=DEPTH,
                trigger=TRIGGER, **extra)


def replies(*requests):
    result = subprocess.run([str(ENGINE), str(ROOT / 'config.json')],
                            input=''.join(json.dumps(r) + '\n' for r in requests),
                            capture_output=True, text=True, timeout=300, check=True)
    output = [json.loads(line) for line in result.stdout.splitlines() if line]
    if len(output) != len(requests):
        raise AssertionError(f'Expected {len(requests)} replies, got {len(output)}')
    return output


def pieces(character, seed, count):
    """The model's queue in the engine's text form."""
    result = []
    for piece in real(PATTERNS[character].replace('*', '0'), seed, 0, count):
        shape, cells = piece.split(':')
        if shape == '3':
            shape = 'L' if cells[0] == cells[1] else 'J'
        result.append(shape + ':' + cells)
    return result


def resolve(rows):
    """Scalar chain resolution: 14 rows, 14th first. The 13th row never pops."""
    grid = [list(row) for row in rows]
    chain = 0
    while True:
        seen = set()
        popped = set()
        for y in range(2, 14):
            for x in range(6):
                if grid[y][x] not in 'RYGB' or (x, y) in seen:
                    continue
                group, stack = set(), [(x, y)]
                while stack:
                    cx, cy = stack.pop()
                    if (cx, cy) in group or not (0 <= cx < 6 and 2 <= cy < 14) or grid[cy][cx] != grid[y][x]:
                        continue
                    group.add((cx, cy))
                    stack += [(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)]
                seen |= group
                if len(group) >= 4:
                    popped |= group
        if not popped:
            return chain, [''.join(row) for row in grid]
        chain += 1
        for x, y in popped:
            grid[y][x] = '.'
        for x in range(6):
            column = [grid[y][x] for y in range(13, 0, -1) if grid[y][x] != '.']
            for i in range(13):
                grid[13 - i][x] = column[i] if i < len(column) else '.'


def cells(rows):
    return Counter(c for row in rows for c in row if c != '.')


class FeverProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for exe in (ENGINE, BENCH):
            if not exe.is_file():
                raise RuntimeError(f'Build the fever targets first: {exe}')

    def test_refusals_keep_the_process_alive(self):
        good = request(['2:RG', '2:BY', 'L:RRG'])
        tsu = dict(good, rule='tsu')
        no_rule = {k: v for k, v in good.items() if k != 'rule'}
        versus = dict(good, solo=False)
        nobody = dict(good, character='nobody')
        wrong_shape = request(['2:RG', '2:BY', '2:RR'])          # move 2 of raffina is a vertical triple
        wrong_triple = request(['2:RG', '2:BY', 'J:RGR'])
        wrong_index = request(['2:RG', '2:BY', 'L:RRG'], index=1)
        bad_piece = request(['2:RG', '2:B#', 'L:RRG'])
        one_color_quad = request(['4:RRRR', '2:RG', '2:BY'], index=15)
        floating = request(['2:RG', '2:BY', 'L:RRG'], field=['......'] * 12 + ['R.....', '......'])
        output = replies(tsu, no_rule, versus, nobody, wrong_shape, wrong_triple, wrong_index, bad_piece,
                         one_color_quad, floating, 'not a request', good)
        for reply in output[:-1]:
            self.assertEqual(list(reply), ['error'])
        self.assertNotIn('error', output[-1])

    def test_every_shape_gets_a_legal_deterministic_move(self):
        queue = pieces('raffina', 7, 19)
        requests = [request(queue[i:i + 3], index=i, include_next=True) for i in range(16)]
        first, second = replies(*requests), replies(*requests)
        shapes = set()
        for i, (reply, again) in enumerate(zip(first, second)):
            with self.subTest(move=i):
                self.assertNotIn('error', reply)
                shape = queue[i][0]
                shapes.add(shape)
                self.assertEqual(reply['shape'], shape)
                self.assertIn(reply['r'], 'URDL')
                self.assertIn(reply['x'], range(6) if shape == '2' else range(5))
                self.assertEqual((reply['x'], reply['r']), (again['x'], again['r']))
                self.assertTrue(reply['solo'])
                self.assertEqual(len(reply['next_field']), 14)
                placed = cells(reply['next_field'])
                if shape == '0':
                    # On an empty field the 4 cells of a big puyo land connected and pop
                    self.assertEqual(reply['color'], 'RYGB'['URDL'.index(reply['r'])])
                    self.assertEqual((reply['next_chain'], reply['next_all_clear']), (1, True))
                else:
                    self.assertNotIn('color', reply)
                    self.assertEqual(reply['next_chain'], 0)
                    self.assertEqual(placed, Counter(queue[i][2:]))
        self.assertEqual(shapes, set('2LJ40'))

    def test_fire_takes_the_chain_in_hand(self):
        field = ['......'] * 11 + ['R.....'] * 3
        build, fire = replies(request(['2:RB', '2:YY', 'L:GGY'], field=field, include_next=True),
                              request(['2:RB', '2:YY', 'L:GGY'], field=field, include_next=True, fire=True))
        self.assertTrue(fire['fire'])
        self.assertEqual((fire['chain'], fire['next_chain']), (1, 1))
        self.assertEqual(fire['eval'], fire['next_score'])
        self.assertEqual(cells(fire['next_field']), {'B': 1})
        self.assertFalse(build['fire'])
        # A big puyo fires by taking the color that pops
        big = request(['0:G', '2:RB', '2:YY'], index=5, field=field, include_next=True, fire=True)
        reply, = replies(big)
        self.assertEqual((reply['color'], reply['next_chain']), ('R', 1))
        self.assertTrue(reply['next_all_clear'])
        # Trigger 1: the policy fires without being asked
        reply, = replies(dict(request(['2:RB', '2:YY', 'L:GGY'], field=field), trigger=1))
        self.assertTrue(reply['fire'])

    def test_fever_death_columns(self):
        # 4th column full: dead under the fever rule even though the 3rd is open
        tall = ['......', '......'] + ['...G..', '...B..'] * 6
        reply, = replies(request(['2:RG', '2:BY', 'L:RRG'], field=tall))
        self.assertIn('error', reply)

    def test_continuous_play_is_legal_and_uses_visible_pieces_only(self):
        moves_max = 40
        environment = dict(os.environ, BEAM_WIDTH=str(WIDTH), BEAM_DEPTH=str(DEPTH),
                           BEAM_TRIGGER=str(TRIGGER), BENCH_GOAL='10')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            weights = directory / 'build.json'
            weights.write_text(json.dumps(json.loads((ROOT / 'config.json').read_text())['build']))
            for character in ('raffina', 'carbuncle', 'arle', 'draco'):
                subprocess.run([str(BENCH), str(weights), character, '1', '3', str(directory / 'out.tsv'),
                                str(moves_max), str(directory / 'snap.txt'), str(directory / 'moves.jsonl')],
                               env=environment, capture_output=True, text=True, timeout=600, check=True)
            rows = [line.split('\t') for line in (directory / 'out.tsv').read_text().splitlines()]
            log = [json.loads(line) for line in (directory / 'moves.jsonl').read_text().splitlines()]
            snapshot = (directory / 'snap.txt').read_text().splitlines()

        self.assertEqual(len(rows), 8)
        self.assertEqual(len(snapshot), 8 * 15)
        games = {}
        for entry in log:
            games.setdefault((entry['character'], entry['seed']), []).append(entry)
        probes = []
        shapes = set()
        for row in rows:
            character, seed, result, score, max_score, max_chain, moves = row[:7]
            dealt, discarded, small = map(int, row[10:13])
            game = games[(character, int(seed))]
            queue = pieces(character, int(seed), moves_max + 3)
            field = EMPTY
            with self.subTest(character=character, seed=seed):
                self.assertEqual(len(game), int(moves))
                self.assertIn(result, ('fired', 'dead', 'timeout', 'nomove'))
                for i, entry in enumerate(game):
                    piece = entry['piece']
                    shapes.add(piece[0])
                    # The piece played is the real queue's, not a virtual one
                    self.assertEqual((entry['move'], entry['dropset_index'], piece), (i + 1, i, queue[i]))
                    # The placement adds exactly the piece's cells, minus those discarded above the 13th row
                    added = cells(entry['placed']) - cells(field)
                    self.assertFalse(cells(field) - cells(entry['placed']))
                    self.assertEqual(sum(added.values()), len(piece[2:]) * (4 if piece[0] == '0' else 1)
                                     - entry['discarded'])
                    if piece[0] == '0':
                        self.assertLessEqual(set(added), {'RYGB'['URDL'.index(entry['r'])]})
                    else:
                        self.assertFalse(added - Counter(piece[2:]))
                    for old, new in zip(zip(*field[::-1]), zip(*entry['placed'][::-1])):
                        height = len(''.join(old).rstrip('.'))
                        self.assertEqual(old[:height], new[:height])
                        self.assertNotIn('.', ''.join(new).rstrip('.'))
                    # Independent chain resolution
                    chain, after = resolve(entry['placed'])
                    self.assertEqual((chain, after), (entry['chain'], entry['field']))
                    if entry['fire']:
                        self.assertEqual(entry['expected_chain'], chain)
                    dead = after[2][2] != '.' or after[2][3] != '.'
                    self.assertEqual(entry['dead'], dead)
                    self.assertEqual(dead or chain >= 10, i == len(game) - 1 and result in ('dead', 'fired'))
                    if i % 6 == 0:
                        probes.append((entry, request(queue[i:i + 3], index=i, field=field, character=character)))
                    field = after
                chains = [e['chain'] for e in game]
                self.assertEqual(int(max_chain), max(chains))
                self.assertEqual(small, sum(1 <= c <= 3 for c in chains))
                self.assertEqual(discarded, sum(e['discarded'] for e in game))
                self.assertEqual(dealt, sum(len(e['piece'][2:]) * (4 if e['piece'][0] == '0' else 1) for e in game))
                self.assertEqual(result == 'fired', chains[-1] >= 10)
                self.assertEqual(int(score) > 0, result == 'fired')
        self.assertEqual(shapes, set('2LJ40'))

        # The engine, given only the 3 visible pieces, plays the move bench_fever played
        for (entry, _), reply in zip(probes, replies(*[probe for _, probe in probes])):
            with self.subTest(character=entry['character'], seed=entry['seed'], move=entry['move']):
                self.assertEqual((reply['x'], reply['r'], reply['fire']), (entry['x'], entry['r'], entry['fire']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
