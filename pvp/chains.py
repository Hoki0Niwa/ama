#!/usr/bin/env python3
"""Draw the chains of a PVP match from the move log written by `pvp --log moves.jsonl`.

For every game it takes the biggest chain of each side, rebuilds the field with the firing pair
placed and draws it as a PNG. Every puyo that pops is numbered with the link it pops in, and the
pair that triggers the chain is outlined. It also writes index.html with a table of all the
images and a puyop.com link for each of them.

usage: chains.py moves.jsonl -o out_dir [--names A=branch B=main] [--min-chain 1]

Both sides of a game get the same queue, so the images of A and B of the same game are also put
side by side in out_dir/pairs (one PNG per game, left A, right B) and in out_dir/pairs.html.

The chain count of every chain is recomputed here and checked against the log. Needs Pillow.
"""
import argparse
import html
import json
import os
from PIL import Image, ImageDraw, ImageFont

COLORS = {
    'R': (224, 60, 49),
    'Y': (242, 194, 48),
    'G': (60, 169, 74),
    'B': (58, 123, 213),
    '#': (150, 150, 150),
}

CELL = 40
PAD = 14
HEAD = 58
COLS = 6
ROWS = 13        # rows 1 to 13, the 13th is the hidden row
VISIBLE_ROWS = 12


def load(path):
    """Returns {(game_seed, player): {move: request}} and the list of chain events."""
    requests = {}
    chains = []

    with open(path) as f:
        for line in f:
            js = json.loads(line)
            key = (js['game_seed'], js['player'])

            if 'reply' in js:
                requests.setdefault(key, {})[js['move']] = js
            elif 'chain' in js:
                chains.append(js)

    return requests, chains


def parse_field(rows):
    """rows[0] is the 14th row (occupancy only). Returns grid[y][x], y = 0 is the bottom row."""
    grid = [[None] * COLS for _ in range(ROWS)]

    for i, row in enumerate(rows[1:]):
        y = ROWS - 1 - i
        for x, ch in enumerate(row):
            if ch != '.':
                grid[y][x] = ch

    return grid


def drop(grid, x, ch):
    for y in range(ROWS):
        if grid[y][x] is None:
            grid[y][x] = ch
            return (x, y)
    return None  # falls off the top


def place(grid, pair, x, r):
    first, second = pair[0], pair[1]
    placed = []

    if r == 'U':
        order = [(x, first), (x, second)]
    elif r == 'D':
        order = [(x, second), (x, first)]
    elif r == 'R':
        order = [(x, first), (x + 1, second)]
    else:
        order = [(x, first), (x - 1, second)]

    for cx, ch in order:
        pos = drop(grid, cx, ch)
        if pos is not None:
            placed.append(pos)

    return placed


def simulate(grid):
    """Pops the field. Returns the link number of every cell that pops, and the chain count."""
    g = [row[:] for row in grid]
    order = {}
    links = 0
    # Where each cell of the working grid started, so the numbers follow the puyos while they fall
    origin = {(x, y): (x, y) for y in range(ROWS) for x in range(COLS) if g[y][x] is not None}

    while True:
        seen = set()
        pops = set()

        for y in range(VISIBLE_ROWS):
            for x in range(COLS):
                ch = g[y][x]
                if ch is None or ch == '#' or (x, y) in seen:
                    continue

                group = [(x, y)]
                seen.add((x, y))
                stack = [(x, y)]

                while stack:
                    cx, cy = stack.pop()
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < COLS and 0 <= ny < VISIBLE_ROWS and (nx, ny) not in seen and g[ny][nx] == ch:
                            seen.add((nx, ny))
                            group.append((nx, ny))
                            stack.append((nx, ny))

                if len(group) >= 4:
                    pops.update(group)

        if not pops:
            break

        links += 1

        # Garbage next to a popped puyo pops too
        for x, y in list(pops):
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < COLS and 0 <= ny < VISIBLE_ROWS and g[ny][nx] == '#':
                    pops.add((nx, ny))

        for p in pops:
            order[origin[p]] = links
            g[p[1]][p[0]] = None
            del origin[p]

        # Gravity
        for x in range(COLS):
            column = [(g[y][x], origin.get((x, y))) for y in range(ROWS) if g[y][x] is not None]
            for y in range(ROWS):
                origin.pop((x, y), None)
                g[y][x] = None
            for y, (ch, src) in enumerate(column):
                g[y][x] = ch
                origin[(x, y)] = src

    return order, links


# puyop.com encoding, same as puyop/encode.h but with whole rows
PUYOP = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ[]"
FIELD_ID = {None: 0, 'R': 1, 'G': 2, 'B': 3, 'Y': 4, '#': 6}
PAIR_ID = {'R': 0, 'G': 1, 'B': 2, 'Y': 3}
DIR_ID = {'U': 0, 'R': 1, 'D': 2, 'L': 3}


def puyop_url(grid, pair, x, r):
    text = ''
    started = False

    for y in range(ROWS - 1, -1, -1):
        row = ''
        for cx in range(0, COLS, 2):
            row += PUYOP[FIELD_ID[grid[y][cx]] * 8 + FIELD_ID[grid[y][cx + 1]]]
        if not started and set(row) == {'0'}:
            continue
        started = True
        text += row

    code = (PAIR_ID[pair[0]] * 5 + PAIR_ID[pair[1]]) | (((x + 1) << 2) + DIR_ID[r]) << 7
    control = PUYOP[code & 0x3F] + PUYOP[(code >> 6) & 0x3F]

    return f'http://www.puyop.com/s/{text}_{control}'


