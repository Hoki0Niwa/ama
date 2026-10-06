#!/usr/bin/env python3
"""Compare two versions of the AI played by `bench` on the same seeds (solo, build the biggest chain).

usage: compare.py -o out_dir A=out_a.tsv,fields_a.txt B=out_b.tsv,fields_b.txt
       compare.py --summary-only A=out_a.tsv B=out_b.tsv

Prints the statistics of both versions and writes, for every seed, a PNG with the chain of A on the
left and the chain of B on the right (numbers show the link a puyop pops in), plus overview.png with
the seeds where the two differ most and index.html with all of them.
Rendering needs Pillow and ../pvp/chains.py; --summary-only needs neither.
"""
import argparse
import html
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pvp'))


def load_tsv(path):
    games = {}
    with open(path) as f:
        for line in f:
            p = line.rstrip('\r\n').split('\t')
            if len(p) < 9:
                continue
            # Legacy files have 9 or 15 columns. The 19-column format also records
            # small clears and the first opportunity to fire 130k. Missing diagnostics
            # stay None so old measurements are not reported as zero small clears.
            efficiency_recorded = len(p) >= 15
            p += ['0'] * (15 - len(p))
            games[int(p[0])] = dict(result=p[1], score=int(p[2]), best=int(p[3]), best_chain=int(p[4]),
                                    moves=int(p[5]), frames=int(p[6]), ms=int(p[7]), ms_max=int(p[8]),
                                    count_fire=int(p[9]), popped=int(p[10]), leftover=int(p[11]),
                                    excess=int(p[12]), max_link=int(p[13]), wasted=int(p[14]),
                                    efficiency_recorded=efficiency_recorded,
                                    **{key: int(p[i]) if i < len(p) else None
                                       for i, key in enumerate(('small_clear_moves', 'single_clear_moves',
                                                                'first_130k_move', 'fire_delay_130k'), 15)})
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
    if not n:
        print('  no usable game rows (expected TSV rows with at least 9 columns)')
        return
    print(f'  fired {len(fired)}  dead {sum(g["result"] == "dead" for g in games.values())}  '
          f'nomove {sum(g["result"] == "nomove" for g in games.values())}  '
          f'timeout {sum(g["result"] == "timeout" for g in games.values())}')
    if fired:
        print(f'  fired score: mean {statistics.mean(g["score"] for g in fired):,.0f}  '
              f'median {statistics.median(g["score"] for g in fired):,.0f}  '
              f'max {max(g["score"] for g in fired):,}')
        print(f'  fired moves: mean {statistics.mean(g["moves"] for g in fired):.1f}  '
              f'frames: mean {statistics.mean(g["frames"] for g in fired):.0f}')
        measured_efficiency = [g for g in fired if g.get('efficiency_recorded', True)]
        if measured_efficiency:
            per_link = [g['popped'] / g['best_chain'] for g in measured_efficiency if g['best_chain'] > 0]
            print(f'  puyos at fire: mean {statistics.mean(g["count_fire"] for g in measured_efficiency):.1f}  '
                  f'popped: mean {statistics.mean(g["popped"] for g in measured_efficiency):.1f}  '
                  f'leftover: mean {statistics.mean(g["leftover"] for g in measured_efficiency):.1f}  '
                  f'excess: mean {statistics.mean(g["excess"] for g in measured_efficiency):.1f}')
            per_link_mean = f'{statistics.mean(per_link):.2f}' if per_link else 'unavailable'
            print(f'  popped per link: mean {per_link_mean}  '
                  f'wasted before fire: mean {statistics.mean(g["wasted"] for g in measured_efficiency):.1f}  '
                  f'({len(measured_efficiency)}/{len(fired)} fired games recorded)')
        else:
            print('  chain efficiency: not recorded in this TSV')
        print(f'  score >= 130000: {sum(g["score"] >= 130000 for g in fired)}  '
              f'>= 150000: {sum(g["score"] >= 150000 for g in fired)}')
    measured = [g for g in games.values() if g.get('small_clear_moves') is not None
                and g.get('single_clear_moves') is not None]
    if measured:
        print(f'  small clears per game: mean {statistics.mean(g["small_clear_moves"] for g in measured):.1f}  '
              f'single-link clears: mean {statistics.mean(g["single_clear_moves"] for g in measured):.1f}  '
              f'({len(measured)}/{n} games recorded, ending chain excluded)')
        measured_fired = [g for g in measured if g['result'] == 'fired']
        if measured_fired:
            print(f'  small clears before fire: mean {statistics.mean(g["small_clear_moves"] for g in measured_fired):.1f}  '
                  f'single-link clears: mean {statistics.mean(g["single_clear_moves"] for g in measured_fired):.1f}')
    else:
        print('  small clears: not recorded in this TSV')
    observed = [g for g in games.values() if g.get('first_130k_move') is not None]
    if observed:
        ready = [g for g in observed if g['first_130k_move'] > 0]
        print(f'  130000 fireable: {len(ready)}/{len(observed)} games recorded')
        if ready:
            print(f'  first 130000 fireable move: mean {statistics.mean(g["first_130k_move"] for g in ready):.1f}')
        delayed = [g for g in observed if g.get('fire_delay_130k') is not None and g['fire_delay_130k'] >= 0]
        if delayed:
            print(f'  moves from first 130000 opportunity to fire: mean '
                  f'{statistics.mean(g["fire_delay_130k"] for g in delayed):.1f}  '
                  f'max {max(g["fire_delay_130k"] for g in delayed)}  ({len(delayed)} fired games)')
        else:
            print('  fire delay: no completed fires with a recorded 130000 opportunity')
    else:
        print('  130000 opportunity and fire delay: not recorded in this TSV')
    print(f'  score per game (0 when not fired): mean {statistics.mean(g["score"] for g in games.values()):,.0f}')
    print(f'  longest search: {max(g["ms_max"] for g in games.values())} ms, '
          f'mean game time {statistics.mean(g["ms"] for g in games.values()) / 1000:.1f} s')


