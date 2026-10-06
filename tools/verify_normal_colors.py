"""Recheck saved protocol 3 normal-color decisions without game input."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True,
                        help='JSON containing cases with saved request objects')
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding='utf-8'))
    records, timings = [], []
    engine = ModeBattleEngine(args.native, ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    try:
        for case in source['cases']:
            request = deepcopy(case['request'])
            # Compare cold normal decisions at the current standard search size.
            request['solo_options'] = dict(beam_width=50, beam_depth=8)
            engine.prepared = None
            started = time.perf_counter()
            reply = engine.answer(request)
            elapsed = (time.perf_counter()-started)*1000
            assert reply['action'] == 'place'
            assert authorize_mode_reply(request, reply, request)
            own = request['self']
            actual = engine.native.ask(dict(op='transition', field=own['field'],
                piece=own['queue'][0], x=reply['x'], r=reply['r']))
            points = engine.scoring.chain(own['character'], actual['links'])
            assert reply['link_points'] == points
            assert reply['chain'] == len(points)
            assert reply['fire'] == bool(points)
            assert reply['next_all_clear'] == actual['all_clear']
            if not own['confirmed'] or reply['fire']:
                assert reply['next_field'] == actual['field']
            needs = reply['normal_color_needs']
            assert needs['status'] == 'reachable_color_completion_heuristic_not_executable_future'
            timings.append(elapsed)
            records.append(dict(request=request, choice={k:reply[k] for k in ('x','r','chain','reason')},
                needs=needs, needed_color_consumed=reply.get('needed_color_consumed'),
                intentional_small_clear=reply.get('intentional_small_clear', False),
                elapsed_ms=elapsed, native_transition_and_scoring_verified=True,
                placement_authorization_verified=True))
    finally:
        engine.close()
    report = dict(date='2026-10-06', source=source.get('source'),
        source_sha256=source.get('source_sha256'), controller=False, live_input_verified=False,
        interpretation='recorded_snapshots_model_replay_not_win_rate_or_live_acceptance',
        binary_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
        replayed=len(records), mainline_found=sum(c['needs']['mainline_chain']>=2 for c in records),
        choices_preserving_colors=sum(c['choice']['reason']=='normal_preserve_needed_colors' for c in records),
        timing=dict(mean_ms=statistics.mean(timings), max_ms=max(timings),
            scope='cold_50x8_decision_ipc_and_os_scheduling_included'), cases=records)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
