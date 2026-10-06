"""The consumed seed request must not hide early failed clears."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.analyze_fever_watch import behaviour


class WatchTests(unittest.TestCase):
    def packets(self, level=5, requested=0):
        side=dict(player_state=1,target_point=120,total_score=0,mode='fever',
                  link=0,seed_requested_chain=requested,seed_last_chain=level,
                  normal_nuisance=dict(confirmed=10,unconfirmed=0),raw_clock_frames=100,
                  queue=dict(index=2),mode_phase=2,settled_field=['......']*14,
                  fever_nuisance=dict(confirmed=0,unconfirmed=0),field_phase=0,active=dict(placed=1))
        result=[]
        for frame,link,index in ((100,0,2),(101,1,2),(102,3,2),(103,0,2),(104,0,3)):
            current=copy.deepcopy(side)
            current.update(link=link,raw_clock_frames=200-frame)
            current['queue']['index']=index
            result.append(dict(event='sample',frame_before=frame,frame_after=frame,
                               players=[current,dict(unreadable='opponent')]))
        return result

    def test_last_seed_level_identifies_failure_after_requested_level_is_consumed(self):
        for requested in (0,12):
            with patch('tools.analyze_fever_watch.records',return_value=iter(self.packets(requested=requested))):
                cases=behaviour(['closed.jsonl.gz'])['failed_chains_with_held_nuisance']
            self.assertEqual(len(cases),1)
            self.assertEqual((cases[0]['chain'],cases[0]['target']),(3,5))
            self.assertTrue(cases[0]['next_seed_observed'])
            self.assertEqual(cases[0]['next_seed_frame'],104)

    def test_unknown_playing_seed_level_is_not_invented_from_a_future_request(self):
        with patch('tools.analyze_fever_watch.records',return_value=iter(self.packets(level=0,requested=12))):
            cases=behaviour(['closed.jsonl.gz'])['failed_chains_with_held_nuisance']
        self.assertEqual(cases,[])

    def test_fever_garbage_animation_ends_when_same_placed_counter_next_piece_is_operable(self):
        packets=self.packets()[:1]
        packets[0]['players'][0]['fever_nuisance']['confirmed']=30
        for frame,phase in ((101,10),(171,13),(172,0)):
            packet=copy.deepcopy(packets[0]);packet.update(frame_before=frame,frame_after=frame)
            own=packet['players'][0]
            own.update(field_phase=phase,mode_phase=2 if phase==0 else 6)
            own['fever_nuisance']['confirmed']=0
            packets.append(packet)
        with patch('tools.analyze_fever_watch.records',return_value=iter(packets)):
            samples=behaviour(['closed.jsonl.gz'])['fever_garbage_ready']
        self.assertEqual(len(samples),1)
        self.assertEqual(samples[0]['drop_to_operable_frames'],71)
        self.assertTrue(samples[0]['drop_edge_exact'] and samples[0]['ready_edge_exact'])


if __name__=='__main__': unittest.main()
