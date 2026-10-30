"""One deterministic native computation per complete query and decision request."""
from collections import Counter, OrderedDict
from contextlib import contextmanager
import json

from .worker import JsonProcess


class NativeQueries(JsonProcess):
    # Configuration commands are barriers. Neither incomplete keys nor fields
    # stripped of timing, scoring, queue or strategy controls may share a result.
    PURE = frozenset(('queue', 'solo', 'normal_conversion', 'normal_followup',
        'normal_capacity', 'drop_preview', 'garbage_search', 'seed_search',
        'seed_defense', 'normal_pressure_probe', 'tactics', 'normal_colors',
        'validate', 'stock', 'normal_gaze', 'holding', 'resolve', 'placements',
        'transition', 'finish_probe', 'closing_transition'))
    MAX_BYTES = 8 * 1024 * 1024
    MAX_ENTRIES = 128

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .cancellation import CancelEvent
        self._cancel=CancelEvent()
        self._memo = None
        self.last_work = dict(executed={}, reused={})

    @contextmanager
    def decision(self):
        if self._memo is not None:
            yield
            return
        self._memo = OrderedDict()
        self._memo_bytes = 0
        self._executed, self._reused = Counter(), Counter()
        try:
            yield
        finally:
            self.last_work = dict(executed=dict(self._executed), reused=dict(self._reused))
            self._memo = None

    def ask(self, request, timeout=10):
        self._cancel.check()
        op = request.get('op')
        if self._memo is None:
            return super().ask(request, timeout)
        if op not in self.PURE:
            self._memo.clear()
            self._memo_bytes = 0
            self._executed[op] += 1
            return super().ask(request, timeout)
        key = json.dumps(request, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        found = self._memo.get(key)
        if found is not None:
            self._memo.move_to_end(key)
            self._reused[op] += 1
            return json.loads(found[0])
        reply = super().ask(request, timeout)
        self._executed[op] += 1
        if reply.get('cutoff') or reply.get('search_cutoff'):
            return reply  # A partial result must never suppress a complete search.
        encoded=json.dumps(reply,ensure_ascii=False,separators=(',',':'))
        size=len(key.encode('utf-8'))+len(encoded.encode('utf-8'))
        if size <= self.MAX_BYTES:
            while self._memo and (len(self._memo) >= self.MAX_ENTRIES
                                   or self._memo_bytes + size > self.MAX_BYTES):
                _, (_, removed) = self._memo.popitem(last=False)
                self._memo_bytes -= removed
            self._memo[key] = (encoded, size)
            self._memo_bytes += size
        return reply

    def close(self):
        try:super().close()
        finally:self._cancel.close()
