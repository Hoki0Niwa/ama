"""Why did the tactical search stack on the trigger of a held 12 chain? (round-44, AI 2, frame 1602)

python tools/investigate_round44_burial.py LOG [--native bin/x/fever_battle.exe ...] [--round round-44]

The log is the bridge's input-session.log of 2026-10-14 02:05-08:02 (doc/OVERNIGHT_LOG_ANALYSIS_2026-10-14.md).
The request is rebuilt from what the log keeps of that decision: the loser's board, queue and pending
nuisance, the winner's board, and the trigger board of the winner's 11 chain (the locked board of its
decision at 1516). Not in the log and put here: the frame the chain's first link was seen (1580, which
gives the log's chain_end_in 825 within 2 frames) and the opponent's piece ids. With the default native the
reply is the logged one (3U, tactics_stack).

Prints every candidate of the search by value: the placement, its value, its chain, the main-chain links
the search charged it, and the chain the board holds after it (the engine's `holding`).
"""
import argparse
import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))
from analyze_fever_arrival import records                                   # noqa: E402
from analyze_fever_matches import rounds_of                                 # noqa: E402
from fever_battle.mode_engine import ModeBattleEngine                       # noqa: E402


def request_of(log, round_name, frame, template, onset):
    rounds = rounds_of(log)
    sides = rounds[round_name]
    loser = next(e for ai, ev in sides.items() for e in ev if e['frame'] == frame)
    ai = loser['ai']
    winner_ai = 3 - ai
    fire = next(e for e in sides[winner_ai] if e['mode'] == 'normal' and e['lock'] and (e['lock'].get('chain') or 0) >= 10)
    after = next(e for e in sides[winner_ai] if e['frame'] > fire['frame'])
    return loser, fire, after, onset


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log', type=Path)
    parser.add_argument('--native', type=Path, nargs='*', default=[ROOT/'bin/fever_battle/fever_battle.exe'])
    parser.add_argument('--round', default='round-44')
    parser.add_argument('--frame', type=int, default=1602)
    parser.add_argument('--onset', type=int, default=1580, help='frame the first link of the opponent chain was seen')
    parser.add_argument('--top', type=int, default=9)
    args = parser.parse_args()
    log = list(records(args.log))
    template = next(d['request'] for d in log if d.get('auto') == 'surprise landing')
    loser, fire, after, onset = request_of(log, args.round, args.frame, template, args.onset)
    for native in args.native:
        engine = ModeBattleEngine(native, ROOT/'bin/fever/fever.exe', ROOT/'config.json')
        try:
            place = engine.native.ask(dict(op='placements', field=fire['field'].split('/'), piece=fire['queue'][0]))['placements']
            move = next(p for p in place if (p['x'], p['r']) == (fire['lock']['x'], fire['lock']['r']))
            trigger = move['locked_field']
            prediction = engine._prediction('rafisol', trigger, 'normal')
            q = copy.deepcopy(template)
            frame = loser['frame']
            q.update(match_id='burial-repro', frame=frame,
                     observation=dict(frame_before=frame, frame_after=frame, match_status='running'))
            identity = loser['decision_identity']
            unconfirmed = loser['nuisance'][0]
            q['self'].update(field=loser['field'].split('/'), queue=loser['queue'], piece_id=identity['piece_id'],
                dropset_index=identity['dropset_index'], board_observed_frame=frame, observed_frame=frame,
                confirmed=0, unconfirmed=unconfirmed, normal_unconfirmed=unconfirmed, moves_since_chain=16)
            q['enemy'].update(field=loser['enemy']['field'].split('/'), queue=after['queue'],
                piece_id=after['decision_identity']['piece_id'], dropset_index=after['decision_identity']['dropset_index'],
                observed_frame=frame, board_observed_frame=frame, phase='chain')
            q['enemy_chain'] = dict(trigger_field=trigger, start_frame=onset, observed_link_frame=onset, observed_link=1,
                scored_links=1, onset_frame_status='exact_edge', mode_generation=0, seed_id=0,
                first_link_points=prediction['points'][0], elapsed=frame-onset)
            q['active_placement'] = dict(x=2, r='U')
            q['decision_budget_ms'] = 100
            reply = engine.answer(dict(q, op='think'))
            forecast = reply['tactics_forecast']
            rows = loser['field'].split('/')
            after_main = {}
            for p in engine.native.ask(dict(op='placements', field=rows, piece=loser['queue'][0]))['placements']:
                after_main[(p['x'], p['r'])] = engine.native.ask(dict(op='holding', field=p['field']))['longest']
            print(f"== {native}")
            print(f"logged: {loser['move']} {loser['reason']}; chain_end_in {reply['arrival']['chain_end_in']} (log {loser['arrival']['chain_end_in']})")
            print(f"board holds {engine.native.ask(dict(op='holding', field=rows))['longest']}; replied {reply['x']}{reply['r']} {reply['reason']}")
            for c in sorted(forecast['candidates'], key=lambda c: -c['value'])[:args.top]:
                print(f"  {c['x']}{c['r']}  value {c['value']:>7}  chain {c['chain']:>2}  links charged {c['main_links_lost']:>2}"
                      f"  held after {after_main.get((c['x'], c['r']))}")
        finally:
            engine.close()


if __name__ == '__main__':
    main()
