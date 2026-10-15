"""Frozen S0 confirmation: provenance, public replay, smoke, then one paired run."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import random
from pathlib import Path
import shutil
import statistics
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.first40_benchmark import Observation, NativeEnvironment, percentile
from fever_battle.first40_provenance import fingerprints, sha
from fever_battle.firstscore40_backend import ScoreBackend, SETTINGS as ACTOR_SETTINGS
from fever_battle.firstscore40_benchmark import TARGETS, SCORING, run_trial, summarize, paired
from fever_battle.worker import JsonProcess
from tools.bench_fever_firstscore40 import contract
from tools.bench_fever_first40_deadline import prepare as prepare_reference

SETTINGS = ROOT / 'data/fever/research/firstscore40_s0_confirm_v1.json'
PLAN = ROOT / 'doc/contracts/FIRSTSCORE40_S0_CONFIRMATION.md'
OLD = ROOT / 'data/fever/baselines/2026-10-12-firstscore40'
START = ROOT / 'bin/s0-confirm/20261013/start'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def fresh(path):
    path.mkdir(parents=True, exist_ok=False)
    return path


def settings():
    s = load(SETTINGS)
    if (s['targets'] != TARGETS or s['choose_budget_ms'] != 250 or
        s['planner_budget_ms'] != 25 or s['confirmation_seed_start'] != 61001 or
        s['confirmation_seed_count'] != 64 or s['backends'] != ['b0', 's0']):
        raise ValueError('confirmation contract changed')
    return s


def seeds(s):
    return list(range(s['confirmation_seed_start'], s['confirmation_seed_start'] + s['confirmation_seed_count']))


def inventory_seeds(wanted, exclude):
    """Inspect numeric seed fields, not scores or quoted source fragments."""
    import re
    import subprocess
    names = subprocess.check_output(['rg', '--files', '--hidden', '--no-ignore', 'data', 'bin',
                                     '-g', '*.json', '-g', '*.jsonl'], cwd=ROOT, text=True).splitlines()
    # Exclude our own reservation and provenance; those do not generate a queue.
    ignored = [exclude.resolve(), SETTINGS.resolve(),
               (ROOT / 'data/fever/baselines/2026-10-12-firstscore40-s0-plan').resolve()]
    pattern = re.compile(r'\b(?:' + '|'.join(map(str, wanted)) + r')\b')
    found, scanned = [], []
    def visit(value, name, location):
        if isinstance(value, dict):
            for key, child in value.items():
                if (key == 'seed' or key.endswith('_seed')) and type(child) is int and child in wanted:
                    found.append(dict(file=name, location=location + '/' + key, seed=child))
                if (key == 'seeds' or key.endswith('_seeds')) and isinstance(child, list):
                    hit = sorted(set(i for i in child if type(i) is int) & set(wanted))
                    if hit: found.append(dict(file=name, location=location + '/' + key, seeds=hit))
                if isinstance(child, (dict, list)): visit(child, name, location + '/' + key)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                if isinstance(child, (dict, list)): visit(child, name, location + '/' + str(i))
    for name in names:
        p = (ROOT / name).resolve()
        if any(p == x or x in p.parents for x in ignored): continue
        raw = p.read_text(encoding='utf-8-sig')
        scanned.append(name.replace('\\', '/'))
        if not pattern.search(raw): continue
        if p.suffix == '.jsonl':
            for i, line in enumerate(raw.splitlines()):
                if pattern.search(line): visit(json.loads(line), name, 'line' + str(i + 1))
        else: visit(json.loads(raw), name, '')
    return dict(scanned=len(scanned), matches=found,
                file_list_sha256=hashlib.sha256(('\n'.join(sorted(scanned)) + '\n').encode()).hexdigest(),
                scope='local data/bin JSON and JSONL numeric seed fields; archives and other checkouts excluded')


def check_frozen():
    old = load(OLD / 'research-v1/manifest.json')
    current = fingerprints()
    for name, digest in old['source_sha256'].items():
        if current.get(name) != digest: raise ValueError('frozen actor source changed: ' + name)
    for name, digest in old['binaries'].items():
        if sha(name) != digest: raise ValueError('frozen binary changed: ' + name)
    return old


def preflight(args):
    s = settings()
    old = check_frozen()
    args.baseline = ROOT / 'data/fever/baselines/2026-10-12-f40-deadline/development24/steps.jsonl'
    args.mode = 'practical'
    out, m = prepare_reference(args)
    built = load(args.planner_build)
    archive = args.planner_build.parent / 'source-snapshot.zip'
    if sha(archive) != built['source_snapshot_sha256']: raise ValueError('planner archive changed')
    if str(args.planner.resolve()) not in built['binaries']: raise ValueError('planner/build mismatch')
    for name, digest in built['binaries'].items():
        if sha(name) != digest: raise ValueError('planner binary changed')
    with zipfile.ZipFile(archive) as z:
        for name, digest in built['source_sha256'].items():
            if Path(name).suffix not in ('.cpp', '.h', '.cc'): continue
            raw = z.read(name)
            if hashlib.sha256(raw).hexdigest() != digest: raise ValueError('planner build source mismatch')
            if (ROOT / name).read_bytes().replace(b'\r\n', b'\n') != raw.replace(b'\r\n', b'\n'):
                raise ValueError('compiled planner source changed: ' + name)
    if sha(ACTOR_SETTINGS) != built['research_settings_sha256']: raise ValueError('actor settings changed')
    for source, dest in ((PLAN, 'experiment-spec.md'), (SETTINGS, 'confirmation-settings.json'),
                         (ACTOR_SETTINGS, 'actor-settings.json'), (args.planner_build, 'planner-build.json'),
                         (archive, 'planner-source-snapshot.zip'), (START / 'preflight.json', 'start-preflight.json')):
        shutil.copyfile(source, out / dest)
    # Nested research settings and the frozen specification are part of the source package.
    with zipfile.ZipFile(out / 'source-snapshot.zip', 'a', zipfile.ZIP_DEFLATED) as z:
        for p in (SETTINGS, ACTOR_SETTINGS, PLAN): z.write(p, p.relative_to(ROOT).as_posix())
    seed_check = inventory_seeds(seeds(s), out)
    write(out / 'seed-inventory.json', seed_check)
    if seed_check['matches']: raise ValueError('confirmation seed already recorded')
    m.update(schema='ama.firstscore40.s0_confirmation.manifest.v1', experiment='S0C frozen score firing at 250ms',
             contract=contract(), seed_role=s['seed_role'], mode='practical', backends=s['backends'],
             seeds=seeds(s), characters=s['characters'], expected_trials=256,
             settings=s, settings_sha256=sha(SETTINGS), actor_settings_sha256=sha(ACTOR_SETTINGS),
             specification_sha256=sha(PLAN), source_snapshot_sha256=sha(out / 'source-snapshot.zip'),
             planner_build_manifest=built, planner_build_manifest_sha256=sha(args.planner_build),
             planner_source_archive_sha256=sha(archive), seed_inventory_sha256=sha(out / 'seed-inventory.json'),
             actor_frozen_against=sha(OLD / 'research-v1/manifest.json'),
             plan_start_head=load(START / 'preflight.json')['head'],
             ordering='ascending seed; alternate character order and arm order per seed parity; sequential trials',
             solver_input='seven public Observation fields only; no environment seed, trial ID or hidden colors')
    m['binaries'].update(built['binaries'])
    write(out / 'manifest.json', m)
    print(json.dumps({'preflight': 'ok', 'seed_scan_files': seed_check['scanned'], 'expected_trials': 256}), flush=True)


def verify_experiment(out):
    m = load(out / 'manifest.json')
    if m['experiment'] != 'S0C frozen score firing at 250ms': raise ValueError('wrong specification')
    if m['source_sha256'] != fingerprints(): raise ValueError('confirmation sources changed')
    if sha(SETTINGS) != m['settings_sha256'] or sha(ACTOR_SETTINGS) != m['actor_settings_sha256']:
        raise ValueError('settings changed')
    if sha(PLAN) != m['specification_sha256']: raise ValueError('plan changed during confirmation')
    for p, digest in m['binaries'].items():
        if sha(p) != digest: raise ValueError('binary changed: ' + p)
    return m


def public_rows(rows, label):
    history = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        if row['backend'] != label or 'links' not in row: continue
        key = (row['character'], row['seed'])
        t, since, maximum = history[key]
        if row['move'] != t + 1: raise ValueError('non-contiguous public history')
        obs = Observation(tuple(row['before']), tuple(row['queue']), row['character'], t, t, since, maximum)
        yield row, obs
        chain = len(row['links'])
        history[key] = [t + 1, 0 if chain else since + 1, max(maximum, chain)]


def probe_request(obs):
    return dict(op='score-probe', observation=asdict(obs), work_budget_ms=25,
                transition_limit=16000, witness_limit=48000)


def replay(args):
    verify_experiment(args.output)
    out = fresh(args.output / 'replay')
    records = read_rows(OLD / 'research-v1/steps.jsonl')
    differences, misses, stops = [], [], Counter()
    replies, times = [], []
    with JsonProcess([args.planner], cwd=ROOT) as worker, (out / 'replies.jsonl').open('x', encoding='utf-8') as stream:
        worker.ask({'op': 'reset'})
        for row, obs in public_rows(records, 's0'):
            begin = time.perf_counter()
            reply = worker.ask(probe_request(obs), timeout=1)
            elapsed = (time.perf_counter() - begin) * 1000
            before = row['research_planner']
            ident = dict(character=row['character'], seed=row['seed'], move=row['move'])
            completed = reply['score_probe_complete']
            same = all(reply.get(k) == before.get(k) for k in ('decision', 'first_main_score', 'first_main_chain'))
            if completed and not same: differences.append(ident)
            if before.get('decision') and (not completed or not same): misses.append(ident)
            if not completed: stops[reply['stats']['stop_reason']] += 1
            record = dict(**ident, observation=asdict(obs), elapsed_ms=elapsed, reply=reply,
                          completed=completed, policy_equal=same, old_proof=bool(before.get('decision')))
            stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n'); stream.flush()
            replies.append(record); times.append(elapsed)
    if len(replies) != 1095: raise ValueError('public replay population changed')
    result = dict(observations=len(replies), complete=sum(r['completed'] for r in replies),
                  old_fire_records=sum(r['old_proof'] for r in replies), differences=differences, fire_misses=misses,
                  stops=dict(stops), times=cost(times), source_steps_sha256=sha(OLD / 'research-v1/steps.jsonl'),
                  ready=not differences and not misses, new_opening_trials=0,
                  unlogged_old_nomove_probe=1, internal_budget_ms=25)
    write(out / 'results.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not result['ready']: raise SystemExit('Replay failed: stop before opening new seeds.')


class RecordingBackend:
    """Records public input and failed probes without changing the delegated action."""
    def __init__(self, delegate):
        self.delegate = delegate
        self.last_observation = None

    @property
    def last_planner(self):
        return self.delegate.last_planner

    def choose(self, observation):
        self.last_observation = observation
        return self.delegate.choose(observation)

    def processes(self):
        return self.delegate.processes()

    def close(self):
        self.delegate.close()


def recorded_trial(character, seed, label, backend_factory, environment_factory, emit):
    holder, rows = {}, []
    def backend():
        wrapped = RecordingBackend(backend_factory())
        holder['backend'] = wrapped
        return wrapped
    def capture(row):
        row = deepcopy(row)
        wrapped = holder.get('backend')
        if wrapped is not None:
            if wrapped.last_observation is not None: row['observation'] = asdict(wrapped.last_observation)
            row['research_planner'] = deepcopy(wrapped.last_planner)
        rows.append(row)
        emit(row)
    result = run_trial(character, seed, label, backend, environment_factory, capture)
    return result, rows


def canonical_piece(value):
    # Native text may canonicalize an all-same-color J to L. No other shape substitution.
    return 'L:' + value[2:] if value.startswith('J:') and len(set(value[2:])) == 1 else value


def audit_fire(records, result, native=None):
    first_deadline, issues, proof_calls, switches = None, [], 0, 0
    last_remaining = None
    for row in records:
        if 'links' not in row: continue
        reply = row.get('research_planner', {})
        decision = reply.get('decision')
        if result['backend'] != 's0': continue
        if not decision:
            if first_deadline is not None: issues.append(dict(move=row['move'], reason='missing_probe_after_adopted_proof'))
            continue
        proof = decision['proof']
        deadline = row['move'] + len(proof) - 1
        if first_deadline is None: first_deadline = deadline
        if deadline > first_deadline: issues.append(dict(move=row['move'], reason='extended_fire_deadline'))
        if not reply.get('score_probe_complete'): issues.append(dict(move=row['move'], reason='incomplete_adopted_probe'))
        if not 1 <= len(proof) <= min(3, 41 - row['move']): raise ValueError('proof beyond public horizon')
        field = row['before']
        for i, item in enumerate(proof):
            if item['before'] != field or item['move'] != row['move'] + i: raise ValueError('discontinuous proof')
            if canonical_piece(item['piece']) != canonical_piece(row['queue'][i]): raise ValueError('proof used hidden piece')
            if item['dead'] or item['score'] != sum(SCORING.chain(result['character'], item['links'], 'normal')):
                raise ValueError('invalid proof score/death')
            if i + 1 < len(proof) and len(item['links']) >= 10: raise ValueError('proof crossed absorbing first main')
            if native is not None:
                actual = native.ask(dict(op='transition', field=field, piece=item['piece'], **item['placement']))
                if (actual['field'], actual['links'], actual['dead'], actual['discarded']) != (
                    item['after'], item['links'], item['dead'], item['discarded']):
                    raise ValueError('proof forecast differs from reference native')
                proof_calls += 1
            field = item['after']
        if len(proof[-1]['links']) < 10 or proof[-1]['score'] < TARGETS[result['character']]:
            raise ValueError('proof final main below target')
        item = proof[0]
        if (item['placement'], item['after'], item['links'], item['dead']) != (
            dict(x=row['x'], r=row['r']), row['after'], row['links'], row['dead']):
            raise ValueError('executed step differs from its own proof')
        if last_remaining is not None and proof != last_remaining: switches += 1
        last_remaining = proof[1:]
    if first_deadline is not None and not (result['success']['40'] and result['success_move'] <= first_deadline):
        issues.append(dict(reason='adopted_proof_not_fired_by_deadline', deadline=first_deadline))
    return dict(first_proof_deadline=first_deadline, issues=issues, reference_transitions=proof_calls,
                replanned_suffixes=switches, adopted_proof=first_deadline is not None)


def cost(values):
    return dict(n=len(values), mean_ms=statistics.mean(values) if values else None,
                p95_ms=percentile(values, .95), maximum_ms=max(values, default=None), over_250ms=sum(x > 250 for x in values))


def sign_flip(q):
    mass, n = {0: 1}, 0
    for value in q:
        if not value: continue
        n += 1
        following = Counter()
        for total, count in mass.items():
            following[total - abs(value)] += count
            following[total + abs(value)] += count
        mass = following
    return sum(count for total, count in mass.items() if total >= sum(q)) / 2**n


def lookup_runs(runs, expected):
    keys = [(r['character'], r['seed'], r['backend']) for r in runs]
    required = {(c, s, b) for c in TARGETS for s in expected for b in ('b0', 's0')}
    if len(keys) != len(set(keys)) or set(keys) != required: raise ValueError('incomplete or duplicate paired trials')
    return dict(zip(keys, runs))


def clustered(runs, expected):
    lookup = lookup_runs(runs, expected)
    q = [sum(int(lookup[c, s, 's0']['success']['40']) - int(lookup[c, s, 'b0']['success']['40']) for c in TARGETS)
         for s in expected]
    rng = random.Random(0x540)
    samples = sorted(sum(rng.choices(q, k=len(q))) / (2 * len(q)) for _ in range(10000))
    return dict(seed_clusters=len(q), q=q, difference=sum(q)/(2*len(q)), net_gain=sum(q),
                bootstrap95=[samples[250], samples[9750]], sign_flip_one_sided=sign_flip(q),
                assumption='arm exchangeability at seed cluster; development/confirmation, not Steam validation')


def full_cost(runs):
    result = {}
    for c in TARGETS:
        for b in ('b0', 's0'):
            selected = [r for r in runs if r['character'] == c and r['backend'] == b]
            times = [v for r in selected for v in r['timings_ms']]
            times += [r['failed_think_ms'] for r in selected if r.get('failed_think_ms') is not None]
            value = cost(times)
            cpu = [r.get('total_cpu_seconds') for r in selected]
            value['cpu_seconds'] = sum(cpu) if cpu and all(v is not None for v in cpu) else None
            value['cpu_per_decision'] = value['cpu_seconds']/len(times) if value['cpu_seconds'] is not None and times else None
            value['response_over_250ms'] = sum(v > 250 for r in selected for v in r['timings_ms'])
            result[c + '/' + b] = value
    return result


def gate(runs, expected, ready, audits, provenance=True):
    if not ready or not provenance or any(r['outcome'] in ('unfinished', 'engine_error') for r in runs):
        return dict(disposition='hold_invalid_or_incomplete', eligible=False)
    try:
        lookup_runs(runs, expected)
    except ValueError:
        return dict(disposition='hold_invalid_or_incomplete', eligible=False)
    statistics_ = clustered(runs, expected)
    comparisons = paired(runs, 'b0', 's0')
    costs = full_cost(runs)
    losses = sum(len(p['loss_seeds']) for p in comparisons.values())
    early = all(v >= 0 for p in comparisons.values() for v in p['secondary_differences'].values())
    safe = all(sum(r['outcome'] == outcome and r['character'] == c and r['backend'] == 's0' for r in runs) <=
               sum(r['outcome'] == outcome and r['character'] == c and r['backend'] == 'b0' for r in runs)
               for c in TARGETS for outcome in ('dead', 'nomove'))
    safe = safe and not any(r['outcome'] == 'timeout' for r in runs)
    proofs = all(not a['issues'] for a in audits)
    required_keys = {(r['character'], r['seed'], r['backend']) for r in runs}
    audit_keys = {(a.get('character'), a.get('seed'), a.get('backend')) for a in audits}
    if audit_keys != required_keys or len(audits) != len(runs):
        return dict(disposition='hold_invalid_or_incomplete', eligible=False)
    cpu_available = all(v['cpu_per_decision'] is not None for v in costs.values())
    if not cpu_available: return dict(disposition='hold_invalid_or_incomplete', eligible=False)
    budget = all(costs[c+'/s0']['p95_ms'] <= costs[c+'/b0']['p95_ms'] + 25 and
                 costs[c+'/s0']['cpu_per_decision'] <= 1.15*costs[c+'/b0']['cpu_per_decision'] for c in TARGETS)
    budget = budget and all(v['response_over_250ms'] == 0 for v in costs.values())
    effect = statistics_['difference'] >= .05 and statistics_['net_gain'] >= 7 and all(p['gain_seeds'] for p in comparisons.values())
    evidence = statistics_['sign_flip_one_sided'] <= .05
    harms = losses > 0 or not (early and safe and proofs and budget)
    passed = effect and evidence and not harms
    disposition = 'eligible_for_next_research_baseline' if passed else (
        'not_adopted_current_s0_250' if harms else 'hold_insufficient_evidence')
    return dict(disposition=disposition, eligible=passed, effect=effect, evidence=evidence,
                losses=losses, early=early, safety=safe, proof_deadlines=proofs, cost=budget,
                clustered=statistics_, paired=comparisons, costs=costs)


def compare_steps(a, b):
    keys = ('before', 'queue', 'x', 'r', 'after', 'links', 'chain', 'dead', 'discarded', 'actual_score')
    return all(a.get(k) == b.get(k) for k in keys)


def execute(args, smoke=False):
    m = verify_experiment(args.output)
    if not load(args.output/'replay/results.json')['ready']: raise ValueError('public replay did not pass')
    checks = load(args.output/'test-results/verification.json')
    if not checks['passed']: raise ValueError('required regression checks did not pass')
    if not smoke and not load(args.output/'smoke/results.json')['ready']: raise ValueError('smoke did not pass')
    if not smoke:
        scan = inventory_seeds(m['seeds'], args.output)
        write(args.output/'seed-inventory-before-run.json', scan)
        if scan['matches']: raise ValueError('new seed has been consumed')
    out = fresh(args.output / ('smoke' if smoke else 'confirmation'))
    pairs_ = [tuple(v) for v in m['settings']['smoke_pairs']] if smoke else [
        (c, s) for i, s in enumerate(m['seeds']) for c in (list(TARGETS) if i % 2 == 0 else list(reversed(TARGETS)))]
    wall = time.perf_counter()
    end = wall + m['settings']['wall_cap_minutes']*60
    runs, records, invalid, stopped = [], [], [], False
    with (out/'steps.jsonl').open('x', encoding='utf-8') as stream:
        def emit(row):
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':'))+'\n'); stream.flush()
            records.append(row)
        for i, (c, s) in enumerate(pairs_):
            order = ('b0', 's0') if ((s - 61001) if not smoke else i) % 2 == 0 else ('s0', 'b0')
            for label in order:
                if time.perf_counter() >= end: stopped = True; break
                result, trial_rows = recorded_trial(c, s, label,
                    lambda label=label: ScoreBackend(args.native, args.planner, args.config, label, 250, 25, end),
                    lambda character, seed: NativeEnvironment(args.native, character, seed), emit)
                runs.append(result); write(out/'runs.json', runs)
                print(json.dumps({k:result[k] for k in ('character','seed','backend','outcome','first_main_chain','first_main_score','success_move')}), flush=True)
                if result['outcome'] == 'engine_error': stopped = True; break
            if stopped: break
    # Reference replay of proofs is validation cost, outside the measured trials.
    audits = []
    with JsonProcess([args.native], cwd=ROOT) as native:
        for r in runs:
            subset = [v for v in records if (v['character'], v['seed'], v['backend']) == (r['character'], r['seed'], r['backend'])]
            try:
                a = audit_fire(subset, r, native)
            except ValueError as error:
                invalid.append(dict(character=r['character'], seed=r['seed'], backend=r['backend'], error=str(error)))
                a = dict(first_proof_deadline=None, issues=[dict(reason='invalid_proof')], reference_transitions=0)
            audits.append(dict(character=r['character'], seed=r['seed'], backend=r['backend'], **a))
    write(out/'fire-audit.json', audits)
    valid_provenance = True
    try: verify_experiment(args.output)
    except ValueError: valid_provenance = False
    expected_trials = 8 if smoke else 256
    complete = len(runs) == expected_trials and not any(r['outcome']=='unfinished' for r in runs)
    result = dict(complete=complete, planned=expected_trials, started=len(runs), not_started=expected_trials-len(runs),
                  runs=runs, summary=summarize(runs), costs=full_cost(runs),
                  provenance_unchanged=valid_provenance, invalid_proofs=invalid,
                  fire_audit_sha256=sha(out/'fire-audit.json'), driver_wall_seconds=time.perf_counter()-wall)
    if smoke:
        old_rows = read_rows(OLD/'research-v1/steps.jsonl') + read_rows(OLD/'smoke/steps.jsonl')
        old_steps = {(v['character'],v['seed'],v['backend'],v['move']):v for v in old_rows if 'links' in v}
        changes = []
        for v in records:
            if 'links' not in v: continue
            key = (v['character'],v['seed'],v['backend'],v['move'])
            if key not in old_steps or not compare_steps(v,old_steps[key]): changes.append(list(key))
        old_runs = load(OLD/'research-v1/results.json')['runs'] + load(OLD/'smoke/results.json')['runs']
        ends = {(v['character'],v['seed'],v['backend']):(v['outcome'],v['first_main_score'],v['placed_moves']) for v in old_runs}
        end_changes = [dict(character=r['character'],seed=r['seed'],backend=r['backend']) for r in runs
                       if ends[r['character'],r['seed'],r['backend']] != (r['outcome'],r['first_main_score'],r['placed_moves'])]
        result.update(matched_placements=sum('links' in v for v in records)-len(changes), changes=changes, end_changes=end_changes,
                      ready=complete and valid_provenance and not invalid and not changes and not end_changes and
                            not any(r['outcome'] in ('timeout','engine_error') for r in runs))
    else:
        result['gate'] = gate(runs,m['seeds'],complete,audits,valid_provenance and not invalid)
        if complete: result['paired'] = paired(runs,'b0','s0')
    write(out/'results.json',result)
    print(json.dumps({'complete':complete, 'ready':result.get('ready'), 'gate':result.get('gate')},ensure_ascii=False),flush=True)
    if smoke and not result['ready']: raise SystemExit('Smoke failed: stop before new seeds.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['preflight','replay','smoke','run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native',type=Path,default=ROOT/'bin/f40-diagnostics/reference/bin/commit-build/fever_battle.exe')
    parser.add_argument('--build-manifest',type=Path,default=ROOT/'bin/f40-diagnostics/reference/bin/commit-build/build.json')
    parser.add_argument('--planner',type=Path,default=ROOT/'bin/firstscore40/build-v4/firstscore40.exe')
    parser.add_argument('--planner-build',type=Path,default=ROOT/'bin/firstscore40/build-v4/build.json')
    parser.add_argument('--config',type=Path,default=ROOT/'config.json')
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.command=='preflight': preflight(args)
    elif args.command=='replay': replay(args)
    else: execute(args, smoke=args.command=='smoke')


if __name__=='__main__': main()
