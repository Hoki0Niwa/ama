"""Compare the common core with a scalar model, using explicit software and BMI2 PEXT paths."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CoreSpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = Path(os.environ.get('AMA_CXX', r'C:\msys64\mingw64\bin\g++.exe'))
        cls.environment = dict(os.environ, PATH=str(cls.compiler.parent) + os.pathsep + os.environ.get('PATH', ''))
        cls.output_dir = ROOT / 'bin/test'
        cls.output_dir.mkdir(parents=True, exist_ok=True)
        probe = cls.output_dir / 'cpu-features.exe'
        source = 'int main() { return __builtin_cpu_supports("bmi2") ? 0 : 1; }'
        subprocess.run([str(cls.compiler), '-x', 'c++', '-std=c++20', '-static', '-', '-o', str(probe)],
                       input=source, text=True, check=True, capture_output=True, timeout=60,
                       env=cls.environment)
        cls.bmi2 = subprocess.run([str(probe)], env=cls.environment, timeout=10).returncode == 0

    def run_native(self, pext):
        sources = list((ROOT / 'core').glob('*.cpp')) + [
            ROOT / 'ai/search/beam' / name for name in ('quiet.cpp', 'table.cpp')]
        output = self.output_dir / ('core-speed-bmi2.exe' if pext else 'core-speed-software.exe')
        flags = ['-mbmi2', '-DPEXT'] if pext else ['-DAMA_SOFTWARE_PEXT']
        compiled = subprocess.run([str(self.compiler), '-std=c++20', '-O2', '-msse4.1', '-static',
                                   *flags, *map(str, sources), str(ROOT / 'test/core_speed_test.cc'),
                                   '-o', str(output)], env=self.environment, timeout=120,
                                  capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        result = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=20)
        self.assertIn('checks passed', result.stdout)
        print(result.stdout.strip())

    def test_software_pext(self):
        self.run_native(False)

    def test_bmi2_pext(self):
        if not self.bmi2:
            self.skipTest('BMI2 unavailable on this CPU')
        self.run_native(True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
