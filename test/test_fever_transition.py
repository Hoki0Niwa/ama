"""Check T2 against scalar placement, gravity/pop, and a separate pose graph."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FeverTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = r'C:\msys64\mingw64\bin\g++.exe' if os.name == 'nt' else 'g++'
        cls.compiler = shutil.which(os.environ.get('AMA_CXX', default))
        if not cls.compiler:
            raise RuntimeError('C++20 compiler unavailable; set AMA_CXX')
        cls.environment = dict(os.environ, PATH=str(Path(cls.compiler).parent) + os.pathsep + os.environ.get('PATH', ''))
        cls.output_dir = ROOT / 'bin/test'
        cls.output_dir.mkdir(parents=True, exist_ok=True)
        probe = cls.output_dir / 'fever-cpu-features.exe'
        subprocess.run([cls.compiler, '-x', 'c++', '-std=c++20', '-static', '-', '-o', str(probe)],
                       input='int main() { return __builtin_cpu_supports("bmi2") ? 0 : 1; }',
                       text=True, check=True, capture_output=True, timeout=60, env=cls.environment)
        cls.bmi2 = subprocess.run([str(probe)], env=cls.environment, timeout=10).returncode == 0

    def run_native(self, bmi2):
        sources = [str(p) for p in (ROOT / 'core').glob('*.cpp')]
        output = self.output_dir / ('fever-transition-bmi2.exe' if bmi2 else 'fever-transition-software.exe')
        flags = ['-mbmi2', '-DPEXT'] if bmi2 else ['-DAMA_SOFTWARE_PEXT']
        compiled = subprocess.run([self.compiler, '-std=c++20', '-O2', '-msse4.1', '-Wall', '-Wextra',
                                   '-static', *flags, *sources, str(ROOT / 'test/fever_transition_test.cc'),
                                   '-o', str(output)], env=self.environment, timeout=120,
                                  capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        result = subprocess.run([str(output)], env=self.environment, timeout=60, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
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
