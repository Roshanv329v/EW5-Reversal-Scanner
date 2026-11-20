"""
EW5 / EW3 runs on several CPU cores.

Python in one Android process runs on one core at a time (the GIL), and Chaquopy has no
multiprocessing. So the app starts separate worker PROCESSES (app.ewscanner.EngineWorker0..5,
each declared with its own android:process), every one with its own Python, and gives each a
share of the stock.csv parts:

    main process                                  worker k (own process, own Python)
    ------------                                  ----------------------------------
    task_k.pkl  (parts, runs, settings)  ──────▶  work(task_k.pkl):
                                                    per part: read it ONCE, run every strategy
                                                    out_k.pkl, progress_k.json, done_k / error_k
    poll progress files, then join the parts  ◀──
    (scan._join: the same rows in the same order as one run over everything)

A worker that does not start, fails or stops reporting has its parts run in the main process,
so a run never fails because of the workers. Without the Android app (desktop, tests) the
same files are handed to local processes, or everything runs in this process.
"""

from __future__ import annotations

import json
import os
import pickle
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Callable, Optional, Sequence

import pandas as pd

from core import data_store as ds, runner
from mobile import scan

MAX_WORKERS = 6                     # EngineWorker0..5 in AndroidManifest.xml
STALL_SECONDS = 240                 # no part finished for this long: a worker died (memory), run its parts here


# ----------------------------------------------------------------------------------
# One worker
# ----------------------------------------------------------------------------------
def _run_part(path: Path, runs: Sequence[tuple[str, runner.RunParams]], keep: Optional[set],
              indicator_cols: Sequence[str], htf_cfg: dict) -> dict[str, pd.DataFrame]:
    df = ds.load_stock_csv(Path(path))
    if keep is not None:
        df = df[df["Ticker"].isin(keep)]
    return {key: runner.run_engine(df, p, indicator_cols, htf_cfg) for key, p in runs}


def work(task_path: str) -> str:
    """Entry point of a worker process: run its parts, write the results next to the task."""
    task_path = Path(task_path)
    k = task_path.stem.split("_")[-1]
    folder = task_path.parent
    try:
        task = pickle.loads(task_path.read_bytes())
        out: dict[str, dict[str, pd.DataFrame]] = {}
        for n, path in enumerate(task["parts"]):
            out[str(path)] = _run_part(path, task["runs"], task["keep"], task["indicator_cols"], task["htf_cfg"])
            (folder / f"progress_{k}.json").write_text(json.dumps({"done": n + 1}), encoding="utf-8")
        tmp = folder / f"out_{k}.pkl.tmp"
        tmp.write_bytes(pickle.dumps(out))
        tmp.replace(folder / f"out_{k}.pkl")
        (folder / f"done_{k}").write_text("ok", encoding="utf-8")
        return "ok"
    except Exception:
        (folder / f"error_{k}").write_text(traceback.format_exc(), encoding="utf-8")
        return "error"


# ----------------------------------------------------------------------------------
# Starting workers: Android services, else local processes (desktop / tests)
# ----------------------------------------------------------------------------------
def _android_start(folder: Path, n: int) -> bool:
    """Start the worker services; any that did not start get an error file (their parts run here)."""
    try:
        from java import jclass                     # Chaquopy, inside the app only
        started = int(jclass("app.ewscanner.EngineWorker").startAll(str(folder), n))
    except Exception:
        started = 0
    for k in range(started, n):
        (folder / f"error_{k}").write_text("not started", encoding="utf-8")
    return started > 0


