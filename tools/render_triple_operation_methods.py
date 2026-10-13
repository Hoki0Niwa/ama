"""Explain suspended triple edges using predictions and measured moving cells."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = 'C:/Windows/Fonts/meiryo.ttc'
COLORS = {'R':'#df3e51','Y':'#e6bd23','G':'#209f70','B':'#387ce1','#':'#8b94a3'}


def render(case, family):
    im=Image.new('RGB',(1010,665),'#f5f7fa');d=ImageDraw.Draw(im)
    def text(x,y,s,size=17,color='#253344'):
        d.text((x,y),s,fill=color,font=ImageFont.truetype(FONT,size))
    title='引っ掛け：同じ列で1段上がる予測' if family=='hook' else '横押し戻し：壁から横へ1列ずれる予測'
    text(23,12,title,26)
    text(23,55,f"例{case['id']}　シード{int(case['round'])-2}・{case['ai']}P・{case['pair']}手目　{case['piece']}",19)
    text(23,85,'左回転で上の子を左へ回す。太枠の1＝軸、2＝上の子、3＝右の子（回転前）。',16)
    seen=case['diverged']['seen'];expected=case['diverged']['expected'];x,y,r=expected
    offsets=[(0,-1),(1,0),(0,1),(-1,0)]
    prediction=[(x,y),(x+offsets[r][0],y+offsets[r][1]),
                (x+offsets[(r+1)%4][0],y+offsets[(r+1)%4][1])]
    stages=[('① 回す前（実測）',seen[0][2]),('② モデルが期待した形',prediction),
            ('③ 実測：動いている途中',seen[-1][2])]
    cell=40
    for j,(heading,cells) in enumerate(stages):
        left=61+j*333;top=200
        text(left-28,124,heading,19)
        note=f"軸x={cells[0][0]:.2f}、y={cells[0][1]:.2f}"
        text(left-28,154,note,16)
        for col in range(6):text(left+col*cell+13,top-21,str(col+1),15)
        for row in range(7):
            gy=row-3;text(left-30,top+row*cell+10,str(12-gy),14)
            for col in range(6):
                xx=left+col*cell;yy=top+row*cell
                d.rectangle((xx,yy,xx+cell,yy+cell),fill='#e0e6ee'if gy<0 else'#ffffff',outline='#d6dde6')
                color=case['field'][gy+2][col]if gy>=-2 else'.'
                if color!='.':
                    d.ellipse((xx+5,yy+5,xx+35,yy+35),fill=COLORS[color])
                    text(xx+13,yy+9,color,15,'#ffffff'if color!='Y'else'#27313d')
        for i,(cx,cy) in enumerate(cells):
            xx=left+(cx+.5)*cell;yy=top+(cy+3+.5)*cell;color=case['piece'][i+2]
            d.ellipse((xx-17,yy-17,xx+17,yy+17),fill=COLORS[color],outline='#17212e',width=3)
            text(xx-6,yy-11,str(i+1),16,'#ffffff'if color!='Y'else'#27313d')
        text(left+55,top+7*cell+7,'下段は省略',14)
        if j==1:
            if family=='hook':
                xx=left+3.6*cell;yy=top+2.9*cell
                d.line((xx,yy,xx,yy-35),fill='#bd3a45',width=3)
                d.polygon([(xx-6,yy-25),(xx+6,yy-25),(xx,yy-36)],fill='#bd3a45')
            else:
                xx=left+2.2*cell;yy=top+3.8*cell
                d.line((xx,yy,xx+38,yy),fill='#bd3a45',width=3)
                d.polygon([(xx+29,yy-6),(xx+29,yy+6),(xx+40,yy)],fill='#bd3a45')
    text(25,506,'実測した軸の横位置：2.00 → 2.19 → 2.38（0始まりの座標）',18)
    if family=='hook':
        lines=['予測：軸を3列目に保ち、12段の壁の上へ1段持ち上げる。',
               '実測：軸が右へ動き始めた。持ち上げ予測と違う動きなので一時除外。',
               '最終配置はこの途中観測だけで決めない。例3は後続盤面からも候補が複数ある。']
    else:
        lines=['予測：13段の壁に子が当たり、軸が3列目から4列目へ押し戻される。',
               '実測：同じ右方向へ移動中。完了位置を待つ前に操作の照合が断念した。',
               '例1は後続盤面が目標設置と一致。着地点の失敗と、観測待ちの失敗を分けて直す。']
    for i,line in enumerate(lines):text(25,546+i*30,line,17)
    path=ROOT/f'doc/images/disabled-triple-20261014/method-{family}.png'
    im.save(path);print(path)


def main():
    cases=json.loads((ROOT/'data/fever/baselines/2026-10-14-disabled-triple-operations.json').read_text())
    render(cases[2],'hook');render(cases[0],'lateral')


if __name__=='__main__':main()