def render(fields, seed, game, title):
    import chains
    from PIL import Image

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
    ap.add_argument('-o', '--output', help='required when rendering images')
    ap.add_argument('--summary-only', action='store_true', help='compare TSV statistics without images or field files')
    ap.add_argument('a', help='NAME=out.tsv,fields.txt (NAME=out.tsv with --summary-only)')
    ap.add_argument('b', help='NAME=out.tsv,fields.txt (NAME=out.tsv with --summary-only)')
    args = ap.parse_args()
    if not args.summary_only and not args.output:
        ap.error('-o/--output is required unless --summary-only is set')

    sides = []
    for item in (args.a, args.b):
        name, separator, files = item.partition('=')
        tsv, _, fields = files.partition(',')
        if not separator or not name or not tsv:
            ap.error(f'invalid input {item!r}; expected NAME=out.tsv')
        if not args.summary_only and not fields:
            ap.error(f'field file required for {name}; expected NAME=out.tsv,fields.txt')
        sides.append((name, load_tsv(tsv), None if args.summary_only else load_fields(fields)))

    for name, games, _ in sides:
        summary(name, games)

    (na, ga, fa), (nb, gb, fb) = sides
    seeds = sorted(set(ga) & set(gb))
    if not seeds:
        print('\nno shared seeds; pairwise comparison and images are unavailable')
        return

    wins_a = sum(ga[s]['score'] > gb[s]['score'] for s in seeds)
    wins_b = sum(gb[s]['score'] > ga[s]['score'] for s in seeds)
    print(f'\nhigher score on the same seed: {na} {wins_a}, {nb} {wins_b}, tie {len(seeds) - wins_a - wins_b}')
    if args.summary_only:
        return

    for name, _, fields in sides:
        missing = [s for s in seeds if s not in fields]
        if missing:
            ap.error(f'{name}: field snapshots missing for seeds {missing[:5]}')

    from PIL import Image

    os.makedirs(args.output, exist_ok=True)
    os.environ['TMP_PNG'] = args.output

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
