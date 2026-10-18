"""Put the decisions a bridge session logged to an engine again, as they were asked.

Since 2026-10-15 the bridge (ama-memory-bridge fever_mode_play.decision_record) writes the engine
request into three kinds of event of the session log: `analysis failed, retrying` (a placement the
controller could not execute), `fire` (a chain was started) and `seed decision` (Fever). This tool
reads those requests and asks `ModeBattleEngine.answer` again, so one symptom is a question to an
engine and a few milliseconds, not hours of play:

    python tools/replay_logged_decisions.py LOG [--kind failed fire seed] [--round N] [--limit N]
                                                [--engine EXE] [--config CONFIG.json]

Each decision is asked of a fresh engine. A live session carries state across pieces (caches, the
margin forecast), so a cold answer can differ from the logged move for reasons that are not a
change of the engine; `same` / `changed` is a reading aid, not a verdict. For a failed placement
the useful reading is whether the replayed engine would still choose that move.
"""
import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
KINDS = {'failed': 'analysis failed, retrying', 'fire': 'fire', 'seed': 'seed decision'}


def events(log, kinds):
    wanted = {KINDS[k] for k in kinds}
    rounds = 0
    with io.open(log, 'r', encoding='utf-16', errors='replace') as handle:
        for line in handle:
            if line.startswith('{"auto": "round over"'):
                rounds += 1
                continue
            if '"request"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('auto') in wanted and isinstance(row.get('request'), dict):
                row['_round'] = rounds + 1
                yield row


def replay(log, kinds, round_number, limit, engine_path, config):
    from fever_battle.mode_engine import ModeBattleEngine
    solo = ROOT / 'bin/fever/fever.exe'
    tally, rows = Counter(), []
    for row in events(log, kinds):
        if round_number and row['_round'] != round_number:
            continue
        if limit and len(rows) >= limit:
            break
        engine = ModeBattleEngine(str(engine_path), str(solo), str(config))
        try:
            reply = engine.answer(dict(row['request']))
            move = '%s%s' % (reply.get('x'), reply.get('r'))
            error = None
        except Exception as problem:  # a recorded request the engine now refuses is a finding
            reply, move, error = {}, None, '%s: %s' % (type(problem).__name__, problem)
        finally:
            engine.close()
        logged = row.get('move')
        verdict = 'error' if error else ('same' if move == logged else 'changed')
        tally[(row['auto'], verdict)] += 1
        queue = (row['request'].get('self') or {}).get('queue') or ['?']
        rows.append(dict(round=row['_round'], event=row['auto'], piece=queue[0], logged_move=logged,
                         replayed_move=move, verdict=verdict, reason=reply.get('reason'), error=error))
    return dict(decisions=len(rows), tally={'%s %s' % k: v for k, v in sorted(tally.items())}, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log')
    parser.add_argument('--kind', nargs='+', choices=sorted(KINDS), default=['failed'])
    parser.add_argument('--round', type=int, default=0, help='only the Nth round of the log')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--engine', default=str(ROOT / 'bin/fever_battle/fever_battle.exe'))
    parser.add_argument('--config', default=str(ROOT / 'config.json'))
    parser.add_argument('--output')
    args = parser.parse_args()
    result = replay(str(Path(args.log).resolve()), args.kind, args.round, args.limit,
                    Path(args.engine).resolve(), Path(args.config).resolve())
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    else:
        print(text)


if __name__ == '__main__':
    main()