def _local_start(folder: Path, n: int) -> list:
    """Desktop / tests: the same worker protocol with plain processes."""
    root = Path(__file__).resolve().parent.parent
    env = dict(os.environ, PYTHONPATH=str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return [subprocess.Popen([sys.executable, "-c", "import sys; from mobile import workers; "
                              "workers.work(sys.argv[1])", str(folder / f"task_{k}.pkl")], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for k in range(n)]


def on_android() -> bool:
    try:
        from java import jclass  # noqa: F401
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------------
# The whole run
# ----------------------------------------------------------------------------------
def _split(paths: Sequence[Path], n: int) -> list[list[Path]]:
    """Parts to n workers, biggest first to the least loaded: the workers finish together."""
    shares: list[list[Path]] = [[] for _ in range(n)]
    load = [0] * n
    for path in sorted(paths, key=lambda p: Path(p).stat().st_size, reverse=True):
        k = load.index(min(load))
        shares[k].append(path)
        load[k] += Path(path).stat().st_size
    return [s for s in shares if s]


def run_parts(paths: Sequence[Path], runs: Sequence[tuple[str, runner.RunParams]], keep: Optional[set],
              indicator_cols: Sequence[str], htf_cfg: dict, workers: int, work_dir: Path,
              progress: Optional[Callable[[int, int], None]] = None, local: Optional[bool] = None,
              log: Optional[Callable[[str], None]] = None) -> dict[str, pd.DataFrame]:
    """
    run_engine for every (key, params) in `runs` over every part, on up to `workers` processes.
    Returns key -> the joined results, identical to running the parts one after the other.
    local=None: Android services inside the app, local processes elsewhere.
    """
    paths = [Path(p) for p in paths]
    total = len(paths)
    results: dict[str, dict[str, pd.DataFrame]] = {}
    say = log or (lambda m: None)
    n = max(0, min(int(workers or 0), MAX_WORKERS, total))
    if n >= 2:
        folder = Path(work_dir) / f"run_{uuid.uuid4().hex[:8]}"
        folder.mkdir(parents=True, exist_ok=True)
        shares = _split(paths, n)
        for k, share in enumerate(shares):
            (folder / f"task_{k}.pkl").write_bytes(pickle.dumps(
                {"parts": [str(p) for p in share], "runs": list(runs), "keep": keep,
                 "indicator_cols": list(indicator_cols), "htf_cfg": htf_cfg}))
        use_local = (not on_android()) if local is None else local
        procs = _local_start(folder, len(shares)) if use_local else []
        started = use_local or _android_start(folder, len(shares))
        if started:
            say(f"Engine on {len(shares)} worker processes")
            pending = set(range(len(shares)))
            last_change, last_done = time.time(), -1
            while pending:
                time.sleep(0.4)
                done_parts = 0
                for k in range(len(shares)):
                    if (folder / f"done_{k}").exists() or (folder / f"error_{k}").exists():
                        pending.discard(k)
                        done_parts += len(shares[k]) if (folder / f"done_{k}").exists() else 0
                    else:
                        try:
                            done_parts += json.loads((folder / f"progress_{k}.json").read_text())["done"]
                        except (OSError, ValueError, KeyError):
                            pass
                if progress:
                    progress(done_parts, total)
                if done_parts != last_done:
                    last_change, last_done = time.time(), done_parts
                elif time.time() - last_change > STALL_SECONDS:
                    say(f"Workers {sorted(pending)} stopped reporting: running their parts here")
                    break
            for k in range(len(shares)):
                out = folder / f"out_{k}.pkl"
                if (folder / f"done_{k}").exists() and out.exists():
                    results.update(pickle.loads(out.read_bytes()))
                elif (folder / f"error_{k}").exists():
                    say(f"Worker {k} failed: running its parts here")
            for p in procs:
                if p.poll() is None:
                    p.kill()
        else:
            say("Worker processes not available: one part after the other")
        shutil.rmtree(folder, ignore_errors=True)

    # everything the workers did not deliver (or no workers): here, one part after the other
    for path in paths:
        if str(path) not in results:
            if progress:
                progress(len(results), total)
            results[str(path)] = _run_part(path, runs, keep, indicator_cols, htf_cfg)
    if progress:
        progress(total, total)
    return {key: scan._join([results[str(p)][key] for p in paths]) for key, _ in runs}
