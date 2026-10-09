"""What long unattended Fever battles show, read from the bridge's protocol-3 session logs.

python tools/analyze_fever_matches.py LOG [LOG ...] [--output REPORT.json]

One report with the measurements the open questions need (doc/WORK_LOG.md, 2026-10-08):
  matches            who lost each match and what each side did in it (main chains, Fever entries,
                     seeds fired at and below their level, nuisance taken)
  after_fever        returning from Fever with nuisance confirmed: how far the gauge got and how it ended
  under_a_packet     decisions on a normal board with nuisance pending, by packet size: main chain
                     fired whole, broken by a smaller clear, stacked on, drop taken
  constants          what the engine's estimates can be checked against: pieces per offset link,
                     what entering Fever with nuisance held led to, puyos per link of a main chain,
                     what a confirmed packet did to a normal board by its size against the room left
  timing             tools/analyze_fever_arrival.py on the same logs, and the bridge's notes
A match's loser is inferred from the last decisions (no placement left, or the middle columns full);
where neither side shows it the match is counted as unfinished. Logs from before 2026-10-08 13:00 lack
the opponent's side and what was held, and the parts that need them say so.
Offline reading of logs: it measures what happened between these two AIs, not what is best.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))
from analyze_fever_arrival import analyse as analyse_arrival, records          # noqa: E402
from fever_battle.mode_engine import ModeBattleEngine                            # noqa: E402


def spread(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    at = lambda share: values[int(share * (len(values) - 1))]
    return dict(n=len(values), p10=at(.1), median=at(.5), p90=at(.9), mean=round(statistics.mean(values), 1))


def bucket(value, edges):
    for edge in edges:
        if value <= edge:
            return f'<={edge}'
    return f'>{edges[-1]}'


class Boards:
    """The longest chain one trigger fires, by board (the engine's own measure), cached."""
    def __init__(self, engine):
        self.engine, self.cache = engine, {}

    def longest(self, text):
        if text not in self.cache:
            try:
                self.cache[text] = self.engine.native.ask(dict(op='holding', field=text.split('/')))['longest']
            except (ValueError, KeyError):
                self.cache[text] = None
        return self.cache[text]


def cells(text):
    return sum(c not in './#' for c in text)


def middle_height(text):
    rows = text.split('/')
    return max(sum(row[x] != '.' for row in rows) for x in (2, 3))


def rounds_of(log):
    """{round: {ai: [events in order]}}: decisions (with what was locked for them) of each side.

    Each AI's observer names the match with an id of its own and the same round number, so the two
    sides of a match meet under the round number. A round whose two sides do not overlap in frames
    (one observer counted a round the other did not) is left with the side that has it.
    """
    rounds = defaultdict(lambda: defaultdict(list))
    waiting = {}
    for d in log:
        kind, ai = d.get('auto'), d.get('ai')
        if kind == 'planning' and 'field' in d and d.get('decision_identity') and d.get('cache') != 'prepare':
            identity = d['decision_identity']
            number = identity['match_id'].rsplit('-round-', 1)[-1]
            entry = dict(d, frame=identity['frame'], match=identity['match_id'], lock=None)
            rounds['round-' + number][ai].append(entry)
            waiting[ai] = entry
        elif kind in ('locked', 'fire') and ai in waiting and waiting[ai]['pair'] == d.get('pair'):
            waiting[ai]['lock'] = d
    paired = {}
    for name, sides in rounds.items():
        spans = {ai: (events[0]['frame'], events[-1]['frame']) for ai, events in sides.items()}
        if len(spans) == 2:
            (a0, a1), (b0, b1) = spans.values()
            if min(a1, b1) - max(a0, b0) < 0.5 * min(a1 - a0, b1 - b0):
                for ai, events in sides.items():
                    paired[f'{name}-ai{ai}'] = {ai: events}
                continue
        paired[name] = sides
    return paired


def analyse(logs, boards):
    matches, after_fever, packets = [], [], defaultdict(Counter)
    offsets, entries, growth, hits = [], [], [], []
    notes = Counter()
    for log in logs:
        for d in log:
            if d.get('auto') in ('opponent chain not followed', 'surprise landing'):
                notes[d['auto'] + ((': ' + str(d.get('what'))) if d.get('what') else '')] += 1
        for match, sides in rounds_of(log).items():
            summary, lost = {}, {}
            for ai, events in sides.items():
                last = events[-1]
                lost[ai] = (last.get('reason') == 'no_rescue_fast_finish'
                            or (last['mode'] == 'normal' and middle_height(last['field']) >= 11))
                fires = [e['lock'] for e in events if e['lock'] and e['lock'].get('chain')]
                level = lambda e: (e.get('seed') or [None])[0]
                seeds = [(e['lock']['chain'], level(e)) for e in events
                         if e['mode'] == 'fever' and e['lock'] and e['lock'].get('chain') and level(e)]
                landed = sum(max(0, b['field'].count('#') - a['field'].count('#'))
                             for a, b in zip(events, events[1:]) if a['mode'] == b['mode'] == 'normal')
                summary[ai] = dict(decisions=len(events),
                    fever_entries=sum(a['mode'] == 'normal' and b['mode'] == 'fever' for a, b in zip(events, events[1:])),
                    first_fever_frame=next((e['frame'] for e in events if e['mode'] == 'fever'), None),
                    biggest_normal_chain=max((f['chain'] for f in fires if f.get('mode') == 'normal'), default=0),
                    biggest_fever_chain=max((f['chain'] for f in fires if f.get('mode') == 'fever'), default=0),
                    seeds_at_level=sum(c >= lv for c, lv in seeds), seeds_below_level=sum(c < lv for c, lv in seeds),
                    nuisance_landed=landed, last_reason=last.get('reason'))
            losers = [ai for ai, dead in lost.items() if dead]
            loser = losers[0] if len(losers) == 1 and len(sides) == 2 else None
            matches.append(dict(match=match[-12:], frames=max(e['frame'] for ev in sides.values() for e in ev),
                                loser=loser, sides=summary))
            for ai, events in sides.items():
                died = loser == ai
                # --- after a Fever, and decisions under a packet
                for i, e in enumerate(events):
                    if e['mode'] != 'normal':
                        continue
                    pending = e['nuisance'][0]
                    longest = boards.longest(e['field'])
                    if i and events[i-1]['mode'] == 'fever':
                        confirmed = (e.get('tray') or [pending, 0])[0]
                        run, end, top = events[i:], 'match ended', e['gauge']
                        for k, later in enumerate(run):
                            top = max(top, later['gauge'] if later['mode'] == 'normal' else 7)
                            if later['mode'] == 'fever':
                                end = 'entered Fever again'
                                break
                            if k and later['field'].count('#') > run[k-1]['field'].count('#'):
                                end = 'took a drop'
                                break
                            if k and later['nuisance'][0] == 0:
                                end = 'packet cleared'
                                break
                        else:
                            end = 'lost the match' if died else 'match ended'
                        after_fever.append(dict(confirmed=confirmed, puyos=cells(e['field']), longest=longest,
                            gauge_reached=top, end=end, lost_match=died))
                    if pending and longest is not None and e['lock'] is not None:
                        size = bucket(pending, (5, 29, 99, 299))
                        chain = e['lock'].get('chain', 0)
                        after = boards.longest(events[i+1]['field']) if i + 1 < len(events) and events[i+1]['mode'] == 'normal' else None
                        if longest >= 4 and chain >= longest - 1:
                            what = 'main chain fired whole'
                        elif longest >= 4 and chain and after is not None and after < longest - 1:
                            what = 'main chain broken by a smaller clear'
                        elif chain:
                            what = 'smaller clear, main chain kept' if longest >= 4 else 'clear, no main chain held'
                        elif i + 1 < len(events) and events[i+1]['field'].count('#') > e['field'].count('#'):
                            what = 'drop taken'
                        else:
                            what = 'stacked'
                        packets[size][what] += 1
                # --- pieces per offset link: stretches on the normal board with nuisance pending
                stretch = None
                for e in events + [None]:
                    under = e is not None and e['mode'] == 'normal' and e['nuisance'][0] > 0
                    if under:
                        stretch = stretch or dict(pieces=0, first=e['gauge'], last=e['gauge'])
                        stretch['pieces'] += 1
                        stretch['last'] = e['gauge']
                    elif stretch:
                        gained = (7 if e is not None and e['mode'] == 'fever' else stretch['last']) - stretch['first']
                        if stretch['pieces'] >= 3:
                            offsets.append(dict(pieces=stretch['pieces'], links=max(0, gained)))
                        stretch = None
                # --- entering Fever with nuisance held, and how it came out
                for i, e in enumerate(events):
                    if e['mode'] == 'fever' and i and events[i-1]['mode'] == 'normal' and e.get('held'):
                        held = sum(v or 0 for v in e['held'])
                        out = next((x for x in events[i:] if x['mode'] == 'normal'), None)
                        entries.append(dict(held=held, level=(e.get('seed') or [None])[0],
                            left_on_return=None if out is None else out['nuisance'][0], lost_match=died))
                # --- puyos per link of a main chain when it is fired
                for e in events:
                    if e['mode'] == 'normal' and e['lock'] and e['lock'].get('chain', 0) >= 4:
                        growth.append(dict(chain=e['lock']['chain'], puyos=cells(e['field']) + 2, piece=e['pair']))
                # --- a confirmed packet against the room left on a normal board
                for i, e in enumerate(events):
                    tray = e.get('tray')
                    if e['mode'] != 'normal' or not tray or not tray[0]:
                        continue
                    if i and events[i-1]['mode'] == 'normal' and (events[i-1].get('tray') or [0])[0]:
                        continue                # the first decision that sees it confirmed
                    room = 6 * max(0, 12 - middle_height(e['field']))
                    took, entered = 0, False
                    for k in range(i, min(i + 12, len(events) - 1)):
                        if events[k+1]['mode'] == 'fever':
                            entered = True
                            break
                        took += max(0, events[k+1]['field'].count('#') - events[k]['field'].count('#'))
                    hits.append(dict(packet=tray[0], room=room, gauge=e['gauge'], longest=boards.longest(e['field']),
                        took=took, entered_fever=entered, lost_match=died and i >= len(events) - 14))
    finished = [m for m in matches if m['loser']]
    both = lambda m, key, better: (lambda w, l: better(w[key], l[key]))(m['sides'][3 - m['loser']], m['sides'][m['loser']])
    def table(rows, key, edges, fields):
        out = {}
        for name in sorted({bucket(r[key], edges) for r in rows}, key=lambda t: (t[0] == '>', int(t.lstrip('<=>')))):
            part = [r for r in rows if bucket(r[key], edges) == name]
            out[name] = dict(n=len(part), **{f: fn(part) for f, fn in fields.items()})
        return out
    share = lambda rows, test: round(sum(1 for r in rows if test(r)) / len(rows), 3) if rows else None
    report = dict(
        matches=dict(n=len(matches), finished=len(finished), frames=spread([m['frames'] for m in finished]),
            lost_by_ai=dict(Counter(m['loser'] for m in finished)),
            winner_fired_the_bigger_normal_chain=sum(both(m, 'biggest_normal_chain', lambda a, b: a > b) for m in finished),
            loser_fired_the_bigger_normal_chain=sum(both(m, 'biggest_normal_chain', lambda a, b: a < b) for m in finished),
            winner_entered_fever_more_often=sum(both(m, 'fever_entries', lambda a, b: a > b) for m in finished),
            loser_entered_fever_more_often=sum(both(m, 'fever_entries', lambda a, b: a < b) for m in finished),
            loser_entered_fever_first=sum(both(m, 'first_fever_frame',
                lambda a, b: b is not None and (a is None or b < a)) for m in finished),
            per_side=dict(biggest_normal_chain=spread([s['biggest_normal_chain'] for m in matches for s in m['sides'].values()]),
                fever_entries=spread([s['fever_entries'] for m in matches for s in m['sides'].values()]),
                seeds_at_level=sum(s['seeds_at_level'] for m in matches for s in m['sides'].values()),
                seeds_below_level=sum(s['seeds_below_level'] for m in matches for s in m['sides'].values()),
                nuisance_landed=spread([s['nuisance_landed'] for m in matches for s in m['sides'].values()]))),
        after_fever=dict(returns=len(after_fever), by_confirmed_packet=table(after_fever, 'confirmed', (0, 29, 99, 299), dict(
            ends=lambda p: dict(Counter(r['end'] for r in p)), gauge_reached=lambda p: spread([r['gauge_reached'] for r in p]),
            puyos_on_return=lambda p: spread([r['puyos'] for r in p]), longest_chain_on_return=lambda p: spread([r['longest'] for r in p]),
            lost_the_match=lambda p: share(p, lambda r: r['lost_match'])))),
        under_a_packet={size: dict(counts) for size, counts in sorted(packets.items(),
            key=lambda item: (item[0][0] == '>', int(item[0].lstrip('<=>'))))},
        constants=dict(
            pieces_per_offset_link=dict(stretches=len(offsets), pieces=sum(o['pieces'] for o in offsets),
                links=sum(o['links'] for o in offsets),
                pieces_per_link=round(sum(o['pieces'] for o in offsets) / max(1, sum(o['links'] for o in offsets)), 2),
                engine_assumes=3),
            entering_fever_with_nuisance_held=(table(entries, 'held', (0, 50, 100, 200, 400), dict(
                left_on_return=lambda p: spread([r['left_on_return'] for r in p]),
                returned_with_30_or_less=lambda p: share([r for r in p if r['left_on_return'] is not None], lambda r: r['left_on_return'] <= 30),
                lost_the_match=lambda p: share(p, lambda r: r['lost_match']))) if entries
                else 'needs logs that carry what was held (2026-10-08 13:00 on)'),
            engine_takes_as_within_a_fevers_reach=100,
            puyos_per_link_of_a_fired_main_chain=dict(n=len(growth),
                puyos_per_link=spread([round(g['puyos'] / g['chain'], 2) for g in growth]),
                chain=spread([g['chain'] for g in growth]), engine_assumes_puyos_for_one_more_link=6),
            confirmed_packet_against_room=(table([dict(h, ratio=round(100 * h['packet'] / max(1, h['room']))) for h in hits],
                'ratio', (25, 50, 100, 200), dict(
                    took=lambda p: spread([r['took'] for r in p]), entered_fever=lambda p: share(p, lambda r: r['entered_fever']),
                    lost_within_14_decisions=lambda p: share(p, lambda r: r['lost_match']),
                    by_gauge=lambda p: {g: dict(n=len(q), entered_fever=share(q, lambda r: r['entered_fever']),
                                                lost=share(q, lambda r: r['lost_match']))
                        for g, q in (('gauge 0-3', [r for r in p if r['gauge'] <= 3]), ('gauge 4-6', [r for r in p if r['gauge'] >= 4])) if q}))
                if hits else 'needs logs that carry the tray (2026-10-08 on)'),
            note='ratio: the confirmed packet as a percentage of what fills the board (whole rows to the top of the middle columns).'),
        timing=dict(notes=dict(notes), arrival=analyse_arrival(logs)))
    return report, matches


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('logs', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    args = parser.parse_args()
    logs = [log for log in map(records, args.logs) if log]
    engine = ModeBattleEngine(args.native, ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    try:
        report, matches = analyse(logs, Boards(engine))
    finally:
        engine.close()
    report['logs'] = dict(read=len(logs), skipped_not_fever_battle=len(args.logs) - len(logs))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.output:
        args.output.write_text(json.dumps(dict(report=report, matches=matches), ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
