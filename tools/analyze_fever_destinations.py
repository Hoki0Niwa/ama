"""Read-only arrival-probe recordings: destination switch, entry and packet timing."""
import argparse
import json
from pathlib import Path


def analyse(path):
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a recorder may still be writing the final line
        if 'f' in row:
            rows.append(row)
    entries, exits, arrivals = [], [], []
    for i in (0, 1):
        last_chain_end = None
        phase12_at = None
        for k in range(1, len(rows)):
            a, b = rows[k-1], rows[k]
            old, new = a['p'][i], b['p'][i]
            if a['f'] >= b['f']:
                last_chain_end = phase12_at = None
                continue
            if old is None or new is None:
                continue
            contiguous = b['f'] - a['f'] == 1
            if old['link'] and not new['link']:
                last_chain_end = dict(frame=b['f'], exact=contiguous)
            if old['field_phase'] != 12 and new['field_phase'] == 12:
                phase12_at = dict(frame=b['f'], exact=contiguous)
            if old['tray'] == 0 and new['tray'] == 1:
                future = []
                for r in rows[k+1:]:
                    if r['f'] <= b['f'] or r['p'][i] is None or r['p'][i]['tray'] != 1:
                        break
                    future.append(r)
                control = next((r['f'] for r in future if r['p'][i]['field_phase'] == 0
                                and r['p'][i]['mode_phase'] == 2), None)
                entries.append(dict(player=i+1, frame=b['f'], exact_edge=contiguous,
                    chain_end=last_chain_end, entry_phase_start=phase12_at,
                    chain_end_to_destination=None if last_chain_end is None else b['f']-last_chain_end['frame'],
                    destination_to_first_control=None if control is None else control-b['f'],
                    before=a, after=b))
            elif old['tray'] == 1 and new['tray'] == 0:
                exits.append(dict(player=i+1, exact_edge=contiguous, before=a, after=b))
            if old['tray'] == new['tray'] and contiguous:
                for dest in ('normal', 'fever'):
                    increase = sum(new[dest]) - sum(old[dest])
                    if increase > 0:
                        arrivals.append(dict(player=i+1, frame=b['f'], destination=dest,
                            active_destination=new['tray'], amount=increase,
                            field_phase=new['field_phase'], mode_phase=new['mode_phase'],
                            enemy_link=b['p'][1-i]['link'] if b['p'][1-i] else None))
    return dict(source=str(path), frames=len(rows), entries=entries, exits=exits,
                positive_tray_changes=arrivals,
                caveat='Positive deltas are observations, not isolated test sends. Entry intervals are measured samples, not universal timing bounds.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyse(args.recording)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('frames', 'entries')}, ensure_ascii=False))
