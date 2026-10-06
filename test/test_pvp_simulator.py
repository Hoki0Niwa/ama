"""Frame referee, parallel matches, and external engine regression checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(os.environ.get('AMA_TEST_ENGINE', ROOT / 'bin/pvp/pvp.exe'))


def run(*args):
    return subprocess.run([str(EXE), *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, timeout=90)


class PvpSimulatorTests(unittest.TestCase):
    def test_native_referee(self):
        compiler = Path(os.environ.get('AMA_CXX', r'C:\msys64\mingw64\bin\g++.exe'))
        sources = [p for directory in ('core', 'ai', 'ai/search', 'ai/search/beam', 'ai/search/dfs')
                   for p in (ROOT / directory).glob('*.cpp')]
        output = ROOT / 'bin/test/pvp-simulator.exe'
        output.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PATH=str(compiler.parent) + os.pathsep + os.environ.get('PATH', ''))
        result = subprocess.run([str(compiler), '-std=c++20', '-O2', '-msse4.1', '-DNDEBUG', '-static',
                                 *map(str, sources), str(ROOT / 'test/pvp_simulator_test.cc'),
                                 '-o', str(output)], env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('checks passed', result.stdout)

    def test_parallel_external_engine_and_profiles(self):
        folder = ROOT / 'bin/test/pvp-fixtures'
        folder.mkdir(parents=True, exist_ok=True)
        engine = folder / 'fixed.py'
        engine.write_text('import json,sys\nfor line in sys.stdin:\n'
                          ' r=json.loads(line)\n'
                          ' assert r["beam_width"]==12 and r["beam_depth"]==3\n'
                          ' print(json.dumps(dict(x=2,r="U",eval=0,trigger=None)),flush=True)\n')
        command = f'"{sys.executable}" "{engine}"'
        logs = []
        for jobs in (1, 3):
            log = folder / f'{jobs}.jsonl'
            result = run('--games', 4, '--max-moves', 2, '--jobs', jobs,
                         '--beam-width', 12, '--beam-depth', 3, '--log', log, command, command)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            games = [line.split('\t')[:11] for line in result.stdout.splitlines() if line[:1].isdigit()]
            self.assertEqual(len(games), 4)
            rows = [json.loads(line) for line in log.read_text().splitlines()]
            logs.append((games, rows[1:]))
        self.assertEqual(logs[0], logs[1])
        profile = folder / 'timing.json'
        profile.write_text(json.dumps(dict(start=20, soft_drop=4)))
        log = folder / 'custom.jsonl'
        result = run('--games', 1, '--max-moves', 1, '--beam-width', 12, '--beam-depth', 3,
                     '--timing-config', profile, '--log', log, command, command)
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(log.read_text().splitlines()[1])
        self.assertEqual((decision['frame'], decision['lock_frame']), (20, 64))
        result = run('--games', 1, '--max-moves', 2, '--timing', 'abstract',
                     '--beam-width', 12, '--beam-depth', 3, command, command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('timing: abstract', result.stdout)

    def test_invalid_options(self):
        for args in [('--jobs', '0'), ('--target', '0'), ('--max-moves', '-1'),
                     ('--beam-width', '-1'), ('--beam-depth', '1'), ('--timing', 'bad'), ('--typo',)]:
            with self.subTest(args=args):
                result = run(*args, 'local', 'local')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('pvp:', result.stderr)
        folder = ROOT / 'bin/test/pvp-fixtures'
        folder.mkdir(parents=True, exist_ok=True)
        profile = folder / 'invalid-timing.json'
        for data in ({'ai_unit': 0}, {'soft_drop': 2.5}, {'typo': 2}):
            profile.write_text(json.dumps(data))
            self.assertNotEqual(run('--timing-config', profile, 'local', 'local').returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
