"""Survival, real continuation and sustained large-chain regression cases."""
import json, sys, unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'test')]
from fever_fixtures import NATIVE,SOLO,side,request
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.tactics import Decision
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.engine=ModeBattleEngine(NATIVE,SOLO,ROOT/'config.json')
 @classmethod
 def tearDownClass(cls): cls.engine.close()
 def test_big_natural_clear_is_not_capacity_failure(self):
  own=side('normal',queue=['0:R','2:GB','L:RRG'])
  self.assertFalse(self.engine._stack_full(own,dict(margin=1)))
  self.assertGreater(self.engine.normal_capacity['safe_moves'],0)
 def test_legal_row13_does_not_close_outer_space(self):
  field=['......']*14
  field[1]='.#..#.'
  for y in range(2,14): field[y]='.#..#.'
  c=self.engine.native.ask(dict(op='normal_capacity',field=field,queue=['2:RG','2:GB'],character='raffina',margin=1))
  self.assertGreater(c['safe_moves'],0)
  self.assertFalse(c['release'])
 def test_sustained_second_against_both_opponent_modes(self):
  own=side('normal',queue=['2:RG','2:GB','L:RRG'])
  req=request(own,side('fever')); req['second_target_chain']=14
  self.assertNotIn('sustained',self.engine._normal_options(req,own))
  own['normal_chain_max']=14; own['moves_since_chain']=10
  options=self.engine._normal_options(req,own)
  self.assertTrue(options['sustained']); self.assertEqual(options['sustained_min_chain'],12)
  self.assertEqual(options['elapsed_build_frames'],550)
  req['enemy']['mode']='normal'
  self.assertTrue(self.engine._normal_options(req,own)['sustained'])
 def test_visible_third_piece_changes_continuation_identity(self):
  req=request(side('normal',queue=['2:RG','2:GB','L:RRG']))
  req['self']['field']=['......']*6+['RGYBGB']*8
  a=self.engine._signature(req,req['self']); req['self']['queue'][2]='L:BBR'
  self.assertNotEqual(a,self.engine._signature(req,req['self']))
 def test_second_does_not_chase_a_counter_ready_normal_opponent(self):
  own=side('normal',queue=['2:RY','2:BG']);own['normal_chain_max']=14
  req=request(own,side('normal'))
  self.engine._normal_options(req,own)
  with patch('fever_battle.mode_engine.tactics.evaluate',return_value=Decision('build')) as search:
   result=self.engine._tactical_decision(req,own,req['enemy'],120)
  self.assertEqual(result.status,'build');search.assert_not_called()
 def test_buried_normal_opponent_allows_a_finishing_search(self):
  own=side('normal',queue=['2:RY','2:BG']);own['normal_chain_max']=14
  enemy=side('normal',['......']*9+['######']*5)
  req=request(own,enemy);self.engine._normal_options(req,own)
  with patch('fever_battle.mode_engine.tactics.evaluate',return_value=Decision('build')) as search:
   self.engine._tactical_decision(req,own,enemy,120)
  self.assertTrue(search.call_args.args[5]['finish_buried'])
 def test_fatal_search_does_not_override_a_surviving_exchange(self):
  data=json.loads((ROOT/'data/fever/baselines/2026-10-11-normal-defense-investigation.json').read_text())
  req=next(p['request'] for p in data['probes'] if p['name']=='packet' and not p['fever'] and p['pending']==90)
  req.update(confirmed=120,budget_ms=0,avoid_own_fever=True)
  answer=self.engine.native.ask(req)
  self.assertTrue(answer['fatal_known_attack'])
  self.assertTrue(any(c['survives_known_exchange'] for c in answer['candidates']))
  self.assertTrue(answer['choice']['survives_known_exchange'])
if __name__=='__main__': unittest.main()
