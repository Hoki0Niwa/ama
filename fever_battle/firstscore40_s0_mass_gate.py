"""Research-only S0: omit a probe when its public supply cannot make 10 links."""
from dataclasses import asdict, is_dataclass
import json
import math
import time

from .first40_benchmark import HORIZON, MAINLINE, colored, piece_mass
from .firstscore40_backend import ScoreBackend
from .firstscore40_benchmark import TARGETS
from .model import ROOT, dead, settled_field

PUBLIC_KEYS = {'field', 'visible', 'character', 'placed_total', 'dropset_index',
               'moves_since_chain', 'normal_chain_max'}
PATTERNS = {v['id']: v['pattern'] for v in
            json.loads((ROOT/'data/fever/dropsets.json').read_text(encoding='utf-8'))['characters']}


def mass_gate(observation):
    """Fail open to the native validator for unsupported or malformed inputs."""
    result = dict(gate_checked=False, gate_threshold=4*MAINLINE, skip=False,
                  gate_horizon=None, board_colored=None, visible_mass=None, mass_upper=None)
    try:
        o = asdict(observation) if is_dataclass(observation) else observation
        if not isinstance(o, dict) or set(o) != PUBLIC_KEYS:
            raise ValueError('unexpected public observation fields')
        if (HORIZON, MAINLINE) != (40, 10) or o['character'] not in TARGETS:
            raise ValueError('unsupported research contract')
        for key, high in (('placed_total', 39), ('dropset_index', 1000000),
                          ('moves_since_chain', 40), ('normal_chain_max', 9)):
            if type(o[key]) is not int or not 0 <= o[key] <= high:
                raise ValueError('invalid public history')
        if not isinstance(o['field'], (list, tuple)):
            raise ValueError('invalid field')
        field = settled_field(list(o['field']))
        if dead(field): raise ValueError('dead observation')
        visible = o['visible']
        if not isinstance(visible, (list, tuple)) or len(visible) != 3:
            raise ValueError('exactly three visible pieces required')
        pattern = PATTERNS[o['character']]
        for i, value in enumerate(visible):
            if (not isinstance(value, str) or len(value) < 3 or value[1] != ':' or
                    value[0] not in '2LJ40' or any(c not in 'RYGB' for c in value[2:])):
                raise ValueError('invalid piece')
            shape, colors = value[0], value[2:]
            if len(colors) != {'2':2, 'L':3, 'J':3, '4':4, '0':1}[shape]:
                raise ValueError('invalid piece size')
            if shape == 'L' and colors[0] != colors[1]: raise ValueError('invalid L')
            if shape == 'J' and colors[0] != colors[2]: raise ValueError('invalid J')
            if shape == '4' and not (
                colors[0] == colors[1] and colors[2] == colors[3] and colors[0] != colors[2] or
                colors[0] == colors[2] and colors[1] == colors[3] and colors[0] != colors[1]):
                raise ValueError('invalid quad')
            expected = pattern[(o['dropset_index']+i) % 16]
            if expected in 'LJ':
                if shape not in 'LJ' or colors[0] != colors[1 if expected == 'L' else 2]:
                    raise ValueError('piece disagrees with cycle')
            elif shape != expected:
                raise ValueError('piece disagrees with cycle')
        h = min(3, HORIZON-o['placed_total'])
        board, incoming = colored(field), sum(piece_mass(p) for p in visible[:h])
        result.update(gate_checked=True, gate_horizon=h, board_colored=board,
                      visible_mass=incoming, mass_upper=board+incoming,
                      skip=board+incoming < 4*MAINLINE,
                      reason='colored_mass_bound' if board+incoming < 4*MAINLINE else 'sufficient_upper_supply')
    except (KeyError, TypeError, ValueError, IndexError) as error:
        result['reason'] = 'delegate_validation: '+str(error)
    return result


class MassGatePlanner:
    """Only the score-probe RPC is intercepted; B0 state and clocks are unchanged."""
    def __init__(self, delegate):
        self.delegate = delegate
        self.last_guard = None

    @property
    def process(self):
        return self.delegate.process

    def ask(self, request, timeout=10):
        if not isinstance(request,dict) or request.get('op') != 'score-probe':
            return self.delegate.ask(request, timeout=timeout)
        # Never let the shortcut hide validation failures in the native protocol.
        if (set(request) != {'op','observation','work_budget_ms','transition_limit','witness_limit'} or
                type(request['work_budget_ms']) not in (int,float) or
                not math.isfinite(request['work_budget_ms']) or not 0 <= request['work_budget_ms'] <= 5000 or
                any(type(request[k]) is not int or not 0 <= request[k] <= high
                    for k,high in (('transition_limit',16000),('witness_limit',48000)))):
            return self.delegate.ask(request, timeout=timeout)
        begin = time.perf_counter()
        guard = mass_gate(request.get('observation'))
        guard['gate_elapsed_ms'] = (time.perf_counter()-begin)*1000
        self.last_guard = guard
        if guard['skip']:
            return dict(schema='ama.firstscore40.s0_mass_gate.probe.v1', decision=None,
                        score_probe_complete=None, goal_complete=None,
                        probe_status='not_run_mass_impossible', probe_invoked=False,
                        proof_kind='colored_mass_bound', mass_guard=guard,
                        stats=dict(wall_ms=None, transition_attempts=0, expanded_parents=0,
                                   stop_reason='mass_impossible'))
        reply = self.delegate.ask(request, timeout=timeout)
        return dict(reply, mass_guard=guard, probe_invoked=True,
                    probe_status='complete' if reply.get('score_probe_complete') else 'incomplete')

    def close(self):
        self.delegate.close()


class MassGatedScoreBackend(ScoreBackend):
    def __init__(self, native, planner, config, budget_ms=250, planner_budget_ms=25,
                 experiment_deadline=None):
        super().__init__(native, planner, config, 's0', budget_ms,
                         planner_budget_ms, experiment_deadline)
        self.planner = MassGatePlanner(self.planner)

    def choose(self, observation):
        self.planner.last_guard = None
        try:
            return super().choose(observation)
        finally:
            # A failed planner RPC has no reply; preserve its public guard metadata.
            if not self.last_planner and self.planner.last_guard is not None:
                self.last_planner = dict(decision=None, score_probe_complete=None,
                    mass_guard=self.planner.last_guard, probe_invoked=True,
                    probe_status='failed_before_reply', stats={})
