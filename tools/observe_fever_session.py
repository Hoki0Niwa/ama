"""Read-only two-hour observation, compressed in five-minute segments.

Uses the bridge's calibrated reader; never opens a controller or reads hidden
future pieces. Closed segments can be analysed while the session continues.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=7200)
    args = parser.parse_args()
    sys.path.insert(0, str(args.bridge))
    import fever_mode_memory as reader
    profile_path = args.bridge / 'profiles/ppc-15209927.json'
    profile = reader.bridge.load(profile_path)
    dropsets = Path(__file__).resolve().parents[1] / 'data/fever/dropsets.json'
    characters = json.loads(dropsets.read_text(encoding='utf-8'))['characters']
    args.output.mkdir(parents=True, exist_ok=False)
    counts, segment, finished = {}, 0, []
    start = time.monotonic()
    manifest = dict(started_at_utc=datetime.now(timezone.utc).isoformat(),
                    seconds=args.seconds, controller=False, future_colors_read=False)

    def status(state):
        manifest.update(state=state, elapsed_seconds=round(time.monotonic()-start, 1),
                        recorded=counts, closed_segments=finished)
        temporary = args.output / 'status.tmp'
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(args.output / 'status.json')

    try:
        with reader.ProcessMemory(reader.find_process(profile['process'])) as mem:
            fingerprint = mem.fingerprint(profile['process'])
            if fingerprint['sha256'] != profile['exe_sha256']:
                raise ValueError('game differs from the calibrated executable')
            header = dict(event='header', fingerprint=fingerprint,
                profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(), **manifest)
            while time.monotonic()-start < args.seconds:
                name = f'segment-{segment:03d}.jsonl.gz'
                until = min(start+args.seconds, time.monotonic()+300)
                previous, last_status = None, 0
                with gzip.open(args.output / name, 'xt', encoding='utf-8', compresslevel=1) as out:
                    out.write(json.dumps(header)+'\n')
                    while time.monotonic() < until:
                        try:
                            packet = reader.capture(mem, profile, characters)
                        except (MemoryError, reader.F.FeverReadError, ValueError) as error:
                            packet = dict(event='read_error', error=str(error))
                        encoded = json.dumps(packet, ensure_ascii=False, separators=(',', ':'))
                        if encoded != previous:
                            out.write(encoded+'\n')
                            counts[packet['event']] = counts.get(packet['event'], 0)+1
                            previous = encoded
                        if time.monotonic()-last_status >= 10:
                            out.flush()
                            status('recording')
                            last_status = time.monotonic()
                        time.sleep(.01)
                finished.append(name)
                segment += 1
                status('recording')
        status('complete')
    except Exception as error:
        manifest['error'] = str(error)
        status('failed')
        raise


if __name__ == '__main__':
    main()
