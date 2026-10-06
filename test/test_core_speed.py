"""Validate chain resolution independently with runtime BMI2 and software fallback."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CoreSpeedTests(unittest.TestCase):
    def test_native_chain_and_quiet_equivalence(self):
        compiler = Path(os.environ.get('AMA_CXX', r'C:\msys64\mingw64\bin\g++.exe'))
        sources = list((ROOT / 'core').glob('*.cpp')) + [
            ROOT / 'ai/search/beam' / name for name in ('quiet.cpp', 'table.cpp', 'eval.cpp', 'form.cpp')]
        environment = dict(os.environ, PATH=str(compiler.parent) + os.pathsep + os.environ.get('PATH', ''))
        for software in (False, True):
            with self.subTest(software_pext=software):
                output = ROOT / ('bin/test/core-speed-software.exe' if software else 'bin/test/core-speed.exe')
                output.parent.mkdir(parents=True, exist_ok=True)
                flags = ['-DAMA_SOFTWARE_PEXT'] if software else []
                compiled = subprocess.run([str(compiler), '-std=c++20', '-O2', '-msse4.1', '-static',
                                           *flags, *map(str, sources), str(ROOT / 'test/core_speed_test.cc'),
                                           '-o', str(output)], env=environment, timeout=120,
                                          capture_output=True, text=True)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                result = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=20)
                self.assertIn('checks passed', result.stdout)
                print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main(verbosity=2)
