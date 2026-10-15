"""Per-mutant time budget for the slow controller mutation steps (B47; Claude-Mac, goatai#2350 6186991728).

Log only, never a verdict. Each mutant's CAUGHT/MISSED line gets its elapsed seconds, and the step ends with one
budget line: mutants, total and mean seconds, the slowest three, and every mutant over the per-mutant budget
(GOAT_MUTANT_BUDGET_SECONDS, default 60 s) as a GitHub Actions ::warning:: so a step drifting toward the shard
timeout (controller-mutation-shard.yml, 60 min) is visible in the run summary before it cancels a shard.
Stdlib only; works with an embedded Python that ignores cwd (the importing script puts its own folder on sys.path).
"""
import os
import threading
import time

DEFAULT_BUDGET_SECONDS = 60.0


def budget_seconds(environ=None):
    """GOAT_MUTANT_BUDGET_SECONDS when it is a positive number, else the default."""
    value = (os.environ if environ is None else environ).get('GOAT_MUTANT_BUDGET_SECONDS', '')
    try:
        number = float(value)
    except ValueError:
        return DEFAULT_BUDGET_SECONDS
    return number if number > 0 else DEFAULT_BUDGET_SECONDS


class MutantClock:
    def __init__(self, step, budget=None, clock=time.monotonic):
        self.step, self.clock = step, clock
        self.budget = budget_seconds() if budget is None else budget
        self.laps = []
        self._lock = threading.Lock()

    def start(self):
        return self.clock()

    def lap(self, label, started):
        """Record one mutant; returns the ' (12.3s)' suffix for its CAUGHT/MISSED line."""
        seconds = self.clock() - started
        with self._lock:
            self.laps.append((seconds, label))
        return ' (%.1fs)' % seconds

    def timed(self, label, func, *args):
        """func(*args), recording its time under label (for a thread pool)."""
        started = self.start()
        try:
            return func(*args)
        finally:
            self.lap(label, started)

    def seconds(self, label):
        return next((s for s, name in self.laps if name == label), None)

    def report_lines(self):
        total = sum(s for s, _ in self.laps)
        slowest = sorted(self.laps, reverse=True)[:3]
        over = [(s, name) for s, name in sorted(self.laps, reverse=True) if s > self.budget]
        lines = ['mutation budget %s: %d mutants, %.1f s total, %.1f s mean, budget %.0f s per mutant, slowest: %s'
                 % (self.step, len(self.laps), total, total / len(self.laps) if self.laps else 0.0, self.budget,
                    '; '.join('%s %.1fs' % (name, s) for s, name in slowest) or 'none')]
        lines += ['::warning title=Mutant over budget::%s: "%s" took %.1f s (budget %.0f s)' % (self.step, name, s, self.budget)
                  for s, name in over]
        return lines

    def report(self):
        for line in self.report_lines():
            print(line, flush=True)
