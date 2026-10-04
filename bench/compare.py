#!/usr/bin/env python3
"""Compare two versions of the AI played by `bench` on the same seeds (solo, build the biggest chain).

usage: compare.py -o out_dir A=out_a.tsv,fields_a.txt B=out_b.tsv,fields_b.txt

Prints the statistics of both versions and writes, for every seed, a PNG with the chain of A on the
left and the chain of B on the right (numbers show the link a puyop pops in), plus overview.png with
the seeds where the two differ most and index.html with all of them.
Needs Pillow and ../pvp/chains.py.
"""
import argparse
import html
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pvp'))
import chains  # noqa: E402
from PIL import Image  # noqa: E402


def load_tsv(path):
    games = {}
    with open(path) as f:
        for line in f:
            p = line.rstrip('\r\n').split('\t')
            if len(p) < 9:
                continue
            # Old files have 9 columns, new ones 15: count_fire popped leftover excess max_link wasted
            p += ['0'] * (15 - len(p))
            games[int(p[0])] = dict(result=p[1], score=int(p[2]), best=int(p[3]), best_chain=int(p[4]),
                                    moves=int(p[5]), frames=int(p[6]), ms=int(p[7]), ms_max=int(p[8]),
                                    count_fire=int(p[9]), popped=int(p[10]), leftover=int(p[11]),
                                    excess=int(p[12]), max_link=int(p[13]), wasted=int(p[14]))
    return games


def load_fields(path):
    fields = {}
    with open(path) as f:
        lines = [line.rstrip('\n') for line in f]
    i = 0
    while i < len(lines):
        if lines[i].startswith('# seed '):
            fields[int(lines[i].split()[2])] = lines[i + 1:i + 15]
            i += 15
        else:
            i += 1
    return fields


def summary(name, games):
    fired = [g for g in games.values() if g['result'] == 'fired']
    n = len(games)
    print(f'{name}: {n} games')
    print(f'  fired {len(fired)}  dead {sum(g["result"] == "dead" for g in games.values())}  '
          f'nomove {sum(g["result"] == "nomove" for g in games.values())}  '
          f'timeout {sum(g["result"] == "timeout" for g in games.values())}')
    if fired:
        print(f'  fired score: mean {statistics.mean(g["score"] for g in fired):,.0f}  '
              f'median {statistics.median(g["score"] for g in fired):,.0f}  '
              f'max {max(g["score"] for g in fired):,}')
        print(f'  fired moves: mean {statistics.mean(g["moves"] for g in fired):.1f}  '
              f'frames: mean {statistics.mean(g["frames"] for g in fired):.0f}')
        # Chain efficiency (needs the 15-column format, 0 in older files)
        per_link = [g['popped'] / g['best_chain'] for g in fired if g['best_chain'] > 0]
        print(f'  puyos at fire: mean {statistics.mean(g["count_fire"] for g in fired):.1f}  '
              f'popped: mean {statistics.mean(g["popped"] for g in fired):.1f}  '
              f'leftover: mean {statistics.mean(g["leftover"] for g in fired):.1f}  '
              f'excess: mean {statistics.mean(g["excess"] for g in fired):.1f}')
        print(f'  popped per link: mean {statistics.mean(per_link) if per_link else 0:.2f}  '
              f'wasted before fire: mean {statistics.mean(g["wasted"] for g in fired):.1f}')
        print(f'  score >= 130000: {sum(g["score"] >= 130000 for g in fired)}  '
              f'>= 150000: {sum(g["score"] >= 150000 for g in fired)}')
    print(f'  score per game (0 when not fired): mean {statistics.mean(g["score"] for g in games.values()):,.0f}')
    print(f'  longest search: {max(g["ms_max"] for g in games.values())} ms, '
          f'mean game time {statistics.mean(g["ms"] for g in games.values()) / 1000:.1f} s')


def render(fields, seed, game, title):
    rows = fields[seed]
    grid = chains.parse_field(rows)
    order, links = chains.simulate(grid)
    result = game['result']
    sub = (f'{result}  {links} chain  {game["score"]:,} pts  {game["moves"]} moves' if result == 'fired'
           else f'{result}  {game["moves"]} moves  (last position)')
    path = os.path.join(os.environ.get('TMP_PNG', '.'), 'x.png')
    chains.draw(grid, order if result == 'fired' else {}, set(), title, sub, path)
    img = Image.open(path).copy()
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('a', help='NAME=out.tsv,fields.txt')
    ap.add_argument('b', help='NAME=out.tsv,fields.txt')
    args = ap.parse_args()

    sides = []
    for item in (args.a, args.b):
        name, _, files = item.partition('=')
        tsv, fields = files.split(',')
        sides.append((name, load_tsv(tsv), load_fields(fields)))

    os.makedirs(args.output, exist_ok=True)
    os.environ['TMP_PNG'] = args.output

    for name, games, _ in sides:
        summary(name, games)

    (na, ga, fa), (nb, gb, fb) = sides
    seeds = sorted(set(ga) & set(gb))

    wins_a = sum(ga[s]['score'] > gb[s]['score'] for s in seeds)
    wins_b = sum(gb[s]['score'] > ga[s]['score'] for s in seeds)
    print(f'\nhigher score on the same seed: {na} {wins_a}, {nb} {wins_b}, tie {len(seeds) - wins_a - wins_b}')

    images = {}
    for s in seeds:
        left = render(fa, s, ga[s], f'seed {s}  {na}')
        right = render(fb, s, gb[s], f'seed {s}  {nb}')
        img = Image.new('RGB', (left.width + right.width + 20, max(left.height, right.height)), (255, 255, 255))
        img.paste(left, (0, 0))
        img.paste(right, (left.width + 20, 0))
        name = f'seed{s:03d}.png'
        img.save(os.path.join(args.output, name))
        images[s] = img

    os.remove(os.path.join(args.output, 'x.png'))

    # Overview of the seeds where the scores differ most, 3 in favor of each side
    diff = sorted((ga[s]['score'] - gb[s]['score'], s) for s in seeds)
    pick = [s for _, s in diff[-3:][::-1]] + [s for _, s in diff[:3]]
    ims = [images[s] for s in pick]
    w, h = ims[0].size
    sheet = Image.new('RGB', (w * 3 + 40, h * 2 + 20), (255, 255, 255))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % 3) * (w + 20), (i // 3) * (h + 20)))
    sheet.save(os.path.join(args.output, 'overview.png'))
    print('overview seeds (top row favors %s, bottom row %s): %s' % (na, nb, pick))

    with open(os.path.join(args.output, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('<!doctype html><meta charset="utf-8"><title>Solo chains</title>\n')
        f.write('<style>body{font-family:sans-serif;margin:20px}.g{display:inline-block;margin:8px;vertical-align:top}'
                'img{display:block;border:1px solid #ccc}</style>\n')
        f.write(f'<h1>Same queue: {html.escape(na)} (left) vs {html.escape(nb)} (right)</h1>\n')
        for s in seeds:
            f.write(f'<div class="g"><img src="seed{s:03d}.png"></div>\n')


if __name__ == '__main__':
    main()
