#!/usr/bin/env python3
"""Render field snapshots written by `bench` as an SVG image.

Each row of the image is one snapshot file (one set of weights), each column is one seed,
so the shapes built from the same queue with different weights line up vertically.

usage: render.py -o out.svg NAME=snapshot.txt [NAME=snapshot.txt ...] [--seeds 1-12]

The SVG needs no extra Python packages. Convert it to PNG with any SVG tool
(a browser, rsvg-convert, Inkscape, ...).
"""
import argparse
import html

COLORS = {
    'R': '#e03c31',
    'Y': '#f2c230',
    'G': '#3ca94a',
    'B': '#3a7bd5',
    '#': '#8a8a8a',
}

CELL = 18          # cell size in px
GAP = 1            # gap between cells
PAD = 10           # padding around a field
LABEL_H = 34       # space above a field for its label
ROW_LABEL_W = 110  # space on the left for the weight set name
COLS = 6
ROWS = 14          # 14th row at the top, 1st row at the bottom


def load(path):
    """Returns {seed: (result, score, moves, rows)} where rows[0] is the 14th row."""
    games = {}
    with open(path) as f:
        lines = [line.rstrip('\n') for line in f]

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith('# seed '):
            i += 1
            continue

        parts = line.split()
        seed = int(parts[2])
        result = parts[4]
        score = int(parts[6])
        moves = int(parts[8])
        rows = lines[i + 1:i + 1 + ROWS]
        games[seed] = (result, score, moves, rows)
        i += 1 + ROWS

    return games


def parse_seeds(text):
    seeds = []
    for part in text.split(','):
        if '-' in part:
            a, b = part.split('-')
            seeds.extend(range(int(a), int(b) + 1))
        else:
            seeds.append(int(part))
    return seeds


def field_svg(x0, y0, game):
    out = []
    result, score, moves, rows = game
    label = f'{result} {score:,}' if result == 'fired' else result
    out.append(f'<text x="{x0}" y="{y0 + 14}" font-size="12" fill="#222">{html.escape(label)}</text>')
    out.append(f'<text x="{x0}" y="{y0 + 28}" font-size="11" fill="#666">{moves} moves</text>')

    top = y0 + LABEL_H
    width = COLS * (CELL + GAP) + GAP
    height = ROWS * (CELL + GAP) + GAP
    out.append(f'<rect x="{x0}" y="{top}" width="{width}" height="{height}" fill="#f3f3f3" stroke="#bbb"/>')

    # Marks the 14th row (hidden in the real game) and the 12th row (visible top)
    out.append(f'<rect x="{x0}" y="{top}" width="{width}" height="{CELL + GAP}" fill="#e4e4e4"/>')
    y12 = top + 2 * (CELL + GAP)
    out.append(f'<line x1="{x0}" y1="{y12}" x2="{x0 + width}" y2="{y12}" stroke="#bbb" stroke-dasharray="3,3"/>')

    for r, row in enumerate(rows):
        for c, ch in enumerate(row[:COLS]):
            color = COLORS.get(ch)
            if color is None:
                continue
            cx = x0 + GAP + c * (CELL + GAP) + CELL / 2
            cy = top + GAP + r * (CELL + GAP) + CELL / 2
            if r == 0:
                # The 14th row only records occupancy, not the color
                out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{CELL / 2 - 2:.1f}" fill="none" stroke="#777" stroke-width="1.5"/>')
            else:
                out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{CELL / 2 - 1:.1f}" fill="{color}"/>')

    # Marks the death cell (3rd column, 12th row)
    cx = x0 + GAP + 2 * (CELL + GAP)
    cy = top + GAP + 2 * (CELL + GAP)
    out.append(f'<line x1="{cx + 4}" y1="{cy + 4}" x2="{cx + CELL - 4}" y2="{cy + CELL - 4}" stroke="#c99" stroke-width="1"/>')
    out.append(f'<line x1="{cx + CELL - 4}" y1="{cy + 4}" x2="{cx + 4}" y2="{cy + CELL - 4}" stroke="#c99" stroke-width="1"/>')

    return '\n'.join(out), width, height + LABEL_H


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sets', nargs='+', help='NAME=snapshot.txt, one per set of weights')
    ap.add_argument('-o', '--output', required=True, help='output .svg path')
    ap.add_argument('--seeds', help='seeds to show, e.g. 1-12 or 1,5,9 (default: all seeds of the first set)')
    ap.add_argument('--title', default='', help='title drawn at the top')
    args = ap.parse_args()

    sets = []
    for item in args.sets:
        name, _, path = item.rpartition('=')
        if not path:
            ap.error(f'expected NAME=path, got "{item}"')
        sets.append((name, load(path)))

    seeds = parse_seeds(args.seeds) if args.seeds else sorted(sets[0][1])

    field_w = COLS * (CELL + GAP) + GAP
    field_h = ROWS * (CELL + GAP) + GAP + LABEL_H
    col_w = field_w + 2 * PAD
    row_h = field_h + 2 * PAD
    title_h = 30 if args.title else 0
    header_h = 24
    width = ROW_LABEL_W + len(seeds) * col_w
    height = title_h + header_h + len(sets) * row_h

    body = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif">',
            f'<rect width="{width}" height="{height}" fill="white"/>']

    if args.title:
        body.append(f'<text x="{ROW_LABEL_W}" y="20" font-size="16" fill="#111">{html.escape(args.title)}</text>')

    for ci, seed in enumerate(seeds):
        x = ROW_LABEL_W + ci * col_w + PAD
        body.append(f'<text x="{x}" y="{title_h + 16}" font-size="12" fill="#444">seed {seed}</text>')

    for ri, (name, games) in enumerate(sets):
        y = title_h + header_h + ri * row_h + PAD
        body.append(f'<text x="8" y="{y + LABEL_H + 60}" font-size="13" fill="#111">{html.escape(name)}</text>')
        for ci, seed in enumerate(seeds):
            game = games.get(seed)
            x = ROW_LABEL_W + ci * col_w + PAD
            if game is None:
                body.append(f'<text x="{x}" y="{y + 14}" font-size="12" fill="#999">no data</text>')
                continue
            svg, _, _ = field_svg(x, y, game)
            body.append(svg)

    body.append('</svg>')

    with open(args.output, 'w') as f:
        f.write('\n'.join(body) + '\n')


if __name__ == '__main__':
    main()
