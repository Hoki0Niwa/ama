"""Summarize read-only bridge objrec recordings without importing bridge code.

Example: python pvp/calibrate_timing.py rec1.jsonl rec2.jsonl --output stats.json
This reports observed counter intervals; it does not fit a physics model.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import struct


def summarize(paths):
    values = {'link_intervals': [], 'last_link_to_end': [], 'link_to_settled': []}
    for path in paths:
        last, start = {}, {}
        with Path(path).open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                seat, frame = row.get('s'), row.get('f')
                if not isinstance(frame, int):
                    continue
                if frame == 0 or (seat in last and frame < last[seat][1]):
                    last.pop(seat, None)
                    start.pop(seat, None)
                if row.get('o') == 'score' and row['k'] == 'd' and row['w'].get('0x48') == 1 and seat in start:
                    interval = frame - start[seat]
                    if 0 < interval < 200:
                        values['link_to_settled'].append(interval)
                if row.get('o') != 'field80':
                    continue
                if row['k'] == 'full':
                    raw = bytes.fromhex(row['hex'])
                    if len(raw) < 244:
                        continue
                    link = struct.unpack_from('<I', raw, 0xf0)[0] & 255
                elif row['k'] == 'd' and '0xf0' in row['w']:
                    link = row['w']['0xf0'] & 255
                else:
                    continue
                previous = last.get(seat)
                if previous and frame >= previous[1]:
                    if link == previous[0] + 1 and previous[0] > 0:
                        values['link_intervals'].append(frame - previous[1])
                    elif link == 0 and previous[0] > 0:
                        values['last_link_to_end'].append(frame - previous[1])
                if not previous or previous[0] != link:
                    last[seat] = (link, frame)
                    if link > 0:
                        start[seat] = frame
                    else:
                        start.pop(seat, None)
    return {key: {'samples': len(samples), 'median': statistics.median(samples) if samples else None,
                  'histogram': dict(sorted(Counter(samples).items()))}
            for key, samples in values.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recordings', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = {'sources': [str(p) for p in args.recordings], **summarize(args.recordings)}
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
