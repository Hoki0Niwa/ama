"""Analyse only closed, coherent live-observation segments."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fever_battle.calibrate import records
from fever_battle.calibrate_deadlines import measure
from fever_battle.worker import JsonProcess


def behaviour(paths):
    previous, epoch, samples = None, 0, 0
    rates, failures, pending, onsets = [], [], [None, None], [None, None]
    garbage_ready, garbage_pending, maximum_running_frame = [], [None, None], 0
    maximum_frame = 0
    for path in paths:
        for packet in records(path):
            if packet.get('event') != 'sample' or packet['frame_before'] != packet['frame_after']:
                continue
            frame = packet['frame_before']; samples += 1
            maximum_frame = max(maximum_frame, frame)
            if previous and frame < previous['frame_before']:
                epoch += 1; previous = None; pending = [None, None]; onsets = [None, None]; garbage_pending = [None,None]
            if previous and frame > previous['frame_before']:
                delta = frame-previous['frame_before']
                for seat, side in enumerate(packet['players']):
                    old = previous['players'][seat]
                    if 'unreadable' in old or 'unreadable' in side or old['player_state'] != 1 or side['player_state'] != 1:
                        continue
                    maximum_running_frame=max(maximum_running_frame,frame)
                    if old['mode']==side['mode']=='fever' and not old['link'] and not side['link']:
                        amount=old['fever_nuisance']['confirmed']-side['fever_nuisance']['confirmed']
                        if amount>0 and side['field_phase']==10:
                            garbage_pending[seat]=dict(epoch=epoch,seat=seat+1,drop_frame=frame,
                                drop_edge_exact=delta==1,count=amount,placed=side['active']['placed'],
                                queue_index=side['queue']['index'])
                    garbage=garbage_pending[seat]
                    if garbage:
                        if side['mode']!='fever' or frame-garbage['drop_frame']>300:
                            garbage_pending[seat]=None
                        elif (side['mode_phase']==2 and side['field_phase']==0 and
                              side['settled_field'] is not None and side['active']['placed']==garbage['placed']):
                            garbage.update(ready_frame=frame,ready_edge_exact=delta==1,
                                drop_to_operable_frames=frame-garbage['drop_frame'])
                            garbage_ready.append(garbage); garbage_pending[seat]=None
                    if side['target_point'] != old['target_point']:
                        rates.append(dict(epoch=epoch, seat=seat+1, frame_bounds=[frame-delta+1,frame],
                            before=old['target_point'], after=side['target_point'],
                            link=side['link'], score_delta=side['total_score']-old['total_score']))
                    if side['mode'] != old['mode']:
                        onsets[seat]=None
                    if side['mode']=='fever' and not old['link'] and side['link']:
                        onsets[seat]=dict(frame_bounds=[frame-delta+1,frame],
                            held=old['normal_nuisance']['confirmed']+old['normal_nuisance']['unconfirmed'],
                            remaining=old['raw_clock_frames'])
                    if old['mode'] == side['mode'] == 'fever' and old['link'] and not side['link']:
                        # The requested level is consumed when the seed arrives;
                        # during play the calibrated bridge uses last_chain.
                        target = old['seed_last_chain']
                        held = side['normal_nuisance']['confirmed']+side['normal_nuisance']['unconfirmed']
                        onset=onsets[seat]
                        before_held=old['normal_nuisance']['confirmed']+old['normal_nuisance']['unconfirmed']
                        if 3 <= target <= 15 and old['link'] < target and (held or before_held or (onset or {}).get('held')):
                            item = dict(epoch=epoch, seat=seat+1, frame=frame, exact_edge=delta==1,
                                chain=old['link'], target=target, remaining=side['raw_clock_frames'],
                                held_pending=held, held_pending_before_end=before_held,
                                onset=onset, next_seed_observed=False,
                                queue_index=side['queue']['index'])
                            failures.append(item); pending[seat]=item
                        onsets[seat]=None
                    item = pending[seat]
                    if item:
                        if side['mode'] != 'fever' or frame-item['frame'] > 200:
                            pending[seat]=None
                        elif (side['mode_phase']==2 and side['settled_field'] is not None and
                              side['queue']['index'] != item['queue_index']):
                            item.update(next_seed_observed=True, next_seed_frame=frame,
                                        next_seed_remaining=side['raw_clock_frames'])
                            pending[seat]=None
            previous = packet
    return dict(samples=samples, observed_rounds=epoch+bool(samples), maximum_frame=maximum_frame,
                maximum_running_frame=maximum_running_frame, fever_garbage_ready=garbage_ready,
                rate_changes=rates, failed_chains_with_held_nuisance=failures)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--native', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    status=json.loads((args.directory/'status.json').read_text(encoding='utf-8'))
    paths=[args.directory/name for name in status['closed_segments']]
    if not paths:
        raise ValueError('no closed segments yet')
    if args.native:
        with JsonProcess([args.native]) as native:
            boundaries=measure(paths,native)
    else:
        boundaries=measure(paths)
    report=dict(recording_status=status, behaviour=behaviour(paths), boundaries=boundaries)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(closed_segments=len(paths), **{k:v for k,v in report['behaviour'].items()
        if k not in ('rate_changes','failed_chains_with_held_nuisance','fever_garbage_ready')},
        fever_garbage_ready=len(report['behaviour']['fever_garbage_ready']),
        rate_changes=len(report['behaviour']['rate_changes']),
        failures=report['behaviour']['failed_chains_with_held_nuisance'],
        boundaries={k:len(v) for k,v in boundaries.items() if k!='sources'}),ensure_ascii=False))


if __name__=='__main__': main()
