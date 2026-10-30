"""Live collision rounding must agree with the ported Steam ground query."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ControlClearanceTests(unittest.TestCase):
    def test_quarter_cell_clearance_matches_steam_ground_query(self):
        compiler=Path(os.environ.get('AMA_CXX',r'C:\msys64\mingw64\bin\g++.exe'))
        output=ROOT/'bin/test/fever-control-clearance.exe'
        output.parent.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'PATH':str(compiler.parent)+os.pathsep+os.environ.get('PATH','')}
        built=subprocess.run([str(compiler),'-std=c++20','-O2','-static',
            str(ROOT/'fever/control.cpp'),str(ROOT/'test/fever_control_clearance_test.cc'),'-o',str(output)],
            env=env,capture_output=True,text=True,timeout=120)
        self.assertEqual(built.returncode,0,built.stdout+built.stderr)
        checked=subprocess.run([str(output)],env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
        self.assertIn('3612 quarter-cell clearance comparisons passed',checked.stdout)

if __name__=='__main__':unittest.main()
