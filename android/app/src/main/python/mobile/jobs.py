"""One background job at a time (a data update or a screener run), with progress and a log."""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


def _notify(running: bool, text: str) -> None:
    """Tell the Android side (keeps the app alive with a notification). No-op on a desktop."""
    try:
        from java import jclass                       # only exists inside the app (Chaquopy)
        jclass("app.ewscanner.JobService").update(running, text)
    except Exception:
        pass


@dataclass
class Job:
    id: int
    kind: str                       # "update" | "run" | "weekly"
    title: str
    started: float = field(default_factory=time.time)
    done: float = 0.0               # 0..1
    text: str = "Starting…"
    log: list[str] = field(default_factory=list)
    running: bool = True
    result: Any = None
    error: Optional[str] = None
    finished: Optional[float] = None

    def progress(self, done: float, text: str) -> None:
        self.done, self.text = max(0.0, min(1.0, float(done))), text
        _notify(True, f"{self.title}: {text}")

    def say(self, line: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {line}")
        self.text = line

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title, "running": self.running,
                "done": round(self.done, 3), "text": self.text, "log": self.log[-400:],
                "result": self.result, "error": self.error,
                "seconds": round((self.finished or time.time()) - self.started, 1)}


_lock = threading.Lock()
_current: Optional[Job] = None
_counter = 0


def current() -> Optional[dict]:
    return _current.public() if _current else None


def start(kind: str, title: str, work: Callable[[Job], Any]) -> dict:
    """Run `work(job)` in a thread. Refused while another job is running."""
    global _current, _counter
    with _lock:
        if _current is not None and _current.running:
            raise RuntimeError(f"Busy: {_current.title} is still running.")
        _counter += 1
        job = _current = Job(_counter, kind, title)

    def runner() -> None:
        _notify(True, title)
        try:
            job.result = work(job)
            job.done, job.text = 1.0, "Finished"
        except Exception as exc:
            job.error = f"{type(exc).__name__}: {exc}"
            job.log.append(traceback.format_exc())
            job.text = "Failed"
        finally:
            job.running, job.finished = False, time.time()
            _notify(False, "")

    threading.Thread(target=runner, name=f"job-{job.id}", daemon=True).start()
    return job.public()
