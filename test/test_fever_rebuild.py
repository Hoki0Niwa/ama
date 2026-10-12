"""Native reconstruction regressions and canonical scoring header consistency."""
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from generate_fever_normal_scoring import render, TARGET


class RebuildTests(unittest.TestCase):
    def test_embedded_tables_match_canonical_data(self):
        self.assertEqual(TARGET.read_text(encoding='utf-8'),render())

    def test_native_scoring_and_piece_reconstruction(self):
        compiler=Path(os.environ.get('AMA_CXX',r'C:\msys64\mingw64\bin\g++.exe'))
        output=ROOT/'bin/test/fever-rebuild.exe'
        output.parent.mkdir(parents=True,exist_ok=True)
        sources=list((ROOT/'core').glob('*.cpp')) + [ROOT/'ai/search/beam'/n for n in
            ('eval.cpp','quiet.cpp','form.cpp','layer.cpp','table.cpp')] + [ROOT/'fever'/n for n in
            ('evaluation.cpp','rebuild.cpp','search.cpp','fire.cpp')]
        # Layer/table implementations may be header-only; only compile existing sources.
        sources=[s for s in sources if s.exists()]
        environment={**os.environ,'PATH':str(compiler.parent)+os.pathsep+os.environ.get('PATH','')}
        built=subprocess.run([str(compiler),'-std=c++20','-O2','-msse4.1','-static',*map(str,sources),
            str(ROOT/'test/fever_rebuild_test.cc'),'-o',str(output)],env=environment,capture_output=True,text=True,timeout=120)
        self.assertEqual(built.returncode,0,built.stdout+built.stderr)
        checked=subprocess.run([str(output)],capture_output=True,text=True,timeout=30)
        self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
        self.assertIn('checks passed',checked.stdout)

    def test_initial_fire_uses_every_characters_actual_normal_score(self):
        sys.path.insert(0,str(ROOT))
        from fever_battle.worker import JsonProcess
        from fever_battle.model import Scoring
        executable=Path(os.environ.get('AMA_BATTLE_NATIVE',ROOT/'bin/fever_battle/fever_battle.exe'))
        native=JsonProcess([str(executable)],cwd=ROOT)
        sets=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
        patterns=json.loads((ROOT/'data/fever/dropsets.json').read_text(encoding='utf-8'))['characters']
        field=['......']*12+['RRRB..','BBBR..']
        scores=set()
        try:
            for character in patterns:
                index=character['pattern'].index('2')
                initial=dict(rule='fever',solo=True,character=character['id'],dropset_index=index,
                    self=dict(field=field,queue=['2:RB']),fire=True,include_next=True,beam_width=10,beam_depth=1)
                reply=native.ask(dict(op='solo',weights=sets['fever'],request=initial))
                transition=native.ask(dict(op='transition',field=field,piece='2:RB',x=reply['x'],r=reply['r']))
                expected=sum(Scoring().chain(character['id'],transition['links'],'normal'))
                self.assertGreaterEqual(len(transition['links']),2)
                self.assertEqual(reply['next_score'],expected,character['id'])
                self.assertEqual(reply['eval'],expected,character['id'])
                self.assertEqual(reply['construction_scoring'],'fever_normal')
                scores.add(expected)
            self.assertGreater(len(scores),1,'character powers were ignored')
        finally:
            native.close()


if __name__=='__main__': unittest.main()
