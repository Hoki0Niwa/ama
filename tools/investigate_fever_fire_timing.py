"""Reproduce premature normal-board firing without changing engine policy.

Reports contain full native requests for later regression tests. Optional live
logs are evidence summaries, not exact protocol replay inputs.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.model import EMPTY, Scoring
from fever_battle.worker import JsonProcess
from fever_battle import tactics


class RecordingNative:
    def __init__(self, path):
        self.worker = JsonProcess([path], cwd=ROOT)
        self.request = None

    def ask(self, request):
        self.request = request
        return self.worker.ask(request)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live-log', type=Path)
    args = parser.parse_args()
    native = RecordingNative(args.native)
    policy = json.loads((ROOT/'data/fever/battle_policy.json').read_text(encoding='utf-8'))['normal_tactics']
    refs = json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
    field = list(next(s['field'] for s in refs['seeds'] if s['id']=='hirazumi-7'))
    field[4:7] = ['Y.....']*3
    cases = []
    try:
        for character in ('arle', 'rafisol'):
            for pending in (0, 1, 20):
                for at in (350, 700, 1000):
                    own = dict(character=character, field=field, queue=['2:YR','2:GB','2:GB'],
                        confirmed=pending, unconfirmed=0, remainder=0, garbage_phase=0, gauge=0)
                    enemy = dict(mode='fever', normal_confirmed=0, normal_unconfirmed=0,
                        fever_confirmed=0, fever_unconfirmed=0, remainder=0)
                    events = [dict(type='link', frame=at, points=30000), dict(type='end', frame=at+50)]
                    result = tactics.choose(native, Scoring(), own, 120, 1, policy,
                        enemy=enemy, enemy_events=events, builder=(5,'U'), builder_fire=False,
                        fever=dict(enemy_fever=True, their_end=at+50, enemy_reply_nuisance=300),
                        defense=dict(hold=300, kill=0, links=0, need=7), enemy_hold=550)
                    forecast = result['tactics_forecast']
                    cases.append(dict(character=character, pending=pending, event_at=at,
                        request=native.request, reply=result,
                        safe_nonclearing_candidates=sum(c['survives'] and not c['chain'] for c in forecast['candidates'])))
        probe = deepcopy(next(c['request'] for c in cases if c['character']=='arle' and c['pending']==1 and c['event_at']==350))
        probe['allowed'] = [dict(x=2,r='L')]
        weight_probes = []
        for weight in (0, 1000000):
            probe['weights']['mainline'] = probe['weights']['uncountered'] = weight
            reply = native.ask(probe)
            weight_probes.append(dict(mainline=weight, uncountered=weight, choice=reply['choice']))
    finally:
        native.worker.close()
    report = dict(status='native_policy_probe',
        native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(), cases=cases,
        mainline_weight_probe=weight_probes)
    if args.live_log:
        raw = args.live_log.read_bytes()
        text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        records = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
        selected = [r for r in records if r.get('auto')=='planning' and r.get('ai')==1 and r.get('pair') in (27,29,33)
                    and r.get('enemy',{}).get('mode')=='fever']
        matching_fire = [r for r in records if r.get('auto')=='fire' and any(
            r.get('ai')==p['ai'] and r.get('pair')==p['pair'] and abs(r.get('t',0)-p.get('t',0))<2 for p in selected)]
        report['live_evidence'] = dict(source=str(args.live_log), sha256=hashlib.sha256(raw).hexdigest(),
            exact_protocol_replay=False, planning=selected, firing=matching_fire)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(cases=len(cases), premature_main_cases=sum(c['reply']['chain']>=7 and
        c['reply']['tactics_forecast']['choice']['gauge_after']<7 for c in cases),
        output=str(args.output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
