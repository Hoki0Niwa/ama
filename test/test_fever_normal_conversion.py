"""Capacity conversion: known small attacks, residual safety and virtual rebuilds."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'test')]
from fever_battle.mode_engine import ModeBattleEngine
from fever_fixtures import NATIVE, SOLO, side, request
from fever_battle.timing import ChainTiming
from fever_battle.normal_conversion import enemy_context
from fever_battle import disruption

# The board two pieces before the reported ten-chain fire. No local logs needed.
BOARD = '....../Y...../YY...R/RY..#Y/GB.YGY/#BRBBG/#B#YYR/GY#GGR/GRR#RB/G#R#RB/R#YYGY/GYRYGB/GBBRG#/RRBR##'.split('/')
FULL = '....../YB...G/YY..YR/RY..#Y/GBGYGY/#BRBBG/#B#YYR/GY#GGR/GRR#RB/G#R#RB/R#YYGY/GYRYGB/GBBRG#/RRBR##'.split('/')
PATTERN = '22222220222222J4'


def case():
    own = side('normal', BOARD, ['2:GB', '2:YG', '2:RY'])
    own.update(character='ally', pattern=PATTERN, piece_id=24, dropset_index=8,
               moves_since_chain=24, remainder=147)
    req = request(own)
    req['enemy']['normal_chain_max'] = 0
    req['solo_options'] = dict(beam_width=250, beam_depth=16)
    req['second_target_chain'] = 14
    return req


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.engine = ModeBattleEngine(NATIVE, SOLO, ROOT / 'config.json')
        self.cfg = self.engine.policy['normal_build']['conversion']
        self.cfg['reuse_visible'] = True

    def tearDown(self):
        self.engine.close()

    def probe(self, req=None, **changes):
        req = copy.deepcopy(req or case())
        self.engine.mode_side(req['self'])
        options = {k: v for k, v in self.cfg.items()
                   if k not in ('enabled', 'min_cells', 'critical_safe_moves', 'main_min_chain', 'first_main_chain')}
        context = changes.pop('enemy_context', dict(kind='normal_opening', first_main_chain=8))
        options.update(changes)
        return self.engine.native.ask(dict(op='normal_conversion', field=req['self']['field'],
            queue=req['self']['queue'], character='ally', dropset_index=req['self']['dropset_index'],
            remainder=req['self']['remainder'], target_point=req['target_point'], options=options,
            timing=ChainTiming().native(), gauge=0, gain=1,
            enemy_context=context,
            weights=self.engine.solo.sets['fever']))

    def test_opening_requires_observed_history_before_first_main_or_fever(self):
        req = case()
        for history in (None, 8, 10):
            req['enemy']['normal_chain_max'] = history
            self.assertIsNone(enemy_context(req, req['enemy'], 8))
        req['enemy']['normal_chain_max'] = 3
        self.assertEqual(enemy_context(req, req['enemy'], 8)['kind'], 'normal_opening')
        req['enemy']['mode_generation'] = 2
        self.assertIsNone(enemy_context(req, req['enemy'], 8))

    def test_fever_requires_extending_or_live_turnover(self):
        req = case()
        req['enemy'] = side('fever', ['......']*13+['RRR...'])
        self.assertEqual(enemy_context(req, req['enemy'], 8)['kind'], 'fever_extending')
        req['enemy']['awaiting_seed'] = True
        self.assertIsNone(enemy_context(req, req['enemy'], 8))
        req['enemy_chain'] = dict(elapsed=0)
        ctx = enemy_context(req, req['enemy'], 8, dict(their_end=100))
        self.assertEqual(ctx['kind'], 'fever_turnover')
        self.assertIsNone(enemy_context(req, req['enemy'], 8, dict(their_end=900)))

    def test_turnover_needs_actual_send_in_the_window(self):
        opening = self.probe()
        end = opening['attack_end']
        ctx = dict(kind='fever_turnover', their_end=end, window=0, enemy_reply=0)
        result = self.probe(enemy_context=ctx)
        self.assertTrue(result['found'], result)
        self.assertEqual(result['attack_end'], end)
        self.assertEqual(result['fire_moves'], 1)
        ctx.update(their_end=10000)
        self.assertFalse(self.probe(enemy_context=ctx)['found'])
        ctx.update(their_end=end, enemy_reply=100000)
        self.assertFalse(self.probe(enemy_context=ctx)['found'])

    def test_prepared_conversion_expires_after_first_main(self):
        req = case()
        guard = disruption.contract(req, dict(reason='normal_capacity_conversion',
            capacity_conversion=dict(enemy_context=dict(kind='normal_opening', first_main_chain=8))), {})
        reply = dict(disruption_timing=guard)
        self.assertTrue(disruption.valid(reply, req))
        req['enemy']['normal_chain_max'] = 8
        self.assertFalse(disruption.valid(reply, req))

    def test_visible_path_replays_without_a_large_or_unknown_clear(self):
        req = case()
        result = self.probe(req)
        self.assertTrue(result['found'], result)
        field = req['self']['field']
        self.assertLessEqual(len(result['path']), len(req['self']['queue']))
        for depth, move in enumerate(result['path']):
            step = self.engine.native.ask(dict(op='transition', field=field,
                piece=req['self']['queue'][depth], x=move['x'], r=move['r']))
            self.assertFalse(step['dead'])
            self.assertEqual(step['field'], move['field'])
            self.assertEqual(len(step['links']), move['chain'])
            self.assertLessEqual(move['chain'], 5)
            if depth < len(result['path']) - 1:
                self.assertEqual(move['chain'], 0)
            field = step['field']
        self.assertGreater(result['conversion_chain'], 0)
        self.assertGreaterEqual(result['sent'], self.cfg['min_sent'])
        self.assertGreaterEqual(result['remaining_material'], self.cfg['min_material'])
        self.assertEqual(len(result['repair_chains']), 6)
        self.assertGreaterEqual(min(result['repair_chains']), self.cfg['min_recovery'])
        self.assertGreaterEqual(result['next_safe_moves'], self.cfg['min_safe'])

    def test_full_board_with_only_ten_chain_moves_does_not_invent_a_split(self):
        req = case()
        req['self'].update(field=FULL, queue=['2:RY', '2:BG', '2:BR'], dropset_index=10)
        result = self.probe(req)
        self.assertFalse(result['found'])
        self.assertFalse(result['budget_exhausted'])

    def test_unpromising_recovery_or_material_does_not_authorize_conversion(self):
        for changes in (dict(min_material=78), dict(min_recovery=19), dict(min_sent=10000)):
            with self.subTest(changes=changes):
                self.assertFalse(self.probe(**changes)['found'])

    def test_node_limit_is_reported_without_claiming_no_conversion_exists(self):
        result = self.probe(max_nodes=1)
        self.assertTrue(result['budget_exhausted'])
        self.assertEqual(result['expanded'], 1)

    def test_invalid_limits_or_wrong_cycle_are_rejected(self):
        for changes in (dict(max_chain=6), dict(repair_width=0), dict(depth=0), dict(shortlist=True)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.probe(**changes)
        req = case()
        req['self']['queue'][0] = '0:R'
        with self.assertRaises(ValueError):
            self.probe(req)

    def test_policy_fires_a_real_three_chain_before_forced_full(self):
        answer = self.engine.answer(case())
        self.assertEqual(answer['reason'], 'normal_capacity_conversion', answer)
        self.assertEqual(answer['next_chain'], 3)
        self.assertEqual(answer['next_score'],2460)
        self.assertTrue(all(a>=b for a,b in zip(answer['capacity_conversion']['retained_points'],
                                               answer['capacity_conversion']['required_points'])))

    def test_reused_visible_path_is_exact_and_never_includes_a_single_clear(self):
        req = case()
        self.engine.mode_side(req['self'])
        capacity = self.engine.native.ask(dict(op='normal_capacity', field=BOARD,
            queue=req['self']['queue'], character='ally', margin=1, target=15, threat=False))
        forecast = capacity['small_chain']
        self.assertTrue(forecast['reused_visible'])
        self.assertIn(forecast['conversion_chain'], (2, 3, 4))
        field = req['self']['field']
        for depth, move in enumerate(forecast['path']):
            step = self.engine.native.ask(dict(op='transition', field=field,
                piece=req['self']['queue'][depth], **move))
            self.assertFalse(step['dead'])
            self.assertEqual(len(step['links']), forecast['conversion_chain']
                if depth == len(forecast['path'])-1 else 0)
            field = step['field']
        self.assertGreaterEqual(sum(c not in '.#' for r in field for c in r), 24)

    def test_opening_does_not_start_a_conversion_or_recovery_search(self):
        original = self.engine.native.ask
        operations = []
        def ask(req, *args, **kwargs):
            operations.append(req['op'])
            return original(req, *args, **kwargs)
        with patch.object(self.engine.native, 'ask', side_effect=ask):
            self.engine.answer(case())
        self.assertNotIn('normal_conversion', operations)

    def test_capacity_does_not_offer_relief_under_threat(self):
        req = case()
        self.engine.mode_side(req['self'])
        for threat in (False, True):
            result = self.engine.native.ask(dict(op='normal_capacity', field=BOARD,
                queue=req['self']['queue'], character='ally', margin=1, target=15, threat=threat))
            self.assertEqual(result['small_chain'] is None, threat)

    def test_root_projections_are_preserved_before_leveling_penalties(self):
        req = case()
        self.engine.mode_side(req['self'])
        native_req = dict(rule='fever',solo=True, character='ally', dropset_index=8,
            self=dict(field=['......']*13+['RRR...'],queue=['2:RG','2:BY','2:RY']),
            plain_pairs=True,special_moves=True,trigger=19,beam_width=10,beam_depth=4)
        profiles = []
        for penalty in (0,40000):
            weights = dict(self.engine.solo.sets['fever'],level_root=penalty)
            answer = self.engine.native.ask(dict(op='solo',request=native_req,weights=weights))
            profiles.append({(r['x'],r['r']):r['points'] for r in answer['root_values']})
        self.assertTrue(profiles[0])
        self.assertEqual(profiles[0],profiles[1])
        self.assertTrue(all(len(v)==6 for v in profiles[0].values()))

    def test_residual_comparison_requires_every_virtual_bag_to_hold(self):
        req = case()
        baseline = dict(reason='normal_build_or_fire', chain=1, x=0, r='U',
            normal_root_values=[dict(x=0,r='U',points=[10000]*6,next_room=1),
                                dict(x=1,r='R',points=[20000]*5+[9000],next_room=1)])
        baseline['normal_root_queue'] = req['self']['queue']
        capacity = dict(available_chain=8, quiet_moves=2,
            small_immediate=[dict(choice=dict(x=1,r='R'),conversion_chain=3,
                conversion_points=2460,remaining_material=39,rank=100)])
        helper = self.engine.normal_conversion
        options = dict(build_chain=15,trigger=15)
        with patch.object(self.engine.native, 'ask') as native:
            self.assertIsNone(helper.choose(req, req['self'],req['enemy'],baseline,
                options,capacity,self.cfg,{}))
        native.assert_not_called()
        baseline['normal_root_values'][1]['points']=[10000]*6
        baseline['normal_root_queue'] = req['self']['queue'][:2]
        with patch.object(self.engine.native, 'ask') as native:
            self.assertIsNone(helper.choose(req,req['self'],req['enemy'],baseline,
                options,capacity,self.cfg,{}))
        native.assert_not_called()
        baseline['normal_root_queue'] = req['self']['queue']
        actual = dict(dead=False,links=[dict(groups=[4],colors=1)]*3,
                      field=BOARD,all_clear=False)
        with patch.object(self.engine.native, 'ask',return_value=actual) as native:
            selected = helper.choose(req,req['self'],req['enemy'],baseline,
                options,capacity,self.cfg,{})
        self.assertEqual(selected['next_chain'],3)
        self.assertEqual(selected['capacity_conversion']['retained_points'],[10000]*6)
        self.assertEqual(native.call_count,1)
        self.assertEqual(native.call_args.args[0]['op'],'transition')

    def test_cold_miss_disables_side_frontier_but_warm_cache_is_preserved(self):
        req=case()
        cold=copy.deepcopy(req)
        cold['cold_spawn']=True
        original=self.engine.native.ask
        builds=[]
        def ask(request,*args,**kwargs):
            if request['op']=='solo': builds.append(request['request'])
            return original(request,*args,**kwargs)
        with patch.object(self.engine.native,'ask',side_effect=ask):
            self.engine.answer(cold)
        self.assertTrue(builds)
        self.assertTrue(all(r['side_frontier_slots']==0 and r['beam_width']<=50 for r in builds))
        self.engine.normal_build_cache=None
        warm=self.engine.answer(req)
        builds.clear()
        with patch.object(self.engine.native,'ask',side_effect=ask):
            reused=self.engine.answer(cold)
        self.assertEqual(builds,[])
        self.assertTrue(reused['normal_build_search_reused'])
        self.assertEqual((reused['x'],reused['r']),(warm['x'],warm['r']))

    def test_recorded_three_chain_rebuilds_to_thirteen_with_three_visible_pieces(self):
        pieces=json.loads((ROOT/'data/fever/golden/visible-relief-rebuild.json').read_text(encoding='utf-8'))['pieces']
        req=case()
        req['self']['normal_chain_max']=0
        self.engine.policy['normal_tactics']['quiet']=False
        fires=[]
        for offset in range(len(pieces)-2):
            own=req['self']
            own.update(queue=pieces[offset:offset+3],piece_id=24+offset,dropset_index=(8+offset)%16)
            req['frame']=offset*60
            req['observation'].update(frame_before=req['frame'],frame_after=req['frame'])
            own['observed_frame']=req['enemy']['observed_frame']=req['frame']
            answer=self.engine.answer(req)
            step=self.engine.native.ask(dict(op='transition',field=own['field'],piece=own['queue'][0],x=answer['x'],r=answer['r']))
            self.assertFalse(step['dead'])
            chain=len(step['links'])
            if chain:fires.append((offset,chain,sum(self.engine.scoring.chain('ally',step['links']))))
            if offset==0:
                self.assertEqual(answer['reason'],'normal_capacity_conversion')
                self.assertEqual(chain,3)
            own['field']=step['field']
            own['normal_chain_max']=max(own['normal_chain_max'],chain)
            own['moves_since_chain']=0 if chain else own['moves_since_chain']+1
            if chain>=13:break
        self.assertGreaterEqual(max(c for _,c,_ in fires),13)
        self.assertGreaterEqual(max(score for _,c,score in fires if c>=13),94200)

    def test_frontier_reuses_same_six_searches_to_read_the_residual_main(self):
        req=case()
        self.engine.mode_side(req['self'])
        request=dict(rule='fever',solo=True,character='ally',dropset_index=8,
            self=dict(field=BOARD,queue=req['self']['queue']),plain_pairs=True,special_moves=True,
            trigger=15,build_chain=15,panic_count=70,panic_chain=13,panic_step=2,
            beam_width=250,beam_depth=16,margin=1,preserve_build=True)
        minima=[]
        for slots in (0,4):
            answer=self.engine.solo.ask(dict(request,side_frontier_slots=slots))
            root=next(r for r in answer['root_values'] if (r['x'],r['r'])==(1,'R'))
            self.assertEqual(len(root['points']),6)
            self.assertEqual(answer['search_virtual_depths'],[16]*6)
            minima.append(min(root['points']))
        self.assertGreater(minima[1],minima[0])
        self.assertGreaterEqual(minima[1],27600)

    def test_disabled_conversion_does_not_reserve_a_frontier(self):
        self.cfg['enabled']=False
        original=self.engine.native.ask
        builds=[]
        def ask(request,*args,**kwargs):
            if request['op']=='solo':builds.append(request['request'])
            return original(request,*args,**kwargs)
        with patch.object(self.engine.native,'ask',side_effect=ask):
            self.engine.answer(case())
        self.assertTrue(builds)
        self.assertTrue(all(r.get('side_frontier_slots',0)==0 for r in builds))

    def test_near_target_main_and_post_side_rebuild_are_protected(self):
        req=case()
        helper=self.engine.normal_conversion
        baseline=dict(reason='normal_build_or_fire',chain=1,x=0,r='U',
            normal_root_queue=req['self']['queue'],
            normal_root_values=[dict(x=0,r='U',points=[10000]*6,next_room=1),
                                dict(x=1,r='R',points=[10000]*6,next_room=1)])
        capacity=dict(available_chain=12,quiet_moves=1,
            small_immediate=[dict(choice=dict(x=1,r='R'),conversion_chain=3,
                conversion_points=2460,remaining_material=39,rank=100)])
        for seen, main in [(0,12),(2,8),(3,8),(None,8),(13,8)]:
            req['self']['normal_chain_max']=seen
            if seen==13: req['self']['moves_since_chain']=0
            capacity['available_chain']=main
            with patch.object(self.engine.native,'ask') as native:
                self.assertIsNone(helper.choose(req,req['self'],req['enemy'],baseline,
                    dict(build_chain=15,trigger=15),capacity,self.cfg,{}))
            native.assert_not_called()

    def test_threats_and_adequate_mains_keep_the_existing_decision(self):
        req = case()
        helper = self.engine.normal_conversion
        baseline = dict(reason='normal_build_or_fire', chain=0)
        options = dict(beam_width=250, beam_depth=16, build_chain=15, trigger=15)
        capacity = dict(available_chain=11, safe_moves=5)
        for change in ('disabled', 'packet', 'enemy_chain', 'in_flight', 'fever', 'main', 'room', 'rate'):
            with self.subTest(change=change):
                test = copy.deepcopy(req)
                config = dict(self.cfg)
                space = dict(capacity)
                margin = {}
                if change == 'disabled': config['enabled'] = False
                elif change == 'packet': test['self']['unconfirmed'] = 1
                elif change == 'enemy_chain': test['enemy_chain'] = {'elapsed': 0}
                elif change == 'in_flight': test['observation']['in_flight'] = {'self': {'incoming_in_flight': 1}}
                elif change == 'fever': test['enemy']['mode'] = 'fever'
                elif change == 'main': space['available_chain'] = 13
                elif change == 'room': space['safe_moves'] = 7
                else: margin['rate_events'] = [{'frame': 10}]
                with patch.object(self.engine.native, 'ask') as native:
                    self.assertIsNone(helper.choose(test, test['self'], test['enemy'], baseline,
                                                    options, space, config, margin))
                native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
