"""Controlled quiet-board initiative from recorded pieces; not a match simulator."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--output',type=Path,default=ROOT/'bin/strategy-initiative-rollout.json')
    parser.add_argument('--legacy-pace-key',action='store_true',help='Isolate the old estimated-pace cache invalidation using the current engine.')
    args=parser.parse_args()
    fixture=ROOT/'data/fever/golden/quiet-initiative-sequence.json'
    requests=json.loads(fixture.read_text(encoding='utf-8'))['requests']
    results=[]
    for strategy in ('mainline','brawl','hybrid'):
        engine=ModeBattleEngine(args.native,ROOT/'bin/fever/fever.exe',ROOT/'config.json')
        if args.legacy_pace_key:
            signature=engine._signature
            def legacy(*a,**kw):
                return json.dumps(dict(json.loads(signature(*a,**kw)),pace=engine.pace),sort_keys=True)
            engine._signature=legacy
        field=None; remainder=0; longest=0; moves=0
        try:
            for source in requests:
                req=deepcopy(source)
                req.pop('enemy_chain',None)
                req['normal_tactics']=dict(strategy=strategy)
                req['observation']['in_flight']={}
                for side in (req['self'],req['enemy']):
                    side.update(mode='normal',gauge=0,phase='controllable',confirmed=0,unconfirmed=0,
                        normal_confirmed=0,normal_unconfirmed=0,fever_confirmed=0,fever_unconfirmed=0)
                own=req['self']
                if field is not None: own['field']=field
                own.update(remainder=remainder,normal_chain_max=longest,moves_since_chain=moves)
                started=time.perf_counter()
                engine.answer(dict(req,op='prepare_observed'))
                preparation=(time.perf_counter()-started)*1000
                started=time.perf_counter();reply=engine.answer(req)
                elapsed=(time.perf_counter()-started)*1000
                field=reply['next_field']
                sent,remainder=divmod(remainder+reply['next_score'],req['target_point'])
                longest=max(longest,reply['chain'])
                moves=0 if reply['chain'] else moves+1
                row=dict(strategy=strategy,piece=own['piece_id'],reason=reply['reason'],chain=reply['chain'],
                    sent=sent,preparation_ms=preparation,execution_ms=elapsed,reused=reply.get('search_reused',False))
                results.append(row)
                if reply['chain']: print(json.dumps(row),flush=True)
                if field is None: break
        finally:
            engine.close()
    args.output.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__': main()
