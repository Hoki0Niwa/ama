"""The replay of logged decisions and the symptom-seed list read from the same session log."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'test'), str(ROOT / 'tools')]
import fever_fixtures as fixtures
import symptom_seeds


def write_log(path, events):
    with io.open(path, 'w', encoding='utf-16') as handle:
        for event in events:
            handle.write(json.dumps(event) + '\n')


class ReplayTests(unittest.TestCase):
    def test_logged_requests_are_asked_to_the_engine_again(self):
        request = fixtures.request()
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'session.log'
            write_log(log, [dict(auto='round over'),
                            dict(auto='seed decision', move='0U', request=request),
                            dict(auto='fire', move='0U'),  # no request: not replayable, skipped
                            dict(auto='analysis failed, retrying', move='4R', piece='J:RGB', request=request)])
            run = subprocess.run([sys.executable, str(ROOT / 'tools/replay_logged_decisions.py'), str(log),
                                  '--kind', 'failed', 'seed'], capture_output=True, text=True, check=True)
        result = json.loads(run.stdout)
        self.assertEqual(result['decisions'], 2)
        self.assertEqual({row['event'] for row in result['rows']}, {'seed decision', 'analysis failed, retrying'})
        self.assertTrue(all(row['error'] is None and row['replayed_move'] for row in result['rows']))
        self.assertEqual({row['round'] for row in result['rows']}, {2})

    def test_symptom_seeds_follow_the_round_order_of_the_seed_file(self):
        failure = lambda round_number, piece_id, piece='J:RRG': dict(
            auto='analysis failed, retrying', piece=piece, reason='placement is no longer reachable from the observed pose',
            decision_identity=dict(match_id='abc-round-%d' % round_number, piece_id=piece_id))
        events = [dict(auto='round over')]                      # round 1 ends
        events += [failure(2, 7) for _ in range(9)]              # round 2: nine retries of one triple
        events += [dict(auto='round over'), dict(auto='round over')]
        events += [failure(3, 4, '2:RG')]                        # a pair does not count
        events += [dict(auto='fire', mode='normal', chain=10)]   # first big fire of round 4: 10 links
        with tempfile.TemporaryDirectory() as folder:
            log, seeds = Path(folder) / 'session.log', Path(folder) / 'seeds.txt'
            write_log(log, events)
            seeds.write_text('# match\tgame\tseed(hex)\tseed(dec)\tsource\ttime\n'
                             '1\t1\t0x0\t0\tstep\tx\n2\t2\t0x1\t1\tstep\tx\n3\t3\t0x2\t2\tstep\tx\n4\t4\t0x3\t3\tstep\tx\n',
                             encoding='utf-8-sig')
            found, table = symptom_seeds.scan(str(log)), symptom_seeds.read_seeds(seeds)
        self.assertEqual(found['triple_loop'], {2: 9})
        self.assertEqual(found['early_fire'], {4: 10})
        self.assertEqual(table, {1: 0, 2: 1, 3: 2, 4: 3})


if __name__ == '__main__':
    unittest.main()
