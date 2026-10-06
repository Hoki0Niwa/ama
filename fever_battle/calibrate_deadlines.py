"""Read-only clock awards and nuisance boundaries; gaps cannot prove edges."""
import argparse
import json
from pathlib import Path
from .calibrate import records, file_sha256
from .timing import ChainTiming
from .worker import JsonProcess


def measure(paths, native=None):
    awards, deliveries, drops, expired_active, expired_chain_ends = [], [], [], [], []
    for path in paths:
        previous = None
        epoch = 0
        locks = [None, None]
        ends = [None, None]
        for packet in records(path):
            if packet.get('event') != 'sample' or packet['frame_before'] != packet['frame_after']:
                continue
            frame = packet['frame_before']
            if previous and frame < previous['frame_before']:
                epoch += 1
                previous = None
                locks, ends = [None, None], [None, None]
            if not previous:
                previous = packet
                continue
            delta = frame - previous['frame_before']
            if delta <= 0:
                continue
            for seat, side in enumerate(packet['players']):
                old = previous['players'][seat]
                if 'unreadable' in side or 'unreadable' in old or side['player_state'] != 1:
                    continue
                base = dict(source=str(path), epoch=epoch, seat=seat+1, frame=frame,
                            mode=side['mode'], exact_edge=delta == 1)
                if side['active']['placed'] == old['active']['placed']+1:
                    locks[seat] = dict(frame=frame, exact_edge=delta == 1,
                                      old=old, placed=side['active']['placed'])
                if old['link'] and not side['link']:
                    ends[seat] = dict(frame=frame, exact_edge=delta == 1, chain=old['link'])
                    if side['mode'] == old['mode'] == 'fever' and side['raw_clock_frames'] == 0:
                        expired_chain_ends.append(dict(**base, chain=old['link'],
                            old_clock=old['raw_clock_frames'], clock=0))
                if side['mode'] == old['mode'] == 'fever':
                    gain = side['raw_clock_frames']-old['raw_clock_frames'] + (
                        min(delta, old['raw_clock_frames']) if old['timer_active'] and not old['timer_frozen'] else 0)
                    if gain > 2:
                        awards.append(dict(**base, gain=gain, old_clock=old['raw_clock_frames'],
                            clock=side['raw_clock_frames'], old_link=old['link'], link=side['link'],
                            since_chain_end=frame-ends[seat]['frame'] if ends[seat] else None))
                    if side['raw_clock_frames'] == 0 and side['mode_phase'] == 2 and side['field_phase'] == 0:
                        if old['raw_clock_frames'] > 0 or old['mode_phase'] != 2:
                            expired_active.append(dict(**base, placed=side['active']['placed'],
                                                       pose=side['active']))
                if side['mode'] != old['mode']:
                    continue
                key = side['mode']+'_nuisance'
                new_pending, old_pending = side[key], old[key]
                enemy_old, enemy = previous['players'][1-seat], packet['players'][1-seat]
                if new_pending['confirmed'] > old_pending['confirmed'] and new_pending['unconfirmed'] < old_pending['unconfirmed']:
                    deliveries.append(dict(**base, count=new_pending['confirmed']-old_pending['confirmed'],
                        source_chain_end=bool(enemy_old.get('link') and not enemy.get('link'))))
                if not side['link'] and not old['link'] and new_pending['confirmed'] < old_pending['confirmed']:
                    lock = locks[seat]
                    drops.append(dict(**base, count=old_pending['confirmed']-new_pending['confirmed'],
                        lock_frame=lock['frame'] if lock else None,
                        lock_edge_exact=lock['exact_edge'] if lock else False,
                        lock_to_drop=frame-lock['frame'] if lock else None,
                        old_pose=lock['old']['active'] if lock else None,
                        old_board=lock['old']['settled_field'] if lock else None,
                        old_phase=old['mode_phase'], phase=side['mode_phase'],
                        field_phase=side['field_phase']))
            previous = packet
    if native is not None:
        for drop in drops:
            if not drop['exact_edge'] or not drop['lock_edge_exact'] or not drop['old_board']:
                continue
            pose = drop['old_pose']; piece = pose['piece']
            x = round(pose['cells'][0][0]) if piece[0]=='2' else round(min(x for x,y in pose['cells']))
            rotation = 'RYGB'.index(piece[2]) if piece[0]=='0' else pose['rotation']
            try:
                result = native.ask(dict(op='closing_transition', field=drop['old_board'],
                                         piece=piece, x=x, r='URDL'[rotation]))
                if result['links']:
                    continue
                split = max(result['split_distances'])
                drop.update(split_rows=split, lock_to_check_without_split=drop['lock_to_drop']-
                            ChainTiming.for_mode(drop['mode']).split_extra_frames[split])
            except (ValueError, KeyError):
                continue
    return dict(sources=[dict(path=str(p), sha256=file_sha256(p)) for p in paths],
                awards=awards, deliveries=deliveries, drops=drops, expired_active=expired_active,
                expired_chain_ends=expired_chain_ends)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native', type=Path)
    args = parser.parse_args()
    if args.native:
        with JsonProcess([args.native]) as native:
            report = measure(args.paths, native)
    else:
        report = measure(args.paths)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key:len(report[key]) for key in ('awards','deliveries','drops','expired_active','expired_chain_ends')}))


if __name__ == '__main__':
    main()
