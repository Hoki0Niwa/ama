"""Measured reward boundaries, final active input and causal landing checks."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'test'))
import test_fever_mode as fixtures
request, side, seed3, NATIVE, SOLO = fixtures.request, fixtures.side, fixtures.seed3, fixtures.NATIVE, fixtures.SOLO
from fever_battle.mode_engine import ModeBattleEngine, authorize_mode_reply
from fever_battle.uncertainty import choose


class ClockAwardTests(unittest.TestCase):
    setUp=fixtures.ModeTests.setUp
    event=fixtures.ModeTests.event
    chain=fixtures.ModeTests.chain
    enter=fixtures.ModeTests.enter
    def test_ignition_is_insufficient_for_renewal(self):
        self.enter(); self.event('seed', field=seed3(), seed_chain=5, seed_id=1)
        self.event('clock', remaining_frames=100, running=True)
        name=self.chain(8, frame=1)
        self.event('end', frame=101, chain=name)
        self.assertEqual(self.ref.players[0].remaining_frames,0)

    def test_chain_reward_at_end_and_all_clear_sixteen_frames_later(self):
        self.enter(); self.event('seed',field=seed3(),seed_chain=5,seed_id=1)
        self.event('clock',remaining_frames=100,running=True)
        name=self.chain(9,frame=1,all_clear=True)
        self.assertEqual(self.ref.players[0].remaining_frames,99)
        self.event('end',frame=50,chain=name)
        self.assertEqual(self.ref.players[0].remaining_frames,260)
        self.event('tick',frame=65)
        self.assertEqual(self.ref.players[0].remaining_frames,245)
        self.event('tick',frame=66)
        self.assertEqual(self.ref.players[0].remaining_frames,544)

    def test_delayed_full_clear_does_not_revive_expired_clock(self):
        self.enter(); self.event('seed',field=seed3(),seed_chain=5,seed_id=1)
        self.event('clock',remaining_frames=20,running=True)
        name=self.chain(1,frame=1,all_clear=True)
        self.event('end',frame=10,chain=name)
        self.event('tick',frame=26)
        self.assertEqual(self.ref.players[0].remaining_frames,0)


class DeadlineSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
    @classmethod
    def tearDownClass(cls): cls.engine.close()

    def test_current_piece_is_authorized_across_clock_zero(self):
        req=request(); req['self']['remaining_frames']=10
        reply=self.engine.answer(req)
        latest=copy.deepcopy(req); latest['frame']=10
        latest['observation'].update(frame_before=10,frame_after=10)
        for name in ('self','enemy'):latest[name]['observed_frame']=10
        latest['self']['remaining_frames']=0
        self.assertTrue(authorize_mode_reply(req,reply,latest))
        latest['self']['mode_generation']+=1
        with self.assertRaises(ValueError):authorize_mode_reply(req,reply,latest)

    def test_award_opportunity_requires_end_but_includes_new_time(self):
        req=request(); req['seed_options']['strategy']='quick'
        req['self']['remaining_frames']=350
        last=self.engine.answer(req)['seed_forecast']['path'][-1]
        self.assertTrue(last['completed_before_timeout'])
        self.assertGreater(last['time_reward_frames'],0)
        self.assertTrue(last['next_seed_input_fits'])
        req['self']['remaining_frames']=50
        last=self.engine.answer(req)['seed_forecast']['path'][-1]
        self.assertEqual(last['time_reward_frames'],0)

    def test_recorded_awards_and_landings_use_separate_verified_boundaries(self):
        report=json.loads((ROOT/'data/fever/baselines/2026-10-06-fever-deadlines.json').read_text(encoding='utf-8'))
        chain=[r for r in report['awards'] if r['exact_edge'] and r['old_link'] and not r['link']]
        self.assertEqual(len(chain),5)
        for r in chain:
            self.assertEqual(r['since_chain_end'],0)
            self.assertEqual(r['gain'],max(0,r['old_link']-2)*30)
        full=[r for r in report['awards'] if r['exact_edge'] and not r['old_link']]
        self.assertEqual([(r['gain'],r['since_chain_end']) for r in full],[(300,16),(300,16)])
        exact=[r for r in report['deliveries'] if r['exact_edge']]
        self.assertEqual(len(exact),22)
        self.assertTrue(all(r['source_chain_end'] for r in exact))
        drops=[r for r in report['drops'] if 'lock_to_check_without_split' in r]
        self.assertEqual(len(drops),7)
        self.assertEqual({r['lock_to_check_without_split'] for r in drops},{16})
        self.assertEqual({r['split_rows'] for r in drops},{0,6})
        self.assertTrue(any(r['exact_edge'] and r['chain']==8 and r['clock']==0
                            for r in report['expired_chain_ends']))

    def test_delivery_during_lock_check_is_considered_with_unknown_columns(self):
        own=side(); own['queue']=['2:RG']; own['unconfirmed']=own['normal_unconfirmed']=12
        events=[dict(type='end',frame=20)]
        result=choose(self.engine.native,self.engine.scoring,own,120,enemy_events=events)
        first=result['choice']
        self.assertEqual(first['dropped'],12)
        self.assertEqual(first['nuisance_check_at'],30)
        result=choose(self.engine.native,self.engine.scoring,own,120,enemy_events=[dict(type='end',frame=31)])
        self.assertEqual(result['choice']['dropped'],0)

    def test_final_chain_builds_on_visible_pieces_until_the_safe_last_ignition(self):
        req=request(side('fever',seed3(),['2:GG','2:RY','L:RRY']))
        req['self']['remaining_frames']=120
        forecast=self.engine.answer(req)['seed_forecast']
        self.assertEqual(forecast['choice']['chain'],0)
        self.assertGreater(len(forecast['path']),1)
        last=forecast['path'][-1]
        self.assertGreaterEqual(last['chain'],3)
        self.assertLess(last['fire_at']+8,120)
        self.assertGreater(last['end_at'],120)
        self.assertEqual(last['time_reward_frames'],0)
        from tools.verify_fever_extension import verify
        verify(self.engine.native,self.engine.scoring,req['self'],forecast)

    def test_small_failed_chain_does_not_replace_larger_final_chain_for_tiny_renewal(self):
        own=side('fever',fixtures.seed_with_small_green(),['2:GY'])
        own.update(seed_chain=5,seed_base=5,remaining_frames=230)
        # Solver alone (no stored-board comparison): the larger final chain stays.
        result=self.engine.seed_solver.solve(own,120,True,dict(strategy='extend',budget_ms=500,max_nodes=20000),
            match_id='mode-test')
        self.assertEqual(result['choice']['chain'],3)
        self.assertFalse(result['path'][-1]['next_seed_input_fits'])
        # In a battle nothing is carried to the normal board, so the under-target
        # fire that only lowers the next seed is not made at all.
        reply=self.engine.answer(request(own))
        self.assertEqual(reply['chain'],0)
        self.assertEqual(reply['reason'],'fever_end_without_pointless_fire')

    def test_fever_seed_includes_delivery_while_nonclearing_piece_is_settling(self):
        own=side('fever',queue=['2:RG'])
        own['unconfirmed']=own['fever_unconfirmed']=12
        own['garbage_phase']=None
        forecast=self.engine.seed_solver.solve(own,120,True,enemy_events=[dict(type='end',frame=20)])
        self.assertEqual(forecast['choice']['dropped'],12)
        self.assertEqual(forecast['pending_arrival_status'],'observed_enemy_chain_timeline')

    def test_six_row_split_delays_nuisance_eligibility_by_thirty_frames(self):
        own=side(queue=['2:RG'])
        own['field'][-6:]=['.#....']*6
        own['unconfirmed']=own['normal_unconfirmed']=6
        first=choose(self.engine.native,self.engine.scoring,own,120,
            allowed_placements={(0,'R')},enemy_events=[dict(type='end',frame=59)])['choice']
        self.assertEqual(first['nuisance_check_at'],60)
        self.assertEqual(first['dropped'],6)
        first=choose(self.engine.native,self.engine.scoring,own,120,
            allowed_placements={(0,'R')},enemy_events=[dict(type='end',frame=61)])['choice']
        self.assertEqual(first['dropped'],0)


if __name__=='__main__':unittest.main()
