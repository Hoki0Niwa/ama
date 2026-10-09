"""When nuisance lands in live Fever battles, against what the engine took for it.

python tools/analyze_fever_arrival.py LOG [LOG ...] [--output REPORT.json]

Reads the bridge's protocol-3 session logs (UTF-16, `FEVER BATTLE`). From every log:
frames per piece (two locks in a row with no chain between), and for every packet that
landed on a normal board, the frames and pieces from its first sight to the landing.
From logs that carry `arrival` (2026-10-08 on): the end of the opponent's chain as the
engine predicted it against the decision at which the packet was first seen confirmed,
and the pieces it counted against the pieces actually locked before that.

The log has one record per decision, so a moment is known to within one piece: an
observed moment lies between the decision before it and the decision that shows it.
Offline reading of logs: it measures what happened, not why.
"""
import argparse
import json
from pathlib import Path
import statistics


def records(path):
    text = Path(path).read_bytes().decode('utf-16', errors='replace')
    lines = text.splitlines()
    if not lines or 'FEVER BATTLE' not in lines[0]:
        return None
    out = []
    for line in lines:
        if line.startswith('{'):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def spread(values):
    if not values:
        return None
    values = sorted(values)
    at = lambda share: values[int(share * (len(values) - 1))]
    return dict(n=len(values), p10=at(.1), median=at(.5), p90=at(.9), mean=round(statistics.mean(values), 1))


def analyse(logs):
    pace = {'normal': [], 'fever': []}
    landings, ends, counted = [], [], []
    for log in logs:
        last_lock, seen, chain = {}, {}, {}
        for d in log:
            kind, ai = d.get('auto'), d.get('ai')
            if kind in ('locked', 'fire') and 'frame' in d:
                before = last_lock.get(ai)
                if (before and d['placed'] == before['placed'] + 1 and before['auto'] == 'locked'
                        and before['chain'] == 0 and d['mode'] == before['mode'] and 0 < d['frame'] - before['frame'] < 400):
                    pace[d['mode']].append(d['frame'] - before['frame'])
                last_lock[ai] = d
                for state in (seen.get(ai), chain.get(ai)):
                    if state:
                        state['locks'] += 1
            if kind != 'planning' or 'field' not in d or not d.get('decision_identity'):
                continue
            identity = d['decision_identity']
            frame, match = identity['frame'], identity['match_id']
            if d.get('mode') != 'normal':
                seen.pop(ai, None), chain.pop(ai, None)
                continue
            garbage, pending = d['field'].count('#'), d['nuisance'][0]
            state = seen.get(ai)
            if state and state['match'] != match:
                state = None
            if state and garbage > state['garbage']:
                landings.append(dict(frames=frame - state['frame'], pieces=state['locks'], packet=state['peak']))
                state = None
            if pending and not state:
                state = dict(match=match, frame=frame, garbage=garbage, locks=0, peak=pending)
            if state:
                state.update(garbage=garbage, peak=max(state['peak'], pending))
                if not pending:
                    state = None
            seen[ai] = state
            # The engine's own timing, where the log has it.
            arrival, tray = d.get('arrival'), d.get('tray')
            watch = chain.get(ai)
            if watch and watch['match'] != match:
                watch = None
            if watch and tray and tray[0] > 0:
                # First decision that shows the packet confirmed: the chain ended before it,
                # and after the decision before it.
                ends.append(dict(predicted=watch['end'], after=watch['previous'], by=frame,
                                 late_by_at_least=max(0, watch['previous'] - watch['end']),
                                 early_by_at_most=max(0, watch['end'] - frame) and 0,
                                 predicted_minus_observed=[watch['end'] - frame, watch['end'] - watch['previous']]))
                counted.append(dict(counted=watch['pieces'], locked=watch['locks'], piece_frames=watch['piece_frames']))
                watch = None
            if arrival and d.get('enemy_chain') and arrival.get('chain_end_in') is not None and tray and tray[0] == 0:
                if not watch:
                    watch = dict(match=match, end=frame + arrival['chain_end_in'], pieces=arrival['pieces'],
                                 piece_frames=arrival['piece_frames'], locks=0, previous=frame)
                watch['previous'] = frame
            elif watch and not d.get('enemy_chain') and not (tray and tray[1]):
                watch = None
            chain[ai] = watch
    report = dict(logs=len(logs),
        frames_per_piece={mode: spread(values) for mode, values in pace.items()},
        from_first_sight_to_landing={name: dict(frames=spread([x['frames'] for x in rows]),
                pieces_locked=dict(sorted((k, sum(min(x['pieces'], 8) == k for x in rows)) for k in range(9)
                                          if any(min(x['pieces'], 8) == k for x in rows))))
            for name, rows in (('packet_1_to_5', [x for x in landings if x['packet'] <= 5]),
                               ('packet_6_to_29', [x for x in landings if 6 <= x['packet'] < 30]),
                               ('packet_30_or_more', [x for x in landings if x['packet'] >= 30])) if rows})
    if ends:
        # predicted - observed: the observed end lies between the two decisions, so this is an interval.
        report['opponent_chain_end'] = dict(n=len(ends),
            predicted_minus_first_confirmed_decision=spread([e['predicted_minus_observed'][0] for e in ends]),
            predicted_minus_last_unconfirmed_decision=spread([e['predicted_minus_observed'][1] for e in ends]),
            predicted_after_it_was_already_confirmed=sum(e['predicted_minus_observed'][0] > 0 for e in ends),
            predicted_before_it_was_still_unconfirmed=sum(e['predicted_minus_observed'][1] < 0 for e in ends))
        report['pieces_before_confirmation'] = dict(n=len(counted),
            counted_minus_locked=spread([c['counted'] - c['locked'] for c in counted]),
            counted_more_than_locked=sum(c['counted'] > c['locked'] + 1 for c in counted),
            piece_frames_used=spread([c['piece_frames'] for c in counted]))
    else:
        report['opponent_chain_end'] = 'no log here carries the engine\'s arrival record'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('logs', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    logs = [log for log in map(records, args.logs) if log]
    report = analyse(logs)
    report['skipped_not_fever_battle'] = len(args.logs) - len(logs)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
