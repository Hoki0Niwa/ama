"""Replay prepared placements as their already observed opposing attack progresses."""
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
    parser.add_argument('--bridge',type=Path,default=ROOT.parent/'ama-memory-bridge')
    parser.add_argument('--native',type=Path,default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--fixture',type=Path,default=ROOT/'data/fever/golden/known-attack-progress.json')
    parser.add_argument('--output',type=Path,default=ROOT/'bin/known-attack-progress-replay.json')
    args=parser.parse_args()
    sys.path.insert(0,str(args.bridge))
    from fever_mode_bridge import Client
    results=[]
    for case in json.loads(args.fixture.read_text(encoding='utf-8'))['cases']:
        engine=ModeBattleEngine(args.native,ROOT/'bin/fever/fever.exe',ROOT/'config.json')
        try:
            prepared=engine.answer(case['prepare_request'])
            state=prepared['prepared_state']
            row=dict(line=case['line'],projection=state.get('incoming_projection'))
            for name in ('before','after'):
                client=object.__new__(Client)
                client.prepared_state=deepcopy(state)
                if name=='before':client.prepared_state.pop('incoming_projection',None)
                started=time.perf_counter()
                reply=client.preview_committed(case['request'])
                row[name]=dict(kept=reply is not None,preview_ms=(time.perf_counter()-started)*1000,
                    placement=None if reply is None else [reply['x'],reply['r']])
            results.append(row)
            print(json.dumps(row),flush=True)
        finally:
            engine.close()
    args.output.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
