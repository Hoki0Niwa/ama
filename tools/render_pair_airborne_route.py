"""Illustrate the logged pair route currently rejected by the fall model."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = 'C:/Windows/Fonts/meiryo.ttc'
BOARD = ['......','YY....','GY...Y','#B..YB','GY..GR','BRG.GR','BRG.YR',
         'YYRGYG','RBGGRG','RBRYRG','GG#YBB','BBBRGB','RGYRYG','RGYYRR']
COLORS = {'Y':'#e6bd23','B':'#387ce1','G':'#209f70','R':'#df3e51','#':'#8b94a3'}


def main():
    image = Image.new('RGB', (1030, 1040), '#f5f7fa')
    d = ImageDraw.Draw(image)
    def text(x,y,s,size=16,color='#253344'):
        d.text((x,y),s,fill=color,font=ImageFont.truetype(FONT,size))
    text(24,12,'2個組：14段目から横に渡る経路',27)
    text(24,56,'シード0・2P・32手目　2:YB　高さ [13,13,9,7,11,12]',18)
    text(24,86,'①〜③は旧モデルの整数姿勢。④〜⑤の高さは実ログ。⑥は未実行の回転を図示。',17)
    stages = [
        ('① 右移動×2 → 5列目', '出現列（3列目）から開始', (4,0,0)),
        ('② 右回転 → 左回転', '右の12段の壁で1段上げる', (4,-1,0)),
        ('③ 右移動 → 左回転', '6列目で左向き（黄が軸）', (5,-1,3)),
        ('④ 左回転 → 下向き', '軸が14段目へ上がる（実測）', (5,-2,2)),
        ('⑤ 左移動×3 → 3列目', '自然落下：y=-2.00 → -1.77', (2,-1.77,2)),
        ('⑥ 最後に右回転したい', '青を2列目へ回すには高さ不足', None),
    ]
    cell=38
    for i,(title,note,pose) in enumerate(stages):
        x0=60+(i%3)*337;top=201+(i//3)*405
        text(x0-27,top-71,title,19)
        text(x0-27,top-39,note,16)
        for x in range(6): text(x0+x*cell+13,top-22,str(x+1),15)
        for row in range(8):
            y=row-3
            text(x0-28,top+row*cell+9,str(12-y),14)
            for x in range(6):
                xx=x0+x*cell;yy=top+row*cell
                d.rectangle((xx,yy,xx+cell,yy+cell),fill='#e0e6ee'if y<0 else'#ffffff',outline='#d6dde6')
                color=BOARD[y+2][x]if y>=-2 else'.'
                if color!='.':
                    d.ellipse((xx+4,yy+4,xx+34,yy+34),fill=COLORS[color])
                    text(xx+13,yy+9,color,15,'#ffffff'if color!='Y'else'#27313d')
        d.line((x0,top+3*cell,x0+6*cell,top+3*cell),fill='#677689',width=2)
        text(x0+57,top+8*cell+5,'下段は省略',14)
        def puyo(x,y,color,ghost=False):
            xx=x0+(x+.5)*cell;yy=top+(y+3+.5)*cell
            box=(xx-16,yy-16,xx+16,yy+16)
            d.ellipse(box,fill=None if ghost else COLORS[color],outline=COLORS[color]if ghost else'#17212e',width=4)
            text(xx-6,yy-11,color,15,COLORS[color]if ghost else'#ffffff'if color!='Y'else'#27313d')
        if pose:
            x,y,r=pose;dx,dy=[(0,-1),(1,0),(0,1),(-1,0)][r]
            puyo(x,y,'Y');puyo(x+dx,y+dy,'B')
        else:
            # Outline: intended left-facing pose without the recorded fall.
            puyo(2,-2,'Y',True);puyo(1,-2,'B',True)
            # Lower translucent-blue cell: hypothetical rotation at the actual
            # observed height, not a rotation claimed to have happened.
            puyo(2,-1.77,'Y');puyo(1,-1.77,'B')
            xx=x0+1.5*cell;yy=top+2*cell
            d.rectangle((xx-20,yy-8,xx+20,yy+22),outline='#bd3a45',width=3)
        if i==4:
            xx=x0+3.9*cell;yy=top+cell
            d.line((xx,yy,xx,yy+31),fill='#bd3a45',width=3)
            d.polygon([(xx-6,yy+22),(xx+6,yy+22),(xx,yy+32)],fill='#bd3a45')
            text(x0+140,top+80,'約0.23段',14,'#bd3a45')
    text(25,943,'横移動中に少し落ちると、13段の列の上を回るための「14段目の余裕」を失う。',18)
    text(25,977,'現在は、この落下を見込んで届かない経路を候補から外している。壁越え全般の禁止ではない。',16)
    path=ROOT/'doc/images/disabled-triple-20261014/pair-airborne-route.png'
    image.save(path)
    print(path)


if __name__=='__main__': main()
