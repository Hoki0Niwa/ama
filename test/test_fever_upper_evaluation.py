"""Compile and run the native Fever upper-row evaluation regression test."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FeverUpperEvaluationTests(unittest.TestCase):
    def test_native_upper_evaluation(self):
        compiler = Path(os.environ.get('AMA_CXX', r'C:\msys64\mingw64\bin\g++.exe'))
        output = ROOT / 'bin/test/fever-upper-evaluation.exe'
        output.parent.mkdir(parents=True, exist_ok=True)
        sources = list((ROOT / 'core').glob('*.cpp')) + [
            ROOT / 'ai/search/beam' / name for name in ('eval.cpp', 'quiet.cpp', 'form.cpp')]
        sources.append(ROOT / 'fever/evaluation.cpp')
        environment = dict(os.environ, PATH=str(compiler.parent) + os.pathsep + os.environ.get('PATH', ''))
        compiled = subprocess.run([str(compiler), '-std=c++20', '-O2', '-msse4.1', '-static',
                                   *map(str, sources), str(ROOT / 'test/fever_upper_eval_test.cc'), '-o', str(output)],
                                  env=environment, timeout=120, capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        result = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=15)
        self.assertIn('checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
