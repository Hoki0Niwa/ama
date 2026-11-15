"""Recorded live pieces must replay on the ported controller, frame by frame."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ControlReplayTests(unittest.TestCase):
    def test_recorded_positions_and_locks(self):
        compiler=Path(os.environ.get('AMA_CXX',r'C:\msys64\mingw64\bin\g++.exe'))
        output=ROOT/'bin/test/fever-control-replay.exe'
        output.parent.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'PATH':str(compiler.parent)+os.pathsep+os.environ.get('PATH','')}
        built=subprocess.run([str(compiler),'-std=c++20','-O2','-static',
            str(ROOT/'fever/control.cpp'),str(ROOT/'test/fever_control_replay_test.cc'),'-o',str(output)],
            env=env,capture_output=True,text=True,timeout=120)
        self.assertEqual(built.returncode,0,built.stdout+built.stderr)
        checked=subprocess.run([str(output)],env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
        self.assertIn('recorded positions and locks reproduced',checked.stdout)

if __name__=='__main__':unittest.main()
