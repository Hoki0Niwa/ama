"""Animation boundaries must not turn a final grid row into visual rest."""
from pathlib import Path
import struct
import io
import json
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fever_battle.calibrate import animation_boundaries, coordinate_evidence, records, epochs, measure


def sample(frame,cells):
    raw=bytearray(128*24)
    for i in range(128):struct.pack_into('<I',raw,i*24+0x10,i<<16)
    for i,identity in cells:
        raw[i*24]=1;struct.pack_into('<Q',raw,i*24+8,identity)
    return dict(frame=frame,drawn_cell_table_hex=raw.hex())


class Tests(unittest.TestCase):
    def test_stack_contact_anchor_can_exceed_final_cell_while_render_keeps_moving(self):
        interval=[]
        for frame,anchor,y,contact in ((0,0,0,0),(1,0,0,0),(2,0.5,0.5,0),
                                      (3,2.5,2.5,1),(4,2.5,1.4,0),(5,2.5,1.1,0)):
            raw=bytearray(0x40);cell=35 # final row y=1, anchor overshoots by 1.5
            raw[0x1e:0x21]=bytes((cell%8,cell//8,cell));raw[0x1c]=contact
            for offset,value in ((0x24,anchor),(0x2c,y),(0x34,y)):
                struct.pack_into('<f',raw,offset,value)
            interval.append(dict(frame=frame,battle_candidate=dict(settled=frame>=1),
                animation_entities_candidate=[dict(address='0x1000',cell=cell,hex=raw.hex())]))
        result=coordinate_evidence(interval,{0x1000})
        self.assertEqual(result['max_last_anchor_motion_offset'],3)
        self.assertEqual(result['fall_boundary_to_last_anchor_motion_frames'],2)
        self.assertEqual(result['last_anchor_motion_to_next_link_frames'],3)
        self.assertTrue(result['last_anchor_contact_bit_all_set'])
        self.assertTrue(result['render_motion_at_next_link'])
        self.assertEqual(result['max_anchor_overshoot_rows'],1.5)
        self.assertIsNone(result['visual_rest_offset'])
        interval[2]['animation_entities_candidate'][0]['cell']=36
        self.assertEqual(coordinate_evidence(interval,{0x1000})['status'],'entity_cell_marker_mismatch')

    def test_late_observed_onset_is_excluded_even_when_interval_is_contiguous(self):
        empty=['......']*14
        features=dict(max_fall=0,moving_puyos=0,moving_columns=0,distance_sum=0,
                      cleared_including_garbage=4,moving_distances_by_column=[[]]*6)
        transition=dict(field=empty,locked_field=empty,split_distances=[0],
                        links=[dict(groups=[4],colors=1)]*3,fall_features=[features]*3)
        class Native:
            def ask(self,request):return transition
        def player(frame,link,phase=6,placed=1):
            return dict(frame=frame,phase=phase,seat=1,address='a',
                active=dict(piece='2:RG',cells=[(0,0),(0,-1)],rotation=0,grounded=0,placed=placed),
                simulator_field_candidate=empty,battle_candidate=dict(link=link,settled=False))
        group=[player(0,0,2,0),player(1,0,4),player(2,0,5),
               player(3,1),player(4,1),player(5,2),player(6,2),player(7,3),player(8,0,2)]
        with patch('fever_battle.calibrate.epochs',return_value=iter([group])), \
             patch('fever_battle.calibrate.file_sha256',return_value='test'):
            complete=measure(['test'],Native())
        self.assertEqual(len(complete['links']),2)
        group.pop(2) # Counter 1 is seen at frame 3 without the frame-2 onset boundary.
        with patch('fever_battle.calibrate.epochs',return_value=iter([group])), \
             patch('fever_battle.calibrate.file_sha256',return_value='test'):
            partial=measure(['test'],Native())
        self.assertEqual(len(partial['links']),1)
        self.assertEqual(partial['rejected']['missed_link_onset_edge'],1)

    def test_large_recording_reader_streams_and_ignores_unfinished_tail(self):
        with patch.object(Path,'open',return_value=io.StringIO('{"event":"header"}\n{"event":')), \
             patch.object(Path,'read_text',side_effect=AssertionError('whole-file allocation')):
            self.assertEqual(list(records('capture.jsonl')),[dict(event='header')])

    def test_menu_reset_separates_rounds_and_excludes_cpu(self):
        def packet(frame,address):
            field=bytearray(0x118);struct.pack_into('<I',field,0x10c,2)
            own=dict(address=address,active={},battle_candidate=dict(cpu=False),
                     field_candidate=dict(hex=field.hex()),simulator_field_candidate=[],score_candidate={})
            return dict(event='sample',both_players_same_frame=True,frame_before=[frame,frame],
                        players=[own,dict(address='cpu',battle_candidate=dict(cpu=True))])
        data=''.join(json.dumps(packet(f,a))+'\n' for f,a in ((0,'a'),(1,'a'),(0,'b'),(1,'b')))
        with patch.object(Path,'open',return_value=io.StringIO(data)):
            groups=list(epochs('capture.jsonl'))
        self.assertEqual([[r['address'] for r in g] for g in groups],[['a','a'],['b','b']])

    def test_disappearance_and_motion_are_separate_and_rest_is_unknown(self):
        interval=[sample(100,[(1,1000),(2,2000),(3,3000)]),
                  sample(101,[(2,2000),(3,3000)]),sample(102,[(11,3000)]),
                  sample(103,[(11,3000)])]
        result=animation_boundaries(interval,dict(cleared_including_garbage=2,moving_puyos=1))
        self.assertEqual(result['first_disappearance_offset'],1)
        self.assertEqual(result['last_disappearance_offset'],2)
        self.assertEqual(result['first_survivor_cell_motion_offset'],2)
        self.assertEqual(result['last_survivor_cell_motion_offset'],2)
        self.assertIsNone(result['visual_rest_offset'])

    def test_missed_frames_do_not_supply_exact_boundaries(self):
        result=animation_boundaries([sample(1,[(1,1000)]),sample(3,[])],
                                    dict(cleared_including_garbage=1,moving_puyos=0))
        self.assertEqual(result['status'],'missed_animation_frames')

    def test_mismatched_simulation_is_rejected(self):
        result=animation_boundaries([sample(1,[(1,1000)]),sample(2,[])],
                                    dict(cleared_including_garbage=2,moving_puyos=0))
        self.assertEqual(result['status'],'drawn_identity_geometry_mismatch')


if __name__=='__main__':unittest.main(verbosity=2)
