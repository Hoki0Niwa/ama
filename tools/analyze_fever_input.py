"""Freeze diagnostics from an existing operation log; no game interaction."""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.log.read_bytes()
    encoding = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
    rows = []
    for line in raw.decode(encoding, errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    anomalies = []
    latest = {}
    for index, row in enumerate(rows):
        if row.get('auto') == 'planning':
            latest[row.get('ai')] = row
        trace = json.dumps(row.get('trace', []), ensure_ascii=False)
        if (row.get('auto') == 'locked' and
                (row.get('stopped_short') or 'stopped short' in trace or row.get('on_target') is False or
                 (row.get('aim_ms') or 0) >= 500)):
            anomalies.append(dict(index=index, event=row,
                                  preceding_planning=latest.get(row.get('ai'))))
    failures = [r for r in rows if r.get('auto') == 'analysis failed, retrying']
    releases = [r for r in rows if r.get('auto') == 'pre-input released']
    report = dict(status='historical_log_not_post_fix_live_acceptance',
        log_bytes=len(raw), log_sha256=hashlib.sha256(raw).hexdigest(),
        event_counts=dict(collections.Counter(r.get('auto') for r in rows)),
        anomaly_count=len(anomalies), anomalies=anomalies,
        opening_decisions=[r for r in rows if r.get('auto') == 'planning'
                           and r.get('cache') != 'prepare' and r.get('pair') == 0],
        analysis_failures=failures, pre_input_releases=releases,
        limitations=['Historical rejection logs do not name changed state keys.',
                      'Animation-boundary pre-input releases are necessary, not classified as bugs.',
                      'A stopped-short trace can still end at the correct target.',
                      'Counts describe this byte snapshot only; the log may continue growing.'])
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(log_bytes=len(raw), anomaly_count=len(anomalies),
                         event_counts=report['event_counts'])))


if __name__ == '__main__':
    main()
