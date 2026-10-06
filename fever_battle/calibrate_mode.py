"""Measure mode-specific clocks from read-only fever_mode_memory recordings.

Only adjacent frames prove an onset/end edge. Missing interior frames do not
change a measured endpoint interval. CPU scratch boards are never used: resolve
the drawn fixed board at each onset and verify its displayed score increment.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from .calibrate import records, file_sha256, summary
from .model import Scoring
from .timing import ChainTiming
from .worker import JsonProcess

COLOURS = {0: '.', 1: 'R', 2: 'G', 3: 'B', 4: 'Y', 6: '#', 22: '#'}


def drawn_field(side):
    rows = side['drawn_field_codes']
    if len(rows) != 14 or any(len(row) != 6 for row in rows):
        raise ValueError('drawn board dimensions')
    return [''.join(COLOURS[c] for c in row) for row in rows]


def measure(paths, native, scoring=None):
    scoring = scoring or Scoring()
    links, terminals, ready, locks, placements, rejected = [], [], [], [], [], Counter()
    for path in paths:
        previous, current, pending, lock = [None]*2, [None]*2, [None]*2, [None]*2
        epoch = [0, 0]
        for packet in records(path):
            if packet.get('event') != 'sample':
                continue
            if packet['frame_before'] != packet['frame_after']:
                rejected['mixed_frame'] += 1
                continue
            for seat, side in enumerate(packet['players']):
                before = previous[seat]
                previous[seat] = side
                if side.get('cpu') or 'unreadable' in side:
                    previous[seat] = current[seat] = pending[seat] = lock[seat] = None
                    continue
                if side['frame'] != packet['frame_before']:
                    rejected['side_frame_mismatch'] += 1
                    previous[seat] = current[seat] = pending[seat] = lock[seat] = None
                    continue
                reset = before and (side['address'] != before['address'] or side['frame'] < before['frame'])
                if reset:
                    epoch[seat] += 1
                if not before or reset or side['mode'] != before['mode'] or side['player_state'] != 1:
                    current[seat] = pending[seat] = lock[seat] = None
                    continue
                if side['frame'] == before['frame']:
                    continue
                exact = side['frame'] == before['frame'] + 1
                placed = side['active']['placed']
                same_piece = placed == before['active']['placed']
                base = dict(source=str(path), epoch=epoch[seat], seat=seat+1,
                            mode=side['mode'], character=side['character'], placed=placed)
                if not same_piece:
                    current[seat] = pending[seat] = None
                    lock[seat] = (side['frame'] if exact and placed == before['active']['placed']+1
                                  and before['mode_phase'] == 2 else None)
                    if lock[seat] is not None:
                        try:
                            pose = before['active']
                            if before['settled_field'] is None or any(abs(x-round(x)) > .01 for x,y in pose['cells']):
                                raise ValueError('unusable lock board or pose')
                            x = round(pose['cells'][0][0]) if pose['piece'][0]=='2' else round(min(x for x,y in pose['cells']))
                            rotation = 'RYGB'.index(pose['piece'][2]) if pose['piece'][0]=='0' else pose['rotation']
                            transition = native.ask(dict(op='transition', field=before['settled_field'],
                                piece=pose['piece'], x=x, r='URDL'[rotation]))
                            lock[seat] = dict(frame=side['frame'], split_rows=max(transition['split_distances']),
                                              chain=bool(transition['links']), locked_field=transition['locked_field'])
                        except (ValueError, KeyError):
                            lock[seat] = None
                onset = side['link'] > 0 and side['link'] != before['link']
                if onset:
                    verified = exact and side['link'] == before['link']+1 and same_piece
                    if not verified:
                        rejected['missed_link_onset'] += 1
                        current[seat] = None
                        continue
                    try:
                        board = drawn_field(side)
                        result = native.ask(dict(op='resolve', field=board))
                        if not result['links']:
                            raise ValueError('drawn onset has no clear')
                        group = result['links'][0]
                        point = scoring.link(side['character'], side['link'], group['groups'], group['colors'], side['mode'])
                        if side['total_score']-before['total_score'] != point:
                            raise ValueError('onset score mismatch')
                    except (ValueError, KeyError):
                        rejected['drawn_geometry_or_score_mismatch'] += 1
                        current[seat] = None
                        continue
                    last = current[seat]
                    if last and last['link']+1 == side['link']:
                        links.append(dict(**last, next_start_frame=side['frame'],
                                          duration_frames=side['frame']-last['start_frame']))
                    current[seat] = dict(**base, link=side['link'], start_frame=side['frame'],
                        terminal=len(result['links']) == 1, trigger_field=board,
                        points=point, **result['fall_features'][0],
                        internal_boundary_offset=None)
                    if side['link'] == 1 and lock[seat] is not None:
                        placement = lock[seat]
                        if placement['chain'] and placement['locked_field'] == board:
                            locks.append(dict(**base, lock_frame=placement['frame'], start_frame=side['frame'],
                                split_rows=placement['split_rows'], duration_frames=side['frame']-placement['frame']))
                        lock[seat] = None
                last = current[seat]
                if last and exact and not before['field_settled'] and side['field_settled']:
                    last['internal_boundary_offset'] = side['frame']-last['start_frame']
                if last and before['link'] > 0 and side['link'] == 0:
                    if exact and same_piece and last['terminal'] and side['total_score'] == before['total_score']:
                        end = dict(**last, end_frame=side['frame'],
                                   duration_frames=side['frame']-last['start_frame'])
                        terminals.append(end)
                        pending[seat] = end
                    else:
                        rejected['missed_or_inconsistent_end'] += 1
                    current[seat] = None
                tail = pending[seat]
                if tail and side['mode_phase'] == 2 and side['field_settled'] and side['field_phase'] == 0:
                    if exact and same_piece and before['mode_phase'] != 2:
                        ready.append(dict(**tail, ready_frame=side['frame'],
                            end_to_ready_frames=side['frame']-tail['end_frame'],
                            terminal_to_ready_frames=side['frame']-tail['start_frame'],
                            nuisance_at_ready=side['fever_nuisance'] if side['mode']=='fever' else side['normal_nuisance']))
                    else:
                        rejected['missed_ready_edge'] += 1
                    pending[seat] = None
                placement = lock[seat]
                if placement and not placement['chain'] and side['mode_phase'] == 2 and before['mode_phase'] != 2:
                    gauge = side['fever_nuisance'] if side['mode']=='fever' else side['normal_nuisance']
                    if (exact and same_piece and side.get('settled_field') == placement['locked_field']
                            and gauge['confirmed'] == 0):
                        placements.append(dict(**base, lock_frame=placement['frame'], ready_frame=side['frame'],
                            split_rows=placement['split_rows'], duration_frames=side['frame']-placement['frame']))
                    lock[seat] = None
    by_mode = {}
    for mode in ('normal', 'fever'):
        selected = [r for r in links if r['mode'] == mode]
        ends = [r for r in terminals if r['mode'] == mode]
        tails = [r for r in ready if r['mode'] == mode]
        by_mode[mode] = dict(
            links=len(selected), terminal_links=len(ends), ready_edges=len(tails),
            interval=summary([r['duration_frames'] for r in selected]),
            interval_minus_normal_contact=summary([r['duration_frames']-ChainTiming.fall_frames(r) for r in selected]),
            internal_boundary=summary([r['internal_boundary_offset'] for r in selected if r['internal_boundary_offset'] is not None]),
            no_fall_terminal=summary([r['duration_frames'] for r in ends if not r['max_fall']]),
            end_to_ready=summary([r['end_to_ready_frames'] for r in tails]),
            lock_to_first_link_by_split={str(d):summary([r['duration_frames'] for r in locks if r['mode']==mode and r['split_rows']==d])
                for d in sorted({r['split_rows'] for r in locks if r['mode']==mode})},
            nonclearing_lock_to_ready_by_split={str(d):summary([r['duration_frames'] for r in placements if r['mode']==mode and r['split_rows']==d])
                for d in sorted({r['split_rows'] for r in placements if r['mode']==mode})})
    return dict(schema_version=1, status='measured_exact_edges_drawn_geometry_and_score_verified',
        fps=60, unit='game_frame', sources=[dict(path=str(p),sha256=file_sha256(p)) for p in paths],
        by_mode=by_mode, rejected=dict(rejected), links=links, terminals=terminals, ready=ready, locks=locks, placements=placements,
        limitations='Contact formula is a normal-mode reference; mode switches and missed endpoint frames are excluded. Internal settled is a candidate pop/fall boundary, not visual rest.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recordings', type=Path, nargs='+')
    parser.add_argument('--native', type=Path, default=Path('bin/fever_battle/fever_battle.exe'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with JsonProcess([args.native.resolve()]) as native:
        result = measure(args.recordings, native)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(by_mode=result['by_mode'], rejected=result['rejected'])))


if __name__ == '__main__':
    main()
