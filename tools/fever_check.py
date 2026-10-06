"""One entry point for the Fever checks: the test files, and a golden replay.

python tools/fever_check.py test
python tools/fever_check.py record            # rewrite data/fever/golden from the current binaries
python tools/fever_check.py replay            # compare the current binaries with data/fever/golden
python tools/fever_check.py replay --native bin/x/fever_battle.exe --solo bin/x/fever.exe

record runs the test files twice with AMA_NATIVE_TRACE set and keeps every
distinct request the native processes were asked. A request whose replies
differed (a search cut off by its time budget) is kept as unstable and not
compared. The saved protocol-3 requests of data/fever/baselines are answered
by a fresh engine each. Offline only: a matching replay says the binaries
answer as before, not that the answers are good or that the game accepts them.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GOLDEN = ROOT/'data/fever/golden'
NATIVE = ROOT/'bin/fever_battle/fever_battle.exe'
SOLO = ROOT/'bin/fever/fever.exe'
# Wall-clock measurements inside replies; everything else must match.
VOLATILE = {'search_ms', 'elapsed_ms', 'time_ms', 'think_ms', 'prepare_ms'}


def tests():
    return sorted(ROOT.glob('test/test_fever*.py'))


def run_tests(env=None, quiet=False):
    """Run every Fever test file; return [(name, tests run, ok, seconds)]."""
    rows = []
    for path in tests():
        started = time.monotonic()
        done = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=env, capture_output=True,
                              text=True, encoding='utf-8', errors='replace')
        tail = done.stderr.strip().splitlines()[-4:]
        ran = next((int(line.split()[1]) for line in tail if line.startswith('Ran ')), 0)
        rows.append((path.name, ran, done.returncode == 0, time.monotonic()-started))
        if not quiet:
            print(f'{"ok  " if done.returncode == 0 else "FAIL"} {path.name}: {ran} tests, {rows[-1][3]:.1f}s')
        if done.returncode and not quiet:
            print(done.stderr[-3000:])
    return rows


def normal(value):
    if isinstance(value, dict):
        return {k: normal(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [normal(v) for v in value]
    return value


def key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def role(exe):
    """Which binary a traced process was: the battle worker, the solo engine, or neither."""
    if exe == 'fever' or exe.startswith('fever-'):
        return 'solo'
    if 'battle' in exe:
        return 'native'
    return None


def trace_once():
    with tempfile.TemporaryDirectory() as folder:
        log = Path(folder)/'trace.jsonl'
        rows = run_tests({**os.environ, 'AMA_NATIVE_TRACE': str(log)}, quiet=True)
        entries = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []
    return rows, entries


def engine_requests():
    """Saved protocol-3 think requests, in file order, named by where they were found."""
    found = []
    def walk(node, path):
        if isinstance(node, dict):
            if node.get('protocol_version') == 3 and 'self' in node and 'enemy' in node:
                found.append((path, node))
                return
            for name, child in node.items():
                walk(child, f'{path}/{name}')
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f'{path}/{index}')
    for source in sorted((ROOT/'data/fever/baselines').glob('*.json')):
        walk(json.loads(source.read_text(encoding='utf-8')), source.name)
    return found


def engine_answer(native, solo, request):
    from fever_battle.mode_engine import ModeBattleEngine
    engine = ModeBattleEngine(native, solo, ROOT/'config.json')
    try:
        return normal(engine.answer(request))
    except (ValueError, KeyError, TypeError, RuntimeError, TimeoutError) as error:
        return dict(error=str(error))
    finally:
        engine.close()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(args):
    runs = [trace_once(), trace_once()]
    for rows, _ in runs:
        failed = [name for name, _, ok, _ in rows if not ok]
        if failed:
            raise SystemExit(f'tests failed while recording: {failed}')
    replies, order = {}, []
    for _, entries in runs:
        for entry in entries:
            kind = role(entry['exe'])
            if kind is None:
                continue
            name = (kind, key(entry['request']))
            if name not in replies:
                replies[name] = set()
                order.append((kind, entry['request']))
            replies[name].add(key(normal(entry['reply'])))
    cases = []
    for kind, request in order:
        seen = replies[(kind, key(request))]
        cases.append(dict(exe=kind, request=request, stable=len(seen) == 1,
                          reply=json.loads(next(iter(seen))) if len(seen) == 1 else None))
    engine = []
    for name, request in engine_requests():
        first, second = (engine_answer(args.native, args.solo, request) for _ in range(2))
        engine.append(dict(case=name, request=request, stable=first == second,
                           reply=first if first == second else None))
    GOLDEN.mkdir(parents=True, exist_ok=True)
    with gzip.open(GOLDEN/'native.jsonl.gz', 'wt', encoding='utf-8') as out:
        for case in cases:
            out.write(key(case)+'\n')
    with gzip.open(GOLDEN/'engine.jsonl.gz', 'wt', encoding='utf-8') as out:
        for case in engine:
            out.write(key(case)+'\n')
    summary = dict(native_sha256=sha(args.native), solo_sha256=sha(args.solo),
        head=subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        tests={name: ran for name, ran, _, _ in runs[0][0]},
        tests_total=sum(ran for _, ran, _, _ in runs[0][0]),
        native_cases=len(cases), native_stable=sum(c['stable'] for c in cases),
        native_by_exe_op=count_ops(cases),
        engine_cases=len(engine), engine_stable=sum(c['stable'] for c in engine),
        volatile_fields=sorted(VOLATILE),
        status='offline_replay_baseline_not_live_acceptance')
    (GOLDEN/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def count_ops(cases):
    counts = {}
    for case in cases:
        name = f"{case['exe']}:{case['request'].get('op', 'think')}"
        total, stable = counts.get(name, (0, 0))
        counts[name] = (total+1, stable+case['stable'])
    return {name: dict(cases=total, stable=stable) for name, (total, stable) in sorted(counts.items())}


def load(name):
    with gzip.open(GOLDEN/name, 'rt', encoding='utf-8') as source:
        return [json.loads(line) for line in source]


def replay(args):
    from fever_battle.worker import JsonProcess
    os.environ.pop('AMA_NATIVE_TRACE', None)
    differences, compared, skipped = [], 0, 0
    processes = dict(native=JsonProcess([args.native], cwd=ROOT), solo=JsonProcess([args.solo, ROOT/'config.json'], cwd=ROOT))
    try:
        for index, case in enumerate(load('native.jsonl.gz')):
            if not case['stable']:
                skipped += 1
                continue
            try:
                reply = normal(processes[case['exe']].ask(case['request'], timeout=30))
            except ValueError as error:
                reply = dict(error=str(error))
            compared += 1
            if reply != case['reply']:
                differences.append(dict(kind='native', index=index, exe=case['exe'], request=case['request'],
                                        expected=case['reply'], actual=reply))
    finally:
        for process in processes.values():
            process.close()
    for case in load('engine.jsonl.gz'):
        if not case['stable']:
            skipped += 1
            continue
        reply = engine_answer(args.native, args.solo, case['request'])
        compared += 1
        if reply != case['reply']:
            differences.append(dict(kind='engine', case=case['case'], request=case['request'],
                                    expected=case['reply'], actual=reply))
    report = dict(native_sha256=sha(args.native), solo_sha256=sha(args.solo), compared=compared,
                  skipped_unstable=skipped, differences=len(differences))
    print(json.dumps(report, ensure_ascii=False))
    for difference in differences[:args.show]:
        changed = sorted(k for k in set(difference['expected']) | set(difference['actual'])
                         if difference['expected'].get(k) != difference['actual'].get(k))
        print(difference['kind'], difference.get('case', difference.get('index')),
              difference['request'].get('op', 'think'), 'changed:', changed[:12])
    if args.output:
        args.output.write_text(json.dumps(dict(report, cases=differences), ensure_ascii=False, indent=1), encoding='utf-8')
    return 1 if differences else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('test', 'record', 'replay'))
    parser.add_argument('--native', type=Path, default=NATIVE)
    parser.add_argument('--solo', type=Path, default=SOLO)
    parser.add_argument('--output', type=Path, help='replay: write every difference here')
    parser.add_argument('--show', type=int, default=20, help='replay: differences to list')
    args = parser.parse_args()
    if args.command == 'test':
        rows = run_tests()
        print(f'{sum(ran for _, ran, _, _ in rows)} tests in {len(rows)} files, '
              f'{sum(not ok for _, _, ok, _ in rows)} files failed, {sum(s for *_, s in rows):.0f}s')
        return 1 if any(not ok for _, _, ok, _ in rows) else 0
    if args.command == 'record':
        return record(args)
    return replay(args)


if __name__ == '__main__':
    sys.exit(main())
