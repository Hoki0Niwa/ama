"""Draw exact board cells and clearly labelled inferred triple landings."""
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.worker import JsonProcess

FONT = 'C:/Windows/Fonts/meiryo.ttc'
COLORS = {'R': '#df3e51', 'Y': '#e6bd23', 'G': '#209f70', 'B': '#387ce1', '#': '#8b94a3'}


def landing(case, placement):
    x, r = placement
    cells = [(0, 0, case['piece'][2]), (0, -1, case['piece'][3]), (1, 0, case['piece'][4])]
    for _ in range(r):
        cells = [(-dy, dx, c) for dx, dy, c in cells]
    minimum = min(dx for dx, _, _ in cells)
    h = list(case['heights'])
    result = []
    for i in sorted(range(3), key=lambda i: cells[i][1], reverse=True):
        dx, _, c = cells[i]
        column = x + dx - minimum
        row = 13 - h[column]
        h[column] += 1
        result.append((column, row, c, i + 1))
    return result


def merged(case, additions):
    board = [list(r) for r in case['field']]
    for x, row, color, _ in additions:
        if row >= 1:
            assert board[row][x] == '.'
            board[row][x] = color
    return [''.join(r) for r in board]


def draw(case, output):
    alternatives = case['placement_diagram']['matching_after_placements']
    im = Image.new('RGB', (1278 if len(alternatives) > 1 else 970, 740), '#f5f7fa')
    d = ImageDraw.Draw(im)
    def text(x, y, s, size=17, color='#253344'):
        d.text((x, y), s, fill=color, font=ImageFont.truetype(FONT, size))
    seed = int(case['round']) - 2
    text(25, 16, f"例{case['id']}　シード{seed}・{case['ai']}P・{case['pair']}手目　{case['piece']}", 26)
    text(25, 61, '太い黒枠＝今回の3個（1＝軸、2＝上の子、3＝右の子：回転前の番号）', 17)
    text(25, 89, '接地・ちぎり後、消去前の位置。列は1始まり。13段目は保持、×は14段目で消滅。', 16)
    placements = [None, case['target'], case['placement_diagram']['shown_actual']]
    status = case['placement_diagram']['status']
    headings = ['配置前', '置きたかった場所', '実際：後続盤面で照合' if status == 'after_board_match' else '実際：途中観測から推定']
    if len(alternatives) > 1:
        placements.append(alternatives[1])
        headings.append('もう一つの一致候補')
    for j, placement in enumerate(placements):
        left = 70 + 308 * j
        text(left-15, 127, headings[j], 19)
        if placement is not None:
            text(left-15, 158, f"枠左列{placement[0]+1}・{'上右下左'[placement[1]]}向き", 16)
        else:
            text(left-15, 158, 'R赤・Y黄・G緑・B青・#おじゃま', 13)
        additions = landing(case, placement) if placement is not None else []
        added = {(x, row): (c, n) for x, row, c, n in additions}
        top, cell = 203, 34
        for x in range(6):
            text(left+x*cell+10, top-26, str(x+1), 16)
        for row in range(14):
            text(left-31, top+row*cell+6, str(14-row), 14)
            for x in range(6):
                xx, yy = left+x*cell, top+row*cell
                d.rectangle((xx,yy,xx+cell,yy+cell),fill='#e0e6ee' if row<2 else '#ffffff',outline='#d6dde6')
                old = case['field'][row][x]
                new = added.get((x,row))
                color = new[0] if new else old
                if color != '.':
                    d.ellipse((xx+3,yy+3,xx+31,yy+31),fill=COLORS[color],outline='#17212e' if new else COLORS[color],width=3 if new else 1)
                    label = str(new[1]) if new else color
                    text(xx+11, yy+5, label, 15, '#ffffff' if color!='Y' else '#27313d')
                    if new and row < 1:
                        d.line((xx+3, yy+3, xx+31, yy+31), fill='#253344', width=3)
                        d.line((xx+31, yy+3, xx+3, yy+31), fill='#253344', width=3)
        # Distinguish the hidden rows without drawing a fake landing above them.
        d.line((left,top+68,left+204,top+68),fill='#677689',width=2)
    notes = {
        1: ['着地点は目標と一致。操作の照合が途中で断念した例。', '「on_target:false」は実際の位置を直接測った値ではない。'],
        2: ['実際の図はD向きの観測に整合する候補。目標のU向きとは異なる。', '枠左列4・L向きでも消去後の盤面が一致するため、一意には確定できない。'],
        3: ['実際の図はL向きの観測に整合する候補。目標のD向きとは異なる。', '枠左列3・U向きでも消去後の盤面が一致するため、一意には確定できない。'],
        4: ['着地点は目標と一致。予測した引っ掛けとは違う動きで到達した例。', '「on_target:false」は実際の位置を直接測った値ではない。'],
        5: ['右図はL向き・右へ動く途中観測からの推定。', '次の自分の盤面が記録されていないため、実際の最終位置は未確認。'],
    }
    for i, note in enumerate(notes[case['id']]):
        text(25, 683+i*25, note, 16)
    im.save(output)
    return im


def main():
    path = ROOT / 'data/fever/baselines/2026-10-14-disabled-triple-operations.json'
    cases = json.loads(path.read_text(encoding='utf-8'))
    folder = ROOT / 'doc/images/disabled-triple-20261014'
    folder.mkdir(parents=True, exist_ok=True)
    # Use the pre-suspension transition model only for geometry/clearing,
    # because the new worker intentionally rejects these target placements.
    native = ROOT / cases[0]['placement_diagram']['before_native']
    with JsonProcess([native]) as engine:
        for case in cases:
            for placement in [case['target'], case['placement_diagram']['shown_actual']]:
                simulated = engine.ask(dict(op='transition', field=case['field'], piece=case['piece'],
                    x=placement[0], r='URDL'[placement[1]]))
                assert merged(case, landing(case, placement)) == simulated['locked_field']
            for placement in case['placement_diagram']['matching_after_placements']:
                simulated = engine.ask(dict(op='transition', field=case['field'], piece=case['piece'],
                    x=placement[0], r='URDL'[placement[1]]))
                assert simulated['field'] == case['observed_after_field']
            draw(case, folder / f"case-{case['id']}.png")
    print(f'Wrote and verified {len(cases)} board images: {folder}')


if __name__ == '__main__':
    main()
