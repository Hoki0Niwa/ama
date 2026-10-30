"""Offline recorded-request latency comparison; never connects to the game."""
import argparse
import copy
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('fixture', type=Path)
parser.add_argument('--output', type=Path, default=ROOT/'bin/strategy-timing.json')
args = parser.parse_args()
rows = []
for i, case in enumerate(json.loads(args.fixture.read_text(encoding='utf-8'))['cases']):
    names = ('mainline', 'brawl', 'hybrid')
    for name in names[i % 3:] + names[:i % 3]:
        req = copy.deepcopy(case['request'])
        req.pop('normal_tactics', None)
        if name != 'mainline':
            req['normal_tactics'] = dict(strategy=name)
        engine = ModeBattleEngine(ROOT/'bin/fever_battle/fever_battle.exe', ROOT/'bin/fever/fever.exe', ROOT/'config.json')
        try:
            reply = engine.answer(req)
            rows.append(dict(case=i, strategy=name, ms=reply['search_ms'], reason=reply['reason']))
        finally:
            engine.close()
summary = {}
for name in ('mainline', 'brawl', 'hybrid'):
    values = sorted(r['ms'] for r in rows if r['strategy'] == name)
    summary[name] = dict(n=len(values), median=statistics.median(values), max=max(values))
args.output.write_text(json.dumps(dict(summary=summary, rows=rows), indent=2)+'\n', encoding='utf-8')
print(json.dumps(summary))
