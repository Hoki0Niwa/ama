"""Shared receiving, upper-space and visible return decisions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE
from fever_battle.worker import JsonProcess


class NormalDefenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=JsonProcess([NATIVE],cwd=ROOT)
        cls.report=json.loads((ROOT/'data/fever/baselines/2026-10-11-normal-defense-investigation.json').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls): cls.native.close()

    def base(self):
        return deepcopy(next(p['request'] for p in self.report['probes'] if p['name']=='packet' and not p['fever'] and p['pending']==90))

    def test_dense_board_can_receive_two_without_spending_eleven_chain(self):
        source=next(p for p in self.report['small_packet_replays'] if p['sample']['lock']['t']==834.578)
        for unknown in (False,True):
            req=deepcopy(source['request']); req['unknown_garbage_phase']=unknown
            reply=self.native.ask(req)
            self.assertTrue(reply['can_receive_attack'])
            self.assertEqual(reply['choice']['chain'],0)
            self.assertTrue(reply['choice']['can_receive'])
            self.assertEqual(reply['choice']['main_links_lost'],0)

    def test_normal_opponent_also_charges_main_consumption(self):
        req=self.base(); req.update(allowed=[dict(x=2,r='U')],confirmed=1)
        vals=[]
        for weight in (0,1000000):
            req['weights'].update(mainline=weight,uncountered=weight)
            vals.append(self.native.ask(req)['choice']['value'])
        self.assertGreater(vals[0],vals[1])

    def test_tactics_retains_legal_thirteenth_row(self):
        req=deepcopy(next(p['request'] for p in self.report['probes'] if p['name']=='upper_tactics'))
        reply=self.native.ask(req)
        self.assertIn((1,'U'),[(c['x'],c['r']) for c in reply['candidates']])
        self.assertTrue(reply['choice']['survives'])

    def test_builder_uses_same_upper_condition(self):
        req=deepcopy(next(p['request'] for p in self.report['probes'] if p['name']=='upper_tactics'))
        weights=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['fever']
        reply=self.native.ask(dict(op='solo',weights=weights,request=dict(rule='fever',solo=True,
            character='arle',dropset_index=0,self=dict(field=req['field'],queue=req['queue']),
            trigger=19,beam_width=20,beam_depth=3,margin=1,special_moves=True)))
        board=self.native.ask(dict(op='transition',field=req['field'],piece=req['queue'][0],x=reply['x'],r=reply['r']))
        self.assertTrue(all(sum(row[x]!='.' for row in board['field'])<=12 for x in (1,4)))

    def test_sole_reachable_upper_placement_stays_available(self):
        req=deepcopy(next(p['request'] for p in self.report['probes'] if p['name']=='upper_tactics'))
        req['allowed']=[dict(x=1,r='U')]
        reply=self.native.ask(req)
        self.assertEqual((reply['choice']['x'],reply['choice']['r']),(1,'U'))

    def test_large_packet_still_selects_sufficient_main(self):
        reply=self.native.ask(self.base())
        self.assertFalse(reply['can_receive_attack'])
        self.assertGreaterEqual(reply['choice']['chain'],7)
        self.assertTrue(reply['choice']['defensive_fire'])

    def test_visible_preparation_is_a_sufficient_return(self):
        req=self.base()
        req.update(queue=['2:GB','2:YR','2:GB'],confirmed=0,unconfirmed=0,
                   enemy_events=[dict(type='link',frame=350,points=10800),dict(type='end',frame=400)])
        reply=self.native.ask(req)
        self.assertFalse(reply['can_receive_attack'])
        self.assertEqual(reply['choice']['chain'],0)
        self.assertTrue(reply['choice']['projected_sufficient_return'])
        self.assertGreaterEqual(reply['choice']['projected_return_points'],10800)
        self.assertTrue(reply['choice']['defensive_fire'])
        move=reply['choice']
        transition=self.native.ask(dict(op='transition',field=req['field'],piece=req['queue'][0],x=move['x'],r=move['r']))
        req.update(field=transition['field'],queue=req['queue'][1:])
        req['enemy_events']=[{**e,'frame':e['frame']-move['frame']} for e in req['enemy_events']]
        next_reply=self.native.ask(req)
        self.assertGreaterEqual(next_reply['choice']['chain'],7)
        self.assertTrue(next_reply['choice']['defensive_fire'])

    def test_preparation_does_not_claim_sufficient_return_for_a_larger_attack(self):
        req=self.base()
        req.update(queue=['2:GB','2:YR','2:GB'],confirmed=0,unconfirmed=0,
                   enemy_events=[dict(type='link',frame=700,points=30000),dict(type='end',frame=750)])
        reply=self.native.ask(req)
        self.assertFalse(reply['choice']['projected_sufficient_return'])


if __name__=='__main__': unittest.main()
