"""Read-only reproductions of current disruption scoring and timing guards."""
import argparse
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import side,request,seed3,seed_with_small_green,NATIVE
from fever_battle.mode_engine import ModeBattleEngine,identity,authorize_mode_reply
from fever_battle import tactics
from fever_battle import disruption


def investigate(log):
    engine=ModeBattleEngine(NATIVE,ROOT/'bin/fever/fever.exe',ROOT/'config.json')
    report={'kind':'source investigation and offline reproductions; no game input',
            'native_sha256':hashlib.sha256(NATIVE.read_bytes()).hexdigest(),
            'amount_cases':[]}
    try:
        seeds=json.loads((ROOT/'data/fever/seeds/namoko-reference.json').read_text(encoding='utf-8'))
        rows=list(next(s['field'] for s in seeds['seeds'] if s['id']=='hirazumi-7'))
        rows[4:7]=['Y.....']*3
        own=side('normal',rows,['2:YG']);own['character']='arle'
        report['no_attack_cases']=[]
        for label,board,piece,known in (
            ('large_board_known_end',rows,'2:YG',True),
            ('small_board_known_end',seed_with_small_green(),'2:GY',True),
            ('large_board_unknown_end',rows,'2:YG',False)):
            probe=side('normal',board,[piece]);probe['character']='arle'
            args=dict(enemy=side('fever',seed3()),allowed=[dict(x=0,r='U')],
                defense=dict(hold=0,kill=0,links=0,need=7),fever=dict(enemy_fever=True))
            raw=tactics.choose(engine.native,engine.scoring,probe,30,1,engine.policy['normal_tactics'],**args)
            duration=raw['tactics_forecast']['choice']['attack_end']
            if known:
                args['fever']['their_end']=duration
                args['enemy_events']=[dict(type='end',frame=duration)]
            raw=tactics.choose(engine.native,engine.scoring,probe,30,1,engine.policy['normal_tactics'],**args)
            quiet=tactics.choose(engine.native,engine.scoring,probe,30,1,engine.policy['normal_tactics'],quiet=True,**args)
            choice=raw['tactics_forecast']['choice']
            report['no_attack_cases'].append(dict(case=label,known_end=known,quiet_selected=quiet is not None,
                **{k:choice[k] for k in ('chain','sent','attack_end','attack_kind','remaining_cells','all_clear','projected_disrupt')}))
        report['building_seed_target']=engine._enemy_fever(side('fever',seed3()),[])
        for rate,hold in ((30,0),(3,0),(30,1000)):
            result=tactics.choose(engine.native,engine.scoring,own,rate,1,engine.policy['normal_tactics'],
                enemy=side('fever',seed3()),allowed=[dict(x=0,r='U')],
                defense=dict(hold=hold,kill=0,links=0,need=7),
                fever=dict(enemy_fever=True,their_end=105,enemy_reply_nuisance=1000),enemy_events=[dict(type='end',frame=105)])
            choice=result['tactics_forecast']['choice']
            report['amount_cases'].append(dict(rate=rate,enemy_hold=hold,**{k:choice[k] for k in
                ('chain','sent','attack_end','projected_disrupt','value','remaining_cells','enemy_trays')}))
        enemy=side('fever',seed3());enemy.update(awaiting_seed=True,fever_entry_frame=0,observed_frame=80)
        req=request(side('normal'),enemy);req.update(frame=80,observation=dict(frame_before=80,frame_after=80,match_status='running'))
        req['self']['observed_frame']=80
        old=dict(fire=True,reason='tactics_disrupt',tactics_forecast=dict(choice=dict(projected_disrupt=1,attack_end=100,disruption_kind='jab'),disrupt_window=122))
        original_time=deepcopy(req);original_time['frame']=0
        old['disruption_timing']=disruption.contract(original_time,old,dict(their_end=0,disrupt_window=122))
        target=engine._enemy_fever(enemy,[])
        report['entry_window_reuse']=dict(current_target=target,attack_duration=100,stored_window=122,
            accepted=engine._prepared_delivery_stable(req,req['self'],enemy,old),
            fits_current_window=target['their_end']<=100<=target['their_end']+target['disrupt_window'])
        original=request(side('normal'),side('fever',seed3()))
        latest=deepcopy(original);latest.update(frame=150,observation=dict(frame_before=150,frame_after=150,match_status='running'))
        latest['self']['observed_frame']=latest['enemy']['observed_frame']=150
        latest['enemy'].update(seed_id=2,seed_chain=4,field=['......']*14)
        reply=dict(action='place',decision_identity=identity(original),fire=True,chain=1,reason='tactics_disrupt',
            tactics_forecast=dict(choice=dict(projected_disrupt=1,attack_end=100,disruption_kind='jab'),enemy_seed_at=100,disrupt_window=26))
        reply['disruption_timing']=disruption.contract(original,reply,dict(their_end=100,disrupt_window=26))
        try: early_accepted=authorize_mode_reply(original,reply,latest)
        except ValueError: early_accepted=False
        report['early_timing_guard']=dict(elapsed=150,enemy_seed_changed=True,
            accepted=early_accepted)
        report['signature_without_enemy_chain']=dict(enemy_seed_changed=True,
            same=engine._signature(original,original['self'])==engine._signature(latest,latest['self']))
        seed_reply=dict(fire=True,seed_forecast=dict(choice=dict(end_at=100,disruption_kind='jab')))
        seed_reply['disruption_timing']=disruption.contract(original_time,seed_reply,dict(their_end=0,disrupt_window=122))
        report['seed_fire_timing_guard']=dict(accepted=engine._prepared_delivery_stable(req,req['self'],enemy,seed_reply))
        own['queue']=['2:YG','2:GB','2:GB']
        entering=side('fever',seed3())
        entering.update(awaiting_seed=True,fever_entry_frame=0,phase='waiting_seed',seed_chain=15)
        before=request(own,entering);before['target_point']=3
        # Isolate the tactics override from the builder's choice. The tactics
        # search and both prepare/think requests use the real current engine.
        with patch.object(engine.solo,'ask',return_value=dict(x=5,r='U')):
            prepared=engine.answer(dict(before,op='prepare_observed'))
        now=deepcopy(before)
        now.update(frame=80,observation=dict(frame_before=80,frame_after=80,match_status='running'))
        now['self']['observed_frame']=now['enemy']['observed_frame']=80
        now['enemy']['remaining_frames']-=80
        reused=engine.answer(now)
        target=engine._enemy_fever(now['enemy'],[])
        forecast=reused.get('tactics_forecast',{})
        report['real_prepare_reuse']=dict(prepared=prepared['prepared'],reused=reused.get('search_reused',False),
            reason=reused['reason'],chain=reused['chain'],elapsed=80,
            attack_end=forecast.get('choice',{}).get('attack_end'),current_window=target['disrupt_window'],
            stored_window=forecast.get('disrupt_window'))
    finally:engine.close()
    if log:
        text=Path(log).read_text(encoding='utf-16')
        events=[]
        for line in text.splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
        plans=[r for r in events if r.get('auto')=='planning' and 'move' in r]
        shots=[r for r in plans if r.get('reason')=='tactics_disrupt']
        selected=[]
        for r in shots:
            fired=next((x for x in events if x.get('auto')=='fire' and x.get('ai')==r['ai'] and
                        x.get('pair')==r['pair'] and r['t']<=x.get('t',0)<=r['t']+3),None)
            selected.append(dict(planning=r,fire=fired))
        report['log']=dict(source=str(log),plans=len(plans),disruptions=len(shots),cases=selected,
            binary_version='not recorded; log ends before gauge-final.exe installation',
            limitation='The log does not record actual nuisance landing or the time of every chain link.')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=investigate(args.log)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='log'},ensure_ascii=False))
