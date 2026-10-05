"""Garbage is a state transition, including future chain links and offset timing."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fever_battle.model import EMPTY, GARBAGE_ORDER, Referee, Scoring, drop_garbage, dead
from fever_battle.forecast import GarbageSearch
from fever_battle.timing import ChainTiming, predict_chain
from fever_battle.threat import ChainPrediction
from fever_battle.worker import JsonProcess


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = JsonProcess([ROOT/'bin/fever_battle/fever_battle.exe'], cwd=ROOT)
        cls.search = GarbageSearch(cls.native, ROOT/'config.json')

    @classmethod
    def tearDownClass(cls):
        cls.native.close()

    def forecast(self, count=0, phase=0, rows=None, queue=None, **kwargs):
        return self.search.search('raffina', rows or list(EMPTY), queue or ['2:RG','L:BBY','4:GGYY'],
                                  count, 0, 0, 120, phase, width=25, **kwargs)

    def replay_path(self, result, count, phase):
        rows = list(EMPTY)
        for piece, step in zip(['2:RG','L:BBY','4:GGYY'], result['path']):
            transition = self.native.ask(dict(op='transition',field=rows,piece=piece,x=step['x'],r=step['r']))
            rows = transition['field']
            self.assertEqual(rows, step['placement_field'])
            if not transition['links']:
                amount = min(30, count)
                rows, _ = drop_garbage(rows, amount, phase)
                count -= amount
                phase = (phase + amount) % 6
            else:
                for points in Scoring().chain('raffina', transition['links']):
                    count = max(0, count-max(1 if count else 0, points//120))
            self.assertEqual(rows, step['field'])
            self.assertEqual(step['confirmed'],count)
            self.assertEqual(step['garbage_phase'],phase)
            self.assertFalse(dead(rows))

    def test_native_transitions_all_amounts_and_start_positions(self):
        for phase in range(6):
            for count in range(31):
                result = self.forecast(count, phase, queue=['2:RG'])
                step = result['choice']
                rows, _ = drop_garbage(step['placement_field'], count, phase)
                self.assertEqual(step['field'],rows)
                self.assertEqual(step['garbage_phase'],(phase+count)%6)

    def test_repeated_falls_resume_after_last_puyo(self):
        ref=Referee(['raffina','ally'])
        def place(order,count):
            ref.apply(dict(type='incoming',player=0,frame=order,order=0,count=count,confirmed=True,chain=str(order)))
            return ref.apply(dict(type='place',player=0,frame=order,order=1,result=dict(field=ref.players[0].rows,links=[])))
        place(1,4)
        effect=place(2,1)
        self.assertEqual(effect['garbage_phase'],5)
        self.assertEqual(ref.players[0].rows[-1], '####.#')
        place(3,8)
        self.assertEqual(ref.players[0].garbage_phase,1)

    def test_backlog_and_reachable_next_moves_use_landed_board(self):
        result=self.forecast(37,4)
        self.assertEqual(result['choice']['dropped'],30)
        self.assertEqual(result['choice']['confirmed'],7)
        self.replay_path(result,37,4)
        self.assertTrue(result['horizon_complete'])

    def test_unscheduled_unconfirmed_is_not_falsely_dropped(self):
        result=self.search.search('raffina',EMPTY,['2:RG'],0,30,0,120,2)
        self.assertEqual(result['choice']['dropped'],0)
        self.assertEqual(result['choice']['garbage_phase'],2)

    def test_known_chain_end_changes_later_search_board_before_it_ends(self):
        timing=ChainTiming(placement_frames=10,spawn_frames=0)
        events=[dict(type='link',frame=5,points=1200),dict(type='end',frame=15)]
        result=self.forecast(0,3,queue=['2:RG','2:BY','2:GY'],enemy_events=events,timing=timing)
        self.assertEqual(result['path'][0]['dropped'],0)
        self.assertEqual(result['path'][0]['unconfirmed'],10)
        self.assertEqual(result['path'][1]['dropped'],10)
        self.assertEqual(result['path'][1]['garbage_phase'],1)
        self.assertEqual(sum(r.count('#') for r in result['path'][1]['field']),10)

    def test_opponents_offset_reduces_predicted_attack(self):
        events=[dict(type='link',frame=0,points=1200),dict(type='end',frame=0)]
        result=self.forecast(enemy_events=events,enemy_confirmed=6,queue=['2:RG'])
        self.assertEqual(result['choice']['dropped'],4)

    def test_own_offset_cannot_cancel_future_unscored_links(self):
        rows=list(EMPTY); rows[-1]='RRRBBB'
        for y in range(3,13): rows[y]='..##..'
        # Huge confirmed backlog forces clearing. The later opposing score is
        # outside our own chain: it must not be cancelled by this clear.
        timing=ChainTiming(pop_frames=1,settle_frames=0,spawn_frames=0,placement_frames=1,fall_frames_per_row=0,
                           split_extra_frames=(0,)*14)
        result=self.forecast(100,1,rows=rows,queue=['2:RG','2:BY'],timing=timing,
            enemy_events=[dict(type='link',frame=3,points=1200),dict(type='end',frame=3)])
        first=result['choice']
        self.assertTrue(first['links'])
        self.assertEqual(first['cancelled'],1)
        self.assertEqual(first['confirmed'],99)
        self.assertEqual(first['garbage_phase'],1)

    def test_geometry_accounts_for_garbage_removed_below_survivors(self):
        rows=list(EMPTY); rows[-1]='RRRR#.';rows[-2]='....B.'
        prediction=predict_chain(self.native,Scoring(),'raffina',rows)
        self.assertEqual(prediction['links'][0]['fall_distance'],1)
        self.assertEqual(prediction['points'],[40])
        self.assertEqual(prediction['end_frame'],70)
        self.assertEqual(prediction['ready_frame'],83)
        self.assertEqual(prediction['field'][-1],'....B.')

    def test_chain_start_prediction_does_not_duplicate_scored_links(self):
        transition=dict(links=[dict(groups=[4],colors=1)]*3,fall_distances=[0,2,1])
        prediction=ChainPrediction('chain-id','raffina',transition,Scoring(),100)
        events=prediction.remaining(150,1)
        self.assertEqual([e['points'] for e in events if e['type']=='link'],[320,680])
        self.assertEqual(events[-1]['type'],'end')
        self.assertEqual(prediction.prediction['total_points'],1040)

    def test_observed_link_onset_reanchors_future_scores(self):
        transition=dict(links=[dict(groups=[4],colors=1)]*3,fall_distances=[0,2,1])
        prediction=ChainPrediction('chain-id','raffina',transition,Scoring(),100)
        self.assertEqual(prediction.prediction['links'][0]['score_at'],0)
        prediction.observe_link(175,2)
        events=prediction.remaining(180,2)
        self.assertEqual(events[0],dict(type='link',frame=65,points=680))
        self.assertEqual(prediction.prediction['total_points'],1040)

    def test_split_geometry_and_elapsed_time_match_measured_table(self):
        timing=ChainTiming()
        for distance in range(9):
            rows=list(EMPTY)
            for y in range(distance):rows[13-y]='.#....'
            transition=self.native.ask(dict(op='transition',field=rows,piece='2:RG',x=0,r='R'))
            self.assertEqual(transition['split_distances'],[distance,0])
            vertical=self.native.ask(dict(op='transition',field=rows,piece='2:RG',x=0,r='U'))
            self.assertEqual(vertical['split_distances'],[0])
            result=self.forecast(rows=rows,queue=['2:RG'],timing=timing)
            step=result['choice']
            geometry=self.native.ask(dict(op='transition',field=rows,piece='2:RG',x=step['x'],r=step['r']))
            expected=timing.split_extra_frames[max(geometry['split_distances'])]
            self.assertEqual(step['split_extra_frames'],expected)
            self.assertEqual(step['frame'],timing.placement_frames+expected)

    def test_all_clear_stops_at_unknown_seed(self):
        rows=list(EMPTY);rows[-1]='RR....'
        result=self.forecast(30,2,rows=rows,queue=['2:RR','2:BY'])
        self.assertTrue(result['stopped_at_unknown_seed'])
        self.assertEqual(result['completed_moves'],1)
        self.assertFalse(result['horizon_complete'])

    def test_calibrated_chain_clock_matches_all_recorded_intervals_and_terminal_ready(self):
        data=json.loads((ROOT/'data/fever/baselines/2026-10-05-timing-extended.json').read_text(encoding='utf8'))
        terminal=json.loads((ROOT/'data/fever/baselines/2026-10-05-timing-calibration.json').read_text(encoding='utf8'))
        clock=ChainTiming()
        for link in data['links']:
            predicted=clock.duration(link['max_fall'],link)
            self.assertLessEqual(abs(predicted-link['duration_frames']),2)
        for link in terminal['terminals']:
            predicted=clock.duration(link['max_fall'],link,terminal=True)+13
            self.assertLessEqual(abs(predicted-link['duration_frames']),2)

    def test_native_chain_uses_geometry_clock_and_lock_to_first_link_delay(self):
        rows=list(EMPTY);rows[-1]='RR....';rows[-2]='B.....'
        result=self.forecast(30,2,rows=rows,queue=['2:RR'])
        step=result['choice']
        features=step['fall_features']
        durations=[ChainTiming().duration(f['max_fall'],f,terminal=i==len(features)-1)
                   for i,f in enumerate(features)]
        self.assertEqual(step['frame'],14+step['split_extra_frames']+15+sum(durations))
        self.assertEqual(step['chain_timing_source'],'steam_15209927_calibrated_estimate')

    def test_lock_prediction_waits_for_split_and_first_onset_then_reanchors(self):
        transition=dict(links=[dict(groups=[4],colors=1)]*2,
                        fall_distances=[2,0],split_distances=[1,0])
        prediction=ChainPrediction('lock','raffina',transition,Scoring(),100,start_is_lock=True)
        self.assertEqual(prediction.prediction['links'][0]['score_at'],28)
        self.assertEqual(prediction.remaining(105,0)[0]['frame'],23)
        prediction.observe_link(128,1)
        self.assertEqual(prediction.remaining(130,1)[0]['frame'],68)


if __name__=='__main__': unittest.main(verbosity=2)
