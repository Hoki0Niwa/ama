"""Research-only deadline cap; the native solver and live policy are unchanged."""
from copy import deepcopy

from .first40_benchmark import HORIZON, MAINLINE, LegacyBackend, normal_side


class DeadlineBackend(LegacyBackend):
    def __init__(self, native, config, enabled=True):
        super().__init__(native, config, width=250, depth=8)
        self.enabled = enabled
        self.last_diagnostics = None
        self._calls = []
        self._native_ask = self.engine.native.ask
        # SoloBuilder holds the same JsonProcess; both capacity and solo pass here.
        self.engine.native.ask = self._record_ask

    def _record_ask(self, request, *args, **kwargs):
        if "seed" in request or "seed" in request.get("request", {}):
            raise ValueError("environment seed is not a solver input")
        reply = self._native_ask(request, *args, **kwargs)
        op = request.get("op")
        if op in ("solo", "normal_capacity"):
            body = request["request"] if op == "solo" else request
            queue = body["self"]["queue"] if op == "solo" else body["queue"]
            self._calls.append(dict(op=op, queue=list(queue),
                depth=body.get("beam_depth"), dropset_index=body.get("dropset_index"),
                reply={k: deepcopy(v) for k, v in reply.items() if k != "search_ms"}))
        return reply

    def choose(self, observation):
        self._calls = []
        self.last_diagnostics = None
        t = observation.placed_total
        if self.enabled:
            if type(t) is not int or not 0 <= t < HORIZON:
                raise ValueError("placed_total must be an integer in 0..39")
            if type(observation.normal_chain_max) is not int or not 0 <= observation.normal_chain_max < MAINLINE:
                raise ValueError("first mainline already fired or invalid history")
            if len(observation.visible) != 3:
                raise ValueError("observation requires current + NEXT2")
            remaining = HORIZON - t
            depth = min(self.depth, remaining)
            visible = min(3, remaining)
            own = normal_side(observation.character)
            own.update(field=list(observation.field), queue=list(observation.visible[:visible]),
                dropset_index=observation.dropset_index, piece_id=t, observed_frame=t,
                moves_since_chain=observation.moves_since_chain,
                normal_chain_max=observation.normal_chain_max)
            if self.enemy is None:
                self.enemy = normal_side(observation.character)
                self.enemy["queue"] = list(observation.visible)
            request = dict(self=own, enemy=self.enemy, gauge_gain_on_offset=1,
                solo_options=dict(trigger=15, beam_width=self.width, beam_depth=depth))
            options = self.engine._normal_options(request, own)
            result = self.engine._solo_build(own, options)
            result = dict(result, benchmark_diagnostics=dict(options=deepcopy(options),
                capacity=deepcopy(getattr(self.engine, "normal_capacity", {}))))
        else:
            # No reply decoration or alternative policy on the disabled path.
            result = super().choose(observation)
            remaining, depth, visible = HORIZON - t, self.depth, 3

        capacity = result["benchmark_diagnostics"]["capacity"]
        violations = []
        for d in result.get("search_virtual_depths", []):
            if d > remaining:
                violations.append("search_depth")
        if result.get("fire") and result.get("fire_moves", 0) > remaining:
            violations.append("fire_moves")
        if capacity.get("available_moves", 0) > remaining:
            violations.append("capacity_moves")
        for call in self._calls:
            if len(call["queue"]) > min(3, remaining):
                violations.append("request_queue")
            if call["op"] == "solo" and call["depth"] > remaining:
                violations.append("request_depth")
        self.last_diagnostics = dict(schema="ama.first40.deadline.v1",
            placed_before=t, remaining_before=remaining, deadline_enabled=self.enabled,
            requested_depth=8, effective_depth_limit=depth, visible_count_observed=3,
            visible_count_searched=visible, native_calls=self._calls,
            final_reply={k: deepcopy(v) for k, v in result.items() if k != "search_ms"},
            cache_identity=dict(placed_total=t, character=observation.character,
                dropset_index=observation.dropset_index, queue=list(observation.visible[:visible]),
                depth=depth, enabled=self.enabled),
            violations=sorted(set(violations)))
        if self.enabled and violations:
            raise ValueError("deadline contract violated: " + ",".join(sorted(set(violations))))
        return result
