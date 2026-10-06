"""Compile and run native regressions for small-clear resource accounting."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChainQualityTests(unittest.TestCase):
    def test_native_small_clear_cost_and_raw_score(self):
        compiler = Path(os.environ.get('AMA_CXX', r'C:\msys64\mingw64\bin\g++.exe'))
        output = ROOT / 'bin/test/chain-quality.exe'
        output.parent.mkdir(parents=True, exist_ok=True)
        sources = list((ROOT / 'core').glob('*.cpp')) + list((ROOT / 'ai/search/beam').glob('*.cpp'))
        environment = dict(os.environ, PATH=str(compiler.parent) + os.pathsep + os.environ.get('PATH', ''))
        compiled = subprocess.run([str(compiler), '-std=c++20', '-O2', '-msse4.1', '-static',
                                   *map(str, sources), str(ROOT / 'test/chain_quality_test.cc'),
                                   '-o', str(output)], env=environment, timeout=120,
                                  capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
