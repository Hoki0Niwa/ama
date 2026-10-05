"""JSON process with bounded response waits and explicit lifetime."""
from __future__ import annotations

import json
import queue
import subprocess
import threading


class JsonProcess:
    def __init__(self, command, cwd=None):
        self.process = subprocess.Popen([str(p) for p in command], cwd=cwd, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, encoding='utf-8',
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.lines = queue.Queue()
        self.lock = threading.Lock()
        def read():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def ask(self, request, timeout=10):
        with self.lock:
            if self.process.poll() is not None:
                raise RuntimeError('engine process is not running')
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
            try:
                line = self.lines.get(timeout=timeout)
            except queue.Empty:
                self.close()  # Never use a stale late reply for a later request.
                raise TimeoutError('engine response deadline exceeded') from None
            if line is None:
                raise RuntimeError('engine closed its output')
            reply = json.loads(line)
            if 'error' in reply:
                raise ValueError(reply['error'])
            return reply

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