def font(size):
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def draw(grid, order, placed, title, subtitle, path):
    width = COLS * CELL + 2 * PAD
    height = HEAD + ROWS * CELL + PAD
    img = Image.new('RGB', (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)

    d.text((PAD, 8), title, fill=(20, 20, 20), font=font(16))
    d.text((PAD, 31), subtitle, fill=(90, 90, 90), font=font(13))

    top = HEAD
    d.rectangle((PAD, top, PAD + COLS * CELL, top + ROWS * CELL), fill=(244, 244, 244), outline=(190, 190, 190))
    d.rectangle((PAD, top, PAD + COLS * CELL, top + CELL), fill=(226, 226, 226))
    d.line((PAD, top + CELL, PAD + COLS * CELL, top + CELL), fill=(170, 170, 170))

    for y in range(ROWS):
        for x in range(COLS):
            ch = grid[y][x]
            if ch is None:
                continue

            px = PAD + x * CELL
            py = top + (ROWS - 1 - y) * CELL
            box = (px + 3, py + 3, px + CELL - 3, py + CELL - 3)
            d.ellipse(box, fill=COLORS[ch])

            if (x, y) in placed:
                d.ellipse((px + 1, py + 1, px + CELL - 1, py + CELL - 1), outline=(0, 0, 0), width=3)

            link = order.get((x, y))
            if link is not None:
                d.text((px + CELL / 2, py + CELL / 2), str(link), fill=(255, 255, 255), font=font(18),
                       anchor='mm', stroke_width=2, stroke_fill=(0, 0, 0))

    img.save(path)


def side_by_side(left_path, right_path, out_path):
    left = Image.open(left_path)
    right = Image.open(right_path)
    img = Image.new('RGB', (left.width + right.width + 20, max(left.height, right.height)), (255, 255, 255))
    img.paste(left, (0, 0))
    img.paste(right, (left.width + 20, 0))
    ImageDraw.Draw(img).line((left.width + 10, 0, left.width + 10, img.height), fill=(200, 200, 200))
    img.save(out_path)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('log')
    ap.add_argument('-o', '--output', required=True, help='output directory')
    ap.add_argument('--names', nargs='*', default=[], help='A=name B=name, labels for the two sides')
    ap.add_argument('--min-chain', type=int, default=1, help='skip chains shorter than this')
    args = ap.parse_args()

    names = {'A': 'A', 'B': 'B'}
    for item in args.names:
        k, _, v = item.partition('=')
        names[k] = v

    os.makedirs(args.output, exist_ok=True)
    requests, chains = load(args.log)

    best = {}
    for c in chains:
        key = (c['game_seed'], c['player'])
        if key not in best or c['score'] > best[key]['score']:
            best[key] = c

    rows = []
    bad = 0

    for (seed, player), c in sorted(best.items()):
        if c['chain'] < args.min_chain:
            continue

        req = requests[(seed, player)][c['move']]
        grid = parse_field(req['self']['field'])
        before = [row[:] for row in grid]
        pair = req['self']['queue'][0]
        x, r = req['reply']['x'], req['reply']['r']

        placed = place(grid, pair, x, r)
        order, links = simulate(grid)

        if links != c['chain']:
            bad += 1
            print(f'mismatch: seed {seed} {player} move {c["move"]}: rebuilt {links} links, log says {c["chain"]}')

        name = f'game{seed:03d}_{player}.png'
        title = f'Game {seed}  {names[player]}  move {c["move"]}'
        sub = f'{c["chain"]} chain  {c["score"]:,} pts   pair {pair} x={x} {r}'
        draw(grid, order, set(placed), title, sub, os.path.join(args.output, name))

        rows.append((seed, player, c, name, puyop_url(before, pair, x, r)))

    with open(os.path.join(args.output, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('<!doctype html><meta charset="utf-8"><title>PVP chains</title>\n')
        f.write('<style>body{font-family:sans-serif;margin:20px}.g{display:inline-block;margin:8px;vertical-align:top}'
                'img{display:block;border:1px solid #ccc}</style>\n')
        f.write(f'<h1>Biggest chain per game and side</h1>\n<p>A = {html.escape(names["A"])}, '
                f'B = {html.escape(names["B"])}. Numbers show the link a puyo pops in, the outlined pair fires the chain.</p>\n')

        for seed, player, c, name, url in rows:
            f.write(f'<div class="g"><img src="{name}"><a href="{html.escape(url)}">puyop</a></div>\n')

    # Puts the 2 sides of every game next to each other
    pairs_dir = os.path.join(args.output, 'pairs')
    os.makedirs(pairs_dir, exist_ok=True)
    by_game = {}
    for seed, player, c, name, url in rows:
        by_game.setdefault(seed, {})[player] = (c, name)

    games = []
    for seed, sides in sorted(by_game.items()):
        if 'A' not in sides or 'B' not in sides:
            continue
        out = f'game{seed:03d}.png'
        side_by_side(os.path.join(args.output, sides['A'][1]), os.path.join(args.output, sides['B'][1]),
                     os.path.join(pairs_dir, out))
        games.append((seed, sides['A'][0], sides['B'][0], out))

    with open(os.path.join(args.output, 'pairs.html'), 'w', encoding='utf-8') as f:
        f.write('<!doctype html><meta charset="utf-8"><title>PVP chains, same queue</title>\n')
        f.write('<style>body{font-family:sans-serif;margin:20px}.g{display:inline-block;margin:8px;vertical-align:top}'
                'img{display:block;border:1px solid #ccc}</style>\n')
        f.write(f'<h1>Same queue: {html.escape(names["A"])} (left) vs {html.escape(names["B"])} (right)</h1>\n')
        for seed, ca, cb, out in games:
            f.write(f'<div class="g"><img src="pairs/{out}"></div>\n')

    print(f'{len(games)} side by side images in {pairs_dir}')
    print(f'{len(rows)} images in {args.output}, {bad} chain count mismatches')


if __name__ == '__main__':
    main()
