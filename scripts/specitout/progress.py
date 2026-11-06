from __future__ import annotations

import contextlib
import contextvars
import sys
import threading
import time
from collections.abc import Callable, Iterator


ImportProgressReporter = Callable[[str, int, int, str], None]
IndexProgressReporter = Callable[[str, int, int, str], None]
_active_reporter: contextvars.ContextVar[IndexProgressReporter | None] = contextvars.ContextVar("progress_reporter", default=None)


@contextlib.contextmanager
def progress_scope(reporter: IndexProgressReporter | None) -> Iterator[None]:
    token = _active_reporter.set(reporter)
    try:
        yield
    finally:
        _active_reporter.reset(token)


def report_active(stage: str, current: int, total: int, message: str) -> None:
    reporter = _active_reporter.get()
    if reporter is not None:
        reporter(stage, current, total, message)


class TimedProgressReporter:
    def __init__(self, label: str, *, heartbeat_seconds: float = 10.0) -> None:
        self.label = label
        self.heartbeat_seconds = heartbeat_seconds
        self._started: float | None = None
        self._last: tuple[str, int, int, str] | None = None
        self._stream = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __call__(self, stage: str, current: int, total: int, message: str) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            if self._started is None:
                self._started = time.monotonic()
                self._stream = sys.stderr
            self._last = (stage, current, total, message)
            self._write(heartbeat=False)
            if self._thread is None:
                self._thread = threading.Thread(target=self._heartbeat, name="specitout-progress", daemon=True)
                self._thread.start()

    def _write(self, *, heartbeat: bool) -> None:
        assert self._last is not None and self._started is not None
        stage, current, total, message = self._last
        count = f" {current}/{total}" if total > 0 else ""
        state = "still processing / waiting - " if heartbeat else ""
        elapsed = time.monotonic() - self._started
        print(f"progress: {self.label} {stage}{count} elapsed={elapsed:.1f}s - {state}{message}", file=self._stream, flush=True)

    def _heartbeat(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            with self._lock:
                if not self._stop.is_set():
                    self._write(heartbeat=True)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def __enter__(self) -> TimedProgressReporter:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def timed_reporter(label: str, *, heartbeat_seconds: float = 10.0) -> TimedProgressReporter:
    return TimedProgressReporter(label, heartbeat_seconds=heartbeat_seconds)
