"""Offline measurements from coherent, read-only Fever probe recordings.

Candidate phase offsets are retained as evidence, never silently promoted to
timing constants. Reject reset boundaries, CPU scratch boards and missed edges.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
from .worker import JsonProcess


def phase(player):
    data = bytes.fromhex(player['field_candidate']['hex'])
    return struct.unpack_from('<I', data, 0x10c)[0]


def epochs(path):
    groups = [[], []]
    # Multi-hour captures exceed several GB. Stream records and keep only the
    # current round, rather than allocating a second copy of the whole file.
    for row in records(path):
        if row.get('event') != 'sample' or not row.get('both_players_same_frame'):
            continue
        for seat, player in enumerate(row['players']):
            if not all(k in player for k in ('active','battle_candidate','field_candidate','simulator_field_candidate','score_candidate')):
                continue
            if player['battle_candidate']['cpu']: continue
            item = dict(player, frame=row['frame_before'][seat], phase=phase(player), seat=seat+1)
            group = groups[seat]
            if group and (item['address'] != group[-1]['address'] or item['frame'] < group[-1]['frame']):
                yield group
                group = groups[seat] = []
            if group and item['frame'] == group[-1]['frame']: continue
            group.append(item)
    yield from (g for g in groups if g)


def records(path):
    with Path(path).open(encoding='utf-8') as source:
        for line in source:
            if not line.endswith('\n'):
                # A recording in progress may have an unfinished final write.
                break
            yield json.loads(line)


def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def summary(values):
    return dict(n=len(values), min=min(values), median=statistics.median(values), max=max(values)) if values else dict(n=0)


def drawn_cells(player):
    raw=bytes.fromhex(player.get('drawn_cell_table_hex',''))
    if len(raw)!=128*24:return None
    result={}
    for i in range(128):
        if struct.unpack_from('<I',raw,i*24+0x10)[0]>>16!=i:return None
        if 1<=raw[i*24]<=6:
            identity=struct.unpack_from('<Q',raw,i*24+8)[0]
            if not identity or identity in result:return None
            result[identity]=(i,raw[i*24])
    return result


def animation_boundaries(interval,features):
    """Separate disappearance from logical cell movement, never fake rest.

    A cell reaching its final row does not prove that its render object stopped
    falling/bouncing. Exact visual rest needs the entity-coordinate recording.
    """
    sequence=[(p['frame'],drawn_cells(p)) for p in interval]
    if not sequence or any(c is None for f,c in sequence):return dict(status='drawn_cells_unavailable')
    if any(b[0]!=a[0]+1 for a,b in zip(sequence,sequence[1:])):return dict(status='missed_animation_frames')
    first,last=sequence[0][1],sequence[-1][1]
    removed=set(first)-set(last)
    moved={k for k in set(first)&set(last) if first[k][0]!=last[k][0]}
    if len(removed)!=features['cleared_including_garbage'] or len(moved)!=features['moving_puyos']:
        return dict(status='drawn_identity_geometry_mismatch')
    gone=[next(f for f,c in sequence if k not in c) for k in removed]
    moved_at=[next(f for f,c in sequence if c.get(k)!=first[k]) for k in moved]
    changed_at=[f for (af,a),(f,b) in zip(sequence,sequence[1:]) if any(a.get(k)!=b.get(k) for k in moved)]
    start=sequence[0][0]
    result=dict(status='disappearance_and_cell_motion_measured_visual_rest_unverified',
        first_disappearance_offset=min(gone)-start if gone else None,
        last_disappearance_offset=max(gone)-start if gone else None,
        first_survivor_cell_motion_offset=min(moved_at)-start if moved_at else None,
        last_survivor_cell_motion_offset=max(changed_at)-start if changed_at else None,
        visual_rest_offset=None,
        note='Cell movement is quantized; rest must include falling and bounce, not just final grid row.')
    result['coordinate_evidence']=coordinate_evidence(interval,moved)
    return result


def coordinate_evidence(interval,moved):
    """Landing anchors are candidates, not proof that render wobble stopped."""
    if not moved:return dict(status='no_moving_survivors')
    start=interval[0]['frame'];series={identity:[] for identity in moved}
    for p in interval:
        entities=p.get('animation_entities_candidate')
        if entities is None:return dict(status='entities_not_recorded')
        by_id={int(e['address'],16):e for e in entities}
        for identity in moved:
            entity=by_id.get(identity)
            if entity is None:return dict(status='entity_missing')
            raw=bytes.fromhex(entity['hex']);cell=entity['cell']
            if len(raw)!=0x40 or (raw[0x1e],raw[0x1f],raw[0x20])!=(cell%8,cell//8,cell):
                return dict(status='entity_cell_marker_mismatch')
            anchor,y,render_y=(struct.unpack_from('<f',raw,offset)[0] for offset in (0x24,0x2c,0x34))
            if not all(math.isfinite(v) and -5<=v<=20 for v in (anchor,y,render_y)):
                return dict(status='coordinate_candidate_out_of_range')
            series[identity].append((p['frame']-start,anchor,y,render_y,raw[0x1c],cell))
    boundary=next((b['frame']-start for a,b in zip(interval,interval[1:])
                   if not a['battle_candidate']['settled'] and b['battle_candidate']['settled']),None)
    if boundary is None:return dict(status='internal_boundary_not_observed')
    ends=[];contacts=[];render_active=[];overshoots=[]
    for samples in series.values():
        falling=[s for s in samples if s[0]>=boundary]
        changes=[b for a,b in zip(falling,falling[1:]) if abs(a[1]-b[1])>1e-5]
        if not changes:return dict(status='anchor_motion_not_observed')
        last=changes[-1];target_y=last[5]//8-3
        # Falling stacks can collide with bouncing support. The contact anchor
        # then exceeds the final logical row by more than one cell. Preserve
        # that evidence instead of imposing an unmeasured overshoot limit.
        overshoots.append(last[1]-target_y)
        ends.append(last[0]);contacts.append(bool(last[4]&1))
        render_active.append(abs(falling[-1][3]-falling[-2][3])>1e-5)
    return dict(status='candidate_landing_anchor_not_visual_rest',
        max_last_anchor_motion_offset=max(ends),
        fall_boundary_to_last_anchor_motion_frames=max(ends)-boundary,
        last_anchor_motion_to_next_link_frames=interval[-1]['frame']+1-start-max(ends),
        last_anchor_contact_bit_all_set=all(contacts),
        render_motion_at_next_link=any(render_active),
        max_anchor_overshoot_rows=max(overshoots),
        moving_entities=len(moved),visual_rest_offset=None)


def measure(paths, native):
    locks, links, terminals, rejected = [], [], [], defaultdict(int)
    for path in paths:
        for group in epochs(path):
            for index in range(1,len(group)):
                before, after = group[index-1],group[index]
                if after['active']['placed'] != before['active']['placed'] + 1: continue
                if after['frame'] != before['frame']+1:
                    rejected['missed_lock_edge'] += 1; continue
                if before['phase'] != 2:
                    rejected['not_operating_before_lock'] += 1; continue
                active=before['active']; cells=active['cells']; shape=active['piece'][0]
                if any(abs(x-round(x))>.01 for x,y in cells):
                    rejected['fractional_column']+=1; continue
                x=round(cells[0][0]) if shape=='2' else round(min(x for x,y in cells))
                rotation='RYGB'.index(active['piece'][2]) if shape=='0' else active['rotation']
                try:
                    transition=native.ask(dict(op='transition',field=before['simulator_field_candidate'],piece=active['piece'],x=x,r='URDL'[rotation]))
                except ValueError:
                    rejected['invalid_root_or_placement']+=1;continue
                if after['simulator_field_candidate'] not in (transition['field'],transition['locked_field']):
                    rejected['native_lock_board_mismatch']+=1;continue
                # Grounded bits from the preceding piece remain set during spawn.
                # Only the final operating interval with this piece counts.
                start=index-1
                while start>0 and group[start-1]['phase']==2 and group[start-1]['active']['placed']==active['placed'] and group[start-1]['active']['grounded'] and group[start]['frame']==group[start-1]['frame']+1:
                    start-=1
                grounded=after['frame']-group[start]['frame'] if active['grounded'] else 0
                end=index
                while end<len(group) and group[end]['active']['placed']==after['active']['placed'] and group[end]['frame']<=after['frame']+2500:
                    if end>index and group[end]['phase']==2: break
                    end+=1
                interval=group[index:end]
                stage5=[p for p in interval if p['phase']==5]
                next6=next((p for p in interval if stage5 and p['frame']>stage5[-1]['frame'] and p['phase']==6),None)
                complete_stage5=(stage5 and next6 and stage5[0]['frame']==after['frame']+1
                                 and next6['frame']==stage5[-1]['frame']+1)
                record=dict(source=str(path),seat=after['seat'],frame=after['frame'],piece=active['piece'],
                    x=x,r='URDL'[rotation],contact_to_lock_frames=grounded,input_condition='not_observed_in_probe',
                    split_rows=max(transition['split_distances']),split_distances=transition['split_distances'],
                    phase5_frames=(next6['frame']-stage5[0]['frame']) if complete_stage5 else None,
                    chain_length=len(transition['links']))
                locks.append(record)
                # Chain onset events are measured independently of prototype clocks.
                starts=[]; prior=0; onset_verified={}
                for interval_index,p in enumerate(interval):
                    link=p['battle_candidate']['link']
                    if link>prior:
                        starts.append((link,p))
                        onset_verified[p['frame']]=(interval_index>0
                            and interval[interval_index-1]['frame']==p['frame']-1
                            and interval[interval_index-1]['battle_candidate']['link']==link-1)
                    prior=link
                if [n for n,p in starts]!=list(range(1,len(transition['links'])+1)):
                    if transition['links']:rejected['incomplete_chain_edges']+=1
                    continue
                if starts and end<len(group):
                    n,p=starts[-1];ready=group[end]
                    tail=[a for a in interval if a['frame']>=p['frame']]
                    if (onset_verified[p['frame']] and ready['phase']==2 and tail
                            and ready['frame']==tail[-1]['frame']+1
                            and all(b['frame']==a['frame']+1 for a,b in zip(tail,tail[1:]))):
                        terminals.append(dict(source=str(path),seat=after['seat'],lock_frame=after['frame'],
                            start_frame=p['frame'],ready_frame=ready['frame'],
                            duration_frames=ready['frame']-p['frame'],
                            **transition['fall_features'][n-1]))
                for (n,p),(m,q) in zip(starts,starts[1:]):
                    if m!=n+1:continue
                    if not onset_verified[p['frame']] or not onset_verified[q['frame']]:
                        rejected['missed_link_onset_edge']+=1;continue
                    features=transition['fall_features'][n-1]
                    link_interval=[a for a in interval if p['frame']<=a['frame']<q['frame']]
                    if any(b['frame']!=a['frame']+1 for a,b in zip(link_interval,link_interval[1:])):
                        rejected['missed_link_frames']+=1;continue
                    settled=next((a['frame'] for a,b in zip(link_interval,link_interval[1:]) if not a['battle_candidate']['settled'] and b['battle_candidate']['settled']),None)
                    separated=animation_boundaries(link_interval,features)
                    if settled is not None:
                        separated['internal_boundary_offset']=settled+1-p['frame']
                        separated['boundary_to_next_link_frames']=q['frame']-settled-1
                        separated['boundary_meaning']='candidate pop/fall boundary, not a proven visual-rest flag'
                    links.append(dict(source=str(path),seat=after['seat'],lock_frame=after['frame'],link=n,
                        start_frame=p['frame'],next_start_frame=q['frame'],duration_frames=q['frame']-p['frame'],
                        settled_edge_last_unsettled_frame=settled,
                        animation=separated,**features))
    split=defaultdict(list)
    for r in locks:
        if r['phase5_frames'] is not None:split[str(r['split_rows'])].append(r['phase5_frames'])
    cohorts=defaultdict(list)
    for r in links:cohorts[f"fall={r['max_fall']},moving={r['moving_puyos']},columns={r['moving_columns']}"] .append(r['duration_frames'])
    return dict(status='measured_samples_not_general_law',unit='game_frame',fps=60,
        sources=[dict(path=str(p),sha256=file_sha256(p)) for p in paths],
        candidate_phase_offset='field+0x10c; phase 2 operating, 4 lock, 5 falling, 6 chain/check; still calibration evidence',
        contact_summary=summary([r['contact_to_lock_frames'] for r in locks]),
        split_stage_by_rows={k:summary(v) for k,v in sorted(split.items(),key=lambda kv:int(kv[0]))},
        chain_by_geometry={k:summary(v) for k,v in sorted(cohorts.items())},
        rejected=dict(rejected),locks=locks,links=links,terminals=terminals)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recordings',type=Path,nargs='+')
    parser.add_argument('--native',type=Path,default=Path('bin/fever_battle/fever_battle.exe'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with JsonProcess([args.native.resolve()]) as native: result=measure(args.recordings,native)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('locks','links','terminals','sources')},ensure_ascii=False))


if __name__=='__main__':main()
