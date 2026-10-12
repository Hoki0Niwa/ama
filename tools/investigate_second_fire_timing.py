"""Read-only probes of second-chain timing; never controls a game session."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle import tactics
from fever_battle.uncertainty import choose


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, default=ROOT/'bin/fever_battle/fever_battle.exe')
    parser.add_argument('--log', type=Path, default=Path('C:/Users/ho_ki/git/ama-memory-bridge/observations/input-session.log'))
    parser.add_argument('--output', type=Path, default=ROOT/'data/fever/baselines/2026-10-11-second-fire-timing-investigation.json')
    args = parser.parse_args()
    raw = args.log.read_bytes()
    records = [json.loads(line) for line in raw.decode('utf-16').splitlines() if line.startswith('{')]
    engine = ModeBattleEngine(args.native.resolve(), ROOT/'bin/fever/fever.exe', ROOT/'config.json')
    plans = {}; fires = []; characters = {}
    for ai in (1, 2):
        ps = [p for p in records if p.get('auto') == 'planning' and p.get('decision_identity') and p['ai'] == ai]
        characters[ai] = [c for c, pattern in engine.patterns.items() if all(all(
            pattern[(p['decision_identity']['dropset_index']+k)%16] == v[0] for k, v in enumerate(p['queue'])) for p in ps)]
    for row in records:
        key = row.get('ai'), row.get('pair')
        if row.get('auto') == 'planning' and row.get('field'):
            plans[key] = row
        elif row.get('auto') == 'fire' and row.get('mode') == 'normal' and key in plans:
            fires.append(dict(plan=plans[key], lock=row))
    report = dict(native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
        bridge_log_sha256=hashlib.sha256(raw).hexdigest(), log_process_binary_unknown=True,
        exact_protocol_replay=False, cycle_compatible_characters=characters, fires=fires, probes=[])
    try:
        for ai, pair in ((2, 57), (2, 58), (1, 61)):
            p = plans[ai, pair]
            character = characters[ai][0]
            own = dict(character=character, field=p['field'].split('/'), queue=p['queue'],
                confirmed=p['nuisance'][0], unconfirmed=p['nuisance'][1], remainder=0,
                garbage_phase=None, gauge=p['gauge'], moves_since_chain=0,
                piece_id=pair, dropset_index=p['decision_identity']['dropset_index'],
                mode_generation=p['decision_identity']['mode_generation'], seed_id=p['decision_identity']['seed_id'],
                normal_chain_max=p['normal_chain_max'], normal_confirmed=0, normal_unconfirmed=0, mode='normal')
            enemy = dict(mode='fever', normal_confirmed=p['enemy']['held'][0], normal_unconfirmed=p['enemy']['held'][1],
                fever_confirmed=p['enemy']['tray'][0], fever_unconfirmed=p['enemy']['tray'][1], remainder=0)
            options = engine._normal_options(dict(second_target_chain=14, enemy=enemy, gauge_gain_on_offset=1,
                solo_options=dict(beam_width=150, beam_depth=8)), own)
            build = engine._solo_build(own, options)
            moves = engine.native.ask(dict(op='placements', field=own['field'], piece=own['queue'][0]))['placements']
            actual_build = next(m for m in moves if (m['x'], m['r']) == (build['x'], build['r']))
            sample = dict(ai=ai, pair=pair, character_assumption=character, own=deepcopy(own), enemy=deepcopy(enemy), options=options,
                occupied=sum(c!='.' for r in own['field'] for c in r), stack_full=engine._stack_full(own, options),
                build=build, build_actual_chain=len(actual_build['links']), variants=[])
            # Timelines below are explicit sensitivity probes, not the missing live protocol input.
            for label, events in (
                    ('no_future_events', []),
                    ('only_chain_end', [dict(type='end', frame=p['arrival']['chain_end_in'])]),
                    ('large_tail_late', [dict(type='link', frame=650, points=62400), dict(type='end', frame=672)]),
                    ('large_tail_now', [dict(type='link', frame=0, points=62400), dict(type='end', frame=0)])):
                uncertain = choose(engine.native, engine.scoring, own, 120, enemy=enemy, enemy_events=events)
                policy = deepcopy(engine.policy['normal_tactics'])
                policy.update(budget_ms=0, main_trigger_points=40*sum(engine.scoring.data['characters'][character]['normal'][:14]))
                result = tactics.choose(engine.native, engine.scoring, own, 120, 1, policy,
                    enemy_events=events, enemy=enemy, builder=(build['x'],build['r']), builder_fire=build['fire'],
                    fever=dict(enemy_fever=True, their_end=p['arrival']['chain_end_in'],
                        enemy_reply_nuisance=p['fever_disruption']['enemy_reply_nuisance']),
                    enemy_hold=p.get('tactics',{}).get('enemy_hold',486) if p.get('tactics') else 486)
                sample['variants'].append(dict(name=label, events=events, uncertainty=uncertain, tactics=result))
                u = uncertain['choice']; t = (result or {}).get('tactics_forecast',{}).get('choice',{})
                print(ai,pair,label,'uncertainty',u['chain'],u['pending_after_observed_chains'],
                    'tactics',t.get('chain'),t.get('gauge_after'),t.get('projected_gauge'),t.get('known_exchange_pending'),t.get('survives'))
            report['probes'].append(sample)
            if ai == 1 and pair == 61:
                # Run the real normal dispatcher with a declared end-only timeline.
                # Replace only the opponent analysis, whose protocol fields the live log omits.
                originals = {name:getattr(engine,name) for name in (
                    '_enemy_events','_enemy_fever','_enemy_defense','_enemy_hold')}
                end_only = [dict(type='end', frame=0)]
                enemy.update(mode_generation=1, seed_id=1)
                engine._enemy_events = lambda *a, **k: end_only
                engine._enemy_fever = lambda *a, **k: dict(enemy_fever=True, their_end=0, enemy_reply_nuisance=428)
                engine._enemy_defense = lambda *a, **k: dict(hold=428,kill=0,links=0,need=7)
                engine._enemy_hold = lambda *a, **k: 486
                req = dict(second_target_chain=14, enemy=enemy, gauge_gain_on_offset=1,
                    solo_options=dict(beam_width=150, beam_depth=8),
                    enemy_chain=dict(mode_generation=1,seed_id=1))
                try:
                    for phase in (None, 0):
                        own['garbage_phase'] = phase
                        reply = engine._normal(req, own, enemy, 120)
                        report.setdefault('normal_dispatch_probe',[]).append(dict(
                            declared_timeline=end_only, unknown_phase=phase is None,
                            opponent_analysis_isolated=True, reply=reply))
                        print('normal dispatcher',phase,reply['reason'],reply['chain'])
                    own['garbage_phase'] = None
                    req['enemy_chain'] = None
                    reply = engine._normal(req, own, enemy, 120)
                    report['normal_dispatch_probe'].append(dict(declared_timeline=end_only,
                        unknown_phase=True, chain_metadata_present=False,
                        opponent_analysis_isolated=True, reply=reply))
                    print('normal dispatcher no chain metadata',reply['reason'],reply['chain'])
                finally:
                    for name, method in originals.items(): setattr(engine,name,method)
        # Absent/default/explicit second target changes only the policy input.
        report['target_option_probe'] = []
        for label, update in (('absent',{}),('null',dict(second_target_chain=None)),('14',dict(second_target_chain=14))):
            req = dict(enemy=enemy, gauge_gain_on_offset=1, **update)
            opt = engine._normal_options(req, own)
            report['target_option_probe'].append(dict(input=label, options=opt))
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:
        engine.close()


if __name__ == '__main__':
    main()
