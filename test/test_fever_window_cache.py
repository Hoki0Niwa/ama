"""Recorded narrow window probes must not evict a full-width completed build."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from fever_fixtures import ROOT, NATIVE, SOLO
from fever_battle.mode_engine import ModeBattleEngine
from fever_battle.tactics import Decision


class WindowCacheTests(unittest.TestCase):
    def test_failed_probe_restores_the_completed_build(self):
        cases = json.loads((ROOT/'data/fever/golden/window-build-cache.json').read_text(encoding='utf-8'))['cases']
        req = deepcopy(cases[1]['request'])
        engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
        try:
            engine.answer(req)
            saved = deepcopy(engine.normal_build_cache)
            width = engine.normal_build_width
            def failed_probe(*args):
                engine.normal_build_cache = None
                engine.normal_build_width = 30
                raise ValueError('no surviving probe')
            with patch.object(engine, '_solo_build', side_effect=failed_probe):
                answer = engine._window_build(req, req['self'], req['enemy'],
                    engine.last_normal_options, [], Decision('defense',dict(decision_kind='stack',chain=0)))
            self.assertIsNone(answer)
            self.assertEqual(engine.normal_build_cache,saved)
            self.assertEqual(engine.normal_build_width,width)
        finally:
            engine.close()

    def test_recorded_probes_keep_full_build_and_do_not_repeat_it(self):
        cases = json.loads((ROOT/'data/fever/golden/window-build-cache.json').read_text(encoding='utf-8'))['cases']
        for case in cases:
            with self.subTest(case=case['source_case']):
                engine = ModeBattleEngine(NATIVE, SOLO, ROOT/'config.json')
                try:
                    req = deepcopy(case['request'])
                    with patch.object(engine.solo, 'ask', wraps=engine.solo.ask) as solo:
                        reply = engine.answer(req)
                    widths = [call.args[0]['beam_width'] for call in solo.call_args_list]
                    self.assertEqual(widths, [250])
                    saved = deepcopy(engine.normal_build_cache)
                    self.assertEqual(json.loads(saved[0])['options']['beam_width'],250)
                    self.assertEqual(reply['reason'] == 'normal_extend_before_entry', case['source_case'] == 10)
                    with patch.object(engine.solo, 'ask', wraps=engine.solo.ask) as solo:
                        again = engine._solo_build(req['self'], engine.last_normal_options)
                    solo.assert_not_called()
                    self.assertEqual(again, saved[2])
                    self.assertEqual(engine.normal_build_cache, saved)
                    # A real depth change still searches; cached width alone is insufficient.
                    changed = dict(engine.last_normal_options, beam_depth=15)
                    with patch.object(engine.solo, 'ask', wraps=engine.solo.ask) as solo:
                        engine._solo_build(req['self'], changed)
                    solo.assert_called_once()
                finally:
                    engine.close()


if __name__ == '__main__':
    unittest.main()
