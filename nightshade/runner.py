"""One explicit, allowlisted job at a time; bounded output and group cancellation."""
import collections
import os
import signal
import subprocess
import threading
import time


class Runner:
    def __init__(self, scripts, root):
        self.scripts = {s['id']: s for s in scripts}
        self.root = root
        self.lock = threading.RLock()
        self.process = None
        self.lines = collections.deque(maxlen=160)
        self.name = 'No script selected'
        self.status = 'idle'
        self.started = 0
        self.result = None

    def snapshot(self):
        with self.lock:
            return dict(name=self.name, status=self.status, lines=list(self.lines),
                        result=self.result, started=self.started)

    def start(self, script_id):
        with self.lock:
            if self.status in ('running', 'stopping'):
                return False
            if script_id not in self.scripts:
                raise ValueError('Unknown script')
            script = self.scripts[script_id]
            self.name = script['name']; self.lines.clear(); self.result = None
            try:
                self.process = subprocess.Popen(script['argv'], cwd=self.root,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, start_new_session=True,
                    env={**os.environ, 'PYTHONUNBUFFERED': '1'})
            except OSError as exc:
                self.status = 'failed'; self.lines.append(str(exc)); return False
            self.status = 'running'; self.started = time.time()
            process = self.process
            timer = threading.Timer(script.get('timeout', 60), self.stop, args=(process, 'timed out'))
            timer.daemon = True; timer.start()
            threading.Thread(target=self._read, args=(process,timer), daemon=True).start()
            return True

    def _read(self, process, timer):
        try:
            while True:
                chunk = process.stdout.readline(1024)
                if not chunk: break
                line = chunk.decode('utf-8', errors='replace').rstrip()
                with self.lock:
                    self.lines.append(''.join(c for c in line if c.isprintable() or c == '\t'))
            result = process.wait()
        finally:
            timer.cancel()
            process.stdout.close()
        with self.lock:
            if self.process is process:
                self.result = result
                if self.status == 'running':
                    self.status = 'complete' if result == 0 else 'failed'
                elif self.status == 'stopping':
                    self.status = 'stopped'

    def stop(self, expected=None, reason='stopped'):
        with self.lock:
            process = self.process
            if not process or self.status not in ('running', 'stopping'):
                return
            if expected is not None and expected is not process:
                return
            self.status = 'stopping'
            self.lines.append('— ' + reason + ' —')
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        def kill():
            # Also terminates children that outlive their parent.
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        timer = threading.Timer(1.5, kill); timer.daemon = True; timer.start()
