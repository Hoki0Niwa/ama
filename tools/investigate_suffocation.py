"""Read-only probes of upper-row exclusions and shape-dependent room."""
import json, hashlib, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine

def rows(f): return f.split('/') if isinstance(f,str) else f
def count(f): return sum(c!='.' for r in rows(f) for c in r)
def classify(moves,occupied,cells):
    legal=[p for p in moves if not p['dead'] and not p['links'] and count(p['field'])==occupied+cells]
    central=[p for p in legal if all(sum(r[x]!='.' for r in rows(p['field']))<=10 for x in (2,3))]
    upper=[p for p in central if all(sum(r[x]!='.' for r in rows(p['field']))<=12 for x in (1,4))]
    return dict(physical_nonclear=len(legal),central_margin_nonclear=len(central),upper_open_nonclear=len(upper),upper_excluded=[dict(x=p['x'],r=p['r']) for p in central if p not in upper])
def main():
    engine=ModeBattleEngine(ROOT/'bin/fever_battle/fever_battle.exe', ROOT/'bin/fever/fever.exe',ROOT/'config.json')
    out=dict(status='saved_boards_and_synthetic_shapes_not_live_survival_proof',native_sha256=hashlib.sha256((ROOT/'bin/fever_battle/fever_battle.exe').read_bytes()).hexdigest(),boards=[])
    data=json.loads((ROOT/'data/fever/baselines/2026-10-11-symptoms-default-second.json').read_text())
    own=dict(field=['......']*14,queue=['0:R','2:GB','L:RRG'])
    out['empty_big']=dict(release=engine._stack_full(own,dict(margin=1)),diagnostic=engine.normal_capacity)
    try:
        for run in data['runs']:
            for t in run['trace']:
                if not t['fire'] and count(t['before'])<48: continue
                f=t['before']; cells={'2':2,'L':3,'J':3,'4':4,'0':4}[t['piece'][0]]
                actual=classify(engine.native.ask(dict(op='placements',field=f,piece=t['piece']))['placements'],count(f),cells)
                shapes={}
                for piece in ['2:RG','L:RRG','J:RGR','4:RRGG','0:R']:
                    n={'2':2,'L':3,'J':3,'4':4,'0':4}[piece[0]]
                    shapes[piece]=classify(engine.native.ask(dict(op='placements',field=f,piece=piece))['placements'],count(f),n)
                out['boards'].append(dict(character=run['character'],seed=run['seed'],move=t['move'],piece=t['piece'],field=f,count=count(f),fire=t['fire'],chain=t['links'],actual=actual,shapes=shapes))
    finally: engine.close()
    out['summary']=dict(boards=len(out['boards']),upper_only_no_stack=sum(b['actual']['central_margin_nonclear']>0 and b['actual']['upper_open_nonclear']==0 for b in out['boards']),pair_room_but_LJ4_no_room=sum(b['shapes']['2:RG']['central_margin_nonclear']>0 and any(b['shapes'][p]['central_margin_nonclear']==0 for p in ['L:RRG','J:RGR','4:RRGG']) for b in out['boards']))
    target=ROOT/'data/fever/baselines/2026-10-11-suffocation-investigation.json'
    target.write_text(json.dumps(out,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
    print(json.dumps(out['summary']))
if __name__=='__main__': main()

