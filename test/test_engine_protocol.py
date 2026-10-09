"""Standalone regression checks for the engine's additive JSON protocol."""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(os.environ.get('AMA_TEST_ENGINE', ROOT / 'bin/pvp/pvp.exe'))


def request():
    side = dict(field=['......'] * 14, queue=['RG', 'BY', 'YB'],
                all_clear=False, bonus=0, attack=0, attack_chain=0,
                attack_frame=0, dropping=0)
    return dict(self=side, enemy=copy.deepcopy(side), target_point=70,
                trigger=100000, stretch=True)


def replies(*requests):
    result = subprocess.run([str(EXE), '--engine', str(ROOT / 'config.json')],
                            input=''.join(json.dumps(r) + '\n' for r in requests),
                            capture_output=True, text=True, timeout=45, check=True)
    output = [json.loads(line) for line in result.stdout.splitlines() if line]
    if len(output) != len(requests):
        raise AssertionError(f'Expected {len(requests)} replies, got {len(output)}')
    return output


class EngineProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EXE.is_file():
            raise RuntimeError(f'Build the engine first: {EXE}')

    def test_legacy_request_and_process_lifetime(self):
        req = request()
        for reply in replies(req, req):
            self.assertIn(reply['r'], ('U', 'R', 'D', 'L'))
            self.assertIn(reply['x'], range(6))
            self.assertIn('eval', reply)
            self.assertIn('trigger', reply)

    def test_buried_enemy_rebuilds_without_small_followups(self):
        req = dict(request(), include_next=True, beam_width=25, beam_depth=8)
        req['self'].update(field=['......'] * 11 + ['R.....'] * 3,
                           queue=['RB', 'GY', 'YB'])
        req['enemy']['field'] = ['......'] * 11 + ['######'] * 3
        reply, = replies(req)
        self.assertTrue(reply['wait_for_enemy'])
        self.assertEqual(reply['build_search'], 'beam')
        self.assertEqual(reply['next_chain'], 0)

    def test_wait_requires_no_fire_through_all_three_visible_pairs(self):
        req = dict(request(), beam_width=12, beam_depth=3)
        req['enemy'].update(field=['......'] * 9 + ['R.....'] * 2 + ['######'] * 3,
                            queue=['GB', 'YB', 'RR'])
        reply, = replies(req)
        self.assertFalse(reply['wait_for_enemy'])
        self.assertEqual(reply['build_search'], 'beam')

    def test_fixed_garbage_forecast_and_live_fire_before_it(self):
        req = dict(request(), beam_width=12, beam_depth=3)
        req['self']['attack'] = 18
        req['enemy']['dropping'] = 18
        blocked = copy.deepcopy(req)
        req['enemy'].update(field=['......'] * 11 + ['R.....'] * 3,
                            queue=['RB', 'GY', 'YB'])
        waiting, recoverable = replies(blocked, req)
        self.assertTrue(waiting['wait_for_enemy'])
        self.assertFalse(recoverable['wait_for_enemy'])

    def test_wait_is_disabled_for_defence_running_chains_and_solo(self):
        req = dict(request(), beam_width=12, beam_depth=3)
        req['enemy']['field'] = ['......'] * 11 + ['######'] * 3
        running = copy.deepcopy(req)
        running['enemy']['attack_frame'] = 4
        threatened = copy.deepcopy(req)
        threatened['enemy']['attack'] = 30
        dropping = copy.deepcopy(req)
        dropping['self']['dropping'] = 6
        for reply in replies(running, threatened, dropping, dict(req, solo=True)):
            self.assertFalse(reply['wait_for_enemy'])

    def test_wait_is_recomputed_when_cached_enemy_recovers(self):
        req = dict(request(), beam_width=12, beam_depth=3)
        req['enemy']['field'] = ['......'] * 11 + ['######'] * 3
        recovered = copy.deepcopy(req)
        recovered['enemy'].update(field=['......'] * 11 + ['R.....'] * 3,
                                  queue=['RB', 'GY', 'YB'])
        waiting, active = replies(req, dict(recovered, reuse_search=True))
        self.assertTrue(waiting['wait_for_enemy'])
        self.assertTrue(active['search_reused'])
        self.assertFalse(active['wait_for_enemy'])

    def test_route_and_prediction_match_a_real_firing_placement(self):
        req = request()
        req['self'].update(field=['......'] * 11 + ['R.....'] * 3,
                           queue=['RB', 'YY', 'GG'])
        req.update(solo=True, fire=True, include_path=True, include_next=True,
                   beam_width=25, beam_depth=8)
        reply, = replies(req)
        self.assertTrue(reply['path_reachable'])
        self.assertEqual(reply['path_origin'], 'spawn')
        self.assertEqual(reply['path'][-1], 'DROP')
        self.assertEqual(len(reply['next_field']), 14)
        self.assertEqual(reply['next_chain'], 1)
        self.assertGreaterEqual(reply['next_score'], 40)

    def test_beam_target_and_zoro_options_still_place(self):
        req = request()
        req.update(beam_width=12, beam_depth=8, beam_target=60000, beam_zoro=True)
        for reply in replies(req, dict(req, beam_zoro=False), dict(req, beam_target=0)):
            self.assertIn(reply['r'], ('U', 'R', 'D', 'L'))
            self.assertIn(reply['x'], range(6))

    def test_solo_fire_reply_matches_direct_attack(self):
        req = request()
        req['self'].update(field=['......'] * 11 + ['R.....'] * 3,
                           queue=['RB', 'GG', 'YY'])
        req.update(solo=True, include_path=True, include_next=True,
                   beam_width=25, beam_depth=8)
        built, direct = replies(req, dict(req, fire=True))
        fire = built['fire_reply']
        self.assertEqual(fire['attack_score'], direct['attack_score'])
        self.assertEqual(fire['next_score'], direct['next_score'])
        self.assertGreater(fire['next_chain'], 0)
        self.assertTrue(fire['path_reachable'])

    def test_tactics_reuse_construction_with_latest_attack_time(self):
        req = request()
        req['self'].update(field=['......'] * 9 +
                           ['.....Y', '.....B', '.....B', '.....G', 'Y.G.YG'],
                           queue=['BG', 'BR', 'RB'])
        req['enemy'].update(attack=320, attack_chain=13, attack_frame=19)
        req.update(include_path=True, include_next=True, beam_width=100, beam_depth=8)
        second = copy.deepcopy(req)
        second['enemy']['attack_frame'] = 5
        third = copy.deepcopy(second)
        third['enemy']['attack_frame'] = 4
        first, changed, reused, fresh = replies(
            req, dict(second, reuse_search=True), dict(third, reuse_search=True), third)
        self.assertEqual(first['build_search'], 'freestyle')
        self.assertEqual(changed['build_search'], 'fast')
        self.assertTrue(reused['search_reused'])
        self.assertEqual(reused['build_search'], 'none')
        self.assertEqual(tuple(reused[k] for k in ('x', 'r', 'eval')),
                         tuple(fresh[k] for k in ('x', 'r', 'eval')))

    def test_cache_rejects_changed_input_and_search_settings(self):
        base = dict(request(), beam_width=12, beam_depth=3)
        base['self']['field'][-1] = 'R.....'
        for key in ('field', 'row14', 'queue', 'beam_width', 'beam_depth', 'beam_target', 'beam_zoro', 'trigger', 'stretch'):
            with self.subTest(key=key):
                changed = copy.deepcopy(base)
                if key == 'field':
                    changed['self']['field'][-1] = 'RR....'
                elif key == 'row14':
                    changed['self']['field'][0] = '#.....'
                elif key == 'queue':
                    changed['self']['queue'][1] = 'RR'
                elif key in ('stretch', 'beam_zoro'):
                    changed[key] = not base.get(key, False)
                else:
                    changed[key] = changed.get(key, 0) + 1
                _, reply = replies(base, dict(changed, reuse_search=True))
                self.assertFalse(reply['search_reused'])

    def test_guessed_tail_requires_explicit_prefix_matching(self):
        base = dict(request(), beam_width=12, beam_depth=3)
        changed = copy.deepcopy(base)
        changed['self']['queue'][-1] = 'GG'
        _, approximate, _, exact = replies(
            base, dict(changed, reuse_search=True, search_prefix=2),
            base, dict(changed, reuse_search=True))
        self.assertTrue(approximate['search_reused'])
        self.assertFalse(exact['search_reused'])

    def test_unprepared_beam_defers_until_client_is_ready(self):
        base = dict(request(), beam_width=12, beam_depth=3, include_next=True)
        base['enemy'].update(attack=320, attack_chain=13, attack_frame=19)
        changed = copy.deepcopy(base)
        changed['enemy'].update(attack=0, attack_chain=0, attack_frame=0)
        first, deferred, ready = replies(
            base, dict(changed, reuse_search=True, tactics_only=True),
            dict(changed, reuse_search=True))
        self.assertEqual(first['build_search'], 'freestyle')
        self.assertTrue(deferred['build_required'])
        self.assertNotIn('next_field', deferred)
        self.assertNotIn('build_required', ready)
        self.assertEqual(ready['build_search'], 'beam')


if __name__ == '__main__':
    unittest.main(verbosity=2)
