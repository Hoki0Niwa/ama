"""Research observer invariants and native off/on parity, not B1/B2 tests."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fever_battle.worker import JsonProcess
from fever_battle.first40_benchmark import Observation


class GeneratorTests(unittest.TestCase):
    def test_exact_source_anchors_and_no_rule_or_ranking_replacement(self):
        spec=importlib.util.spec_from_file_location('f40_builder',ROOT/'tools/build_fever_diagnostics.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory(dir=ROOT/'bin') as temp:
            builder.generate(Path(temp))
            text=(Path(temp)/'search.cpp').read_text()
            self.assertIn('children.add(child);',text)
            self.assertIn('if (child.score.action < entry->action)',text)
            self.assertIn('if (chain.count >= fever::PRUNE_CHAIN)',text)
            self.assertNotIn('reserve_slots',text)
            self.assertNotIn('min(8',text)
        with self.assertRaisesRegex(ValueError,'anchor changed'):
            builder.replace('missing','old','new')

    def test_observation_does_not_gain_seed_or_hidden_colors(self):
        fields=set(Observation.__dataclass_fields__)
        self.assertFalse(fields & {'seed','future','hidden_queue'})


@unittest.skipUnless(os.environ.get('AMA_TEST_F40_DIAGNOSTIC') and os.environ.get('AMA_TEST_F40_REFERENCE'),
                     'native integration requires dedicated reference and diagnostic builds')
class NativeDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference=JsonProcess([os.environ['AMA_TEST_F40_REFERENCE']],cwd=ROOT)
        cls.diagnostic=JsonProcess([os.environ['AMA_TEST_F40_DIAGNOSTIC']],cwd=ROOT)
        cls.weights=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['fever']
        cls.rows={}
        for line in (ROOT/'data/fever/baselines/2026-10-11-chain15-research/current-mode.jsonl').read_text().splitlines():
            r=json.loads(line);cls.rows[(r['character'],r['seed'],r['move'])]=r

    @classmethod
    def tearDownClass(cls):
        cls.reference.close();cls.diagnostic.close()

    def request(self,character='raffina',seed=31001,move=25):
        row=self.rows[(character,seed,move)]
        return dict(op='solo',weights=self.weights,request=dict(rule='fever',solo=True,
            character=character,dropset_index=move-1,self=dict(field=row['before'],queue=row['queue']),
            plain_pairs=True,special_moves=True,include_next=True,**row['options']))

    @staticmethod
    def stable(reply):return {k:v for k,v in reply.items() if k not in ('search_ms','research_diagnostics')}

    def test_reference_off_on_full_reply_equality(self):
        for character,seed,move in [('raffina',31001,1),('raffina',31001,25),
                ('raffina',31001,30),('rafisol',31004,23),('rafisol',31020,26)]:
            req=self.request(character,seed,move)
            original=self.reference.ask(req);off=self.diagnostic.ask(req)
            on=self.diagnostic.ask(dict(req,research_diagnostics=True,research_placed_total=move-1))
            self.assertEqual(self.stable(original),self.stable(off))
            self.assertEqual(self.stable(original),self.stable(on))
            self.assertNotIn('research_diagnostics',off)

    def test_every_record_conservation_and_feature_balance(self):
        reply=self.diagnostic.ask(dict(self.request(),research_diagnostics=True,
            research_placed_total=24,research_detail_all=True))
        diagnostic=reply['research_diagnostics'];self.assertEqual(len(diagnostic['record_columns']),15)
        for search in diagnostic['searches']:
            self.assertEqual(search['placed_total'],24);self.assertEqual(search['remaining'],16)
            for virtual in search['virtual_searches']:
                self.assertGreater(virtual['expansion_nodes'],0)
                self.assertGreater(virtual['b0_evaluations'],0)
                self.assertEqual(virtual['completed_depth'],len(virtual['layers']))
                for layer in virtual['layers']:
                    self.assertTrue(layer['conservation'])
                    records=layer['records'];self.assertEqual(sum(r[4]==0 for r in records),layer['survivors'])
                    if layer['depth']>1:self.assertLessEqual(layer['survivors'],250)
                    for root in layer['roots']:
                        c=root['counts'];rid=root['root']
                        if rid>=0:
                            self.assertEqual(c.get('eligible',0),c.get('kept',0)+c.get('width_rejected',0)+c.get('width_evicted',0))
                            for state,key in ((0,'kept'),(1,'width_rejected'),(2,'width_evicted'),(3,'tt_cut'),(4,'chain_prune')):
                                self.assertEqual(sum(r[0]==rid and r[4]==state for r in records),c.get(key,0))
                    for r in records:self.assertEqual(r[6],r[12]-4*r[5])

    def test_selected_geometric_witnesses_match_independent_resolve(self):
        on=self.diagnostic.ask(dict(self.request(),research_diagnostics=True,research_placed_total=24))
        checked=0
        for search in on['research_diagnostics']['searches']:
            for virtual in search['virtual_searches'][:1]:
                for layer in virtual['layers']:
                    for example in layer['examples']:
                        g=example['geometry']
                        if g['Lg']<2 or checked>=12:continue
                        board=[list(row) for row in example['board']]
                        x=g['Xg'];height=sum(row[x]!='.' for row in board)
                        for key in range(g['Kg']):board[13-height-key][x]='RYGB'[g['color']]
                        resolved=self.reference.ask(dict(op='resolve',field=[''.join(row) for row in board]))
                        self.assertEqual(len(resolved['links']),g['Lg'])
                        self.assertEqual(sum(sum(link['groups']) for link in resolved['links']),g['popped'])
                        self.assertEqual(sum(c in 'RYGB' for row in resolved['field'] for c in row),g['Rg'])
                        checked+=1
        self.assertGreater(checked,0)

    def test_hidden_queue_seed_and_invalid_clock_rejected(self):
        req=self.request();req['request']['self']['queue']=req['request']['self']['queue']+['2:RR']
        with self.assertRaisesRegex(ValueError,'three visible'):
            self.diagnostic.ask(dict(req,research_diagnostics=True))
        with self.assertRaisesRegex(ValueError,'seed is forbidden'):
            self.diagnostic.ask(dict(self.request(),research_diagnostics=True,seed=123))
        with self.assertRaisesRegex(ValueError,'outside opening'):
            self.diagnostic.ask(dict(self.request(),research_diagnostics=True,research_placed_total=40))


if __name__=='__main__':unittest.main()
