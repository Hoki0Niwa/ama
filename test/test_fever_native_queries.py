"""Memoization preserves complete request identity and result ownership."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from fever_battle.native_queries import NativeQueries
from fever_battle.worker import JsonProcess
from fever_battle.cancellation import CancelEvent


class NativeQueryTests(unittest.TestCase):
    def make(self):
        worker=object.__new__(NativeQueries)
        worker._memo=None
        worker._cancel=CancelEvent(name='')
        return worker

    def test_only_identical_complete_queries_share_work_and_return_detached_values(self):
        worker=self.make()
        query=dict(op='solo',field=['......'],beam_width=80,beam_depth=12,queue=['2:RG'])
        with patch.object(JsonProcess,'ask',return_value={'moves':[{'x':2}]}) as ask:
            with worker.decision():
                first=worker.ask(query);first['moves'][0]['x']=5
                self.assertEqual(worker.ask(dict(reversed(list(query.items()))))['moves'][0]['x'],2)
                for key,value in [('beam_width',81),('beam_depth',13),('queue',['2:RR']),('field',['R.....'])]:
                    other=deepcopy(query);other[key]=value;worker.ask(other)
            self.assertEqual(ask.call_count,5)
            self.assertEqual(worker.last_work['reused'],{'solo':1})
            with worker.decision():worker.ask(query)
            self.assertEqual(ask.call_count,6)

    def test_configuration_commands_are_barriers_and_failures_are_not_cached(self):
        worker=self.make();query={'op':'placements','field':[]}
        with patch.object(JsonProcess,'ask',return_value={'moves':[]}) as ask:
            with worker.decision():
                worker.ask(query);worker.ask({'op':'dropset_override'});worker.ask(query)
                self.assertEqual(ask.call_count,3)
                ask.side_effect=[ValueError('cancelled'),{'moves':[]}]
                with self.assertRaises(ValueError):worker.ask({'op':'solo'})
                worker.ask({'op':'solo'})

    def test_memory_bound_evicts_entries_and_does_not_change_result(self):
        worker=self.make();worker.MAX_ENTRIES=1
        with patch.object(JsonProcess,'ask',side_effect=lambda q,t:{'x':q['x']}) as ask:
            with worker.decision():
                self.assertEqual(worker.ask({'op':'solo','x':1}),{'x':1})
                worker.ask({'op':'solo','x':2});worker.ask({'op':'solo','x':1})
                self.assertEqual(len(worker._memo),1)
            self.assertEqual(ask.call_count,3)

    def test_partial_search_does_not_replace_a_complete_search(self):
        worker=self.make()
        with patch.object(JsonProcess,'ask',side_effect=[{'cutoff':True},{'cutoff':False}]) as ask:
            with worker.decision():
                self.assertTrue(worker.ask({'op':'solo'})['cutoff'])
                self.assertFalse(worker.ask({'op':'solo'})['cutoff'])
                self.assertFalse(worker.ask({'op':'solo'})['cutoff'])
            self.assertEqual(ask.call_count,2)
