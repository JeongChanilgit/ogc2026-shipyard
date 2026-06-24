# instrument.py
#
# OGC 2026 -- analysis instrument ("분석 장치") for the shipyard solver.
#
# WHAT THIS IS
#   A zero-overhead, OFF-by-default tracer.  When enabled it records, for a
#   single algorithm() call, *how the code behaves* (phase timings, decode
#   throughput, ALNS operator behaviour, the wall-clock budget) and *how the
#   solution evolves* (objective trajectory, candidate ladder, gate decisions).
#   tools/analyze_run.py reads the resulting JSON and turns it into a report
#   whose "Diagnostics" section is a ready-made list of improvement points.
#
# WHY IT IS SAFE FOR SUBMISSION (invariants in notes/dev-plan.md §4)
#   * Disabled unless the OGC_TRACE environment variable is set.  The evaluation
#     server never sets it, so get_tracer() returns a NullTracer whose every
#     method is an empty `pass` -> literally no behaviour change, no I/O, no risk.
#   * Even when ENABLED, every public method is wrapped so it can NEVER raise
#     into the solver (invariant §4.7: crash 0).  Events are appended to an
#     in-memory list and written once, at flush(), at the very end of the run.
#   * Bare-importable (invariant §4.8); pure stdlib (json/os/time); the analyzer
#     pulls in matplotlib, never this module.
#
# ENABLING
#   set  OGC_TRACE=1                 -> traces -> results/traces/
#   set  OGC_TRACE=/path/to/dir      -> traces -> that directory
#   (tools/run_local.py --trace sets this for you.)

from __future__ import annotations

import json
import os
import sys
import time

_ENV_FLAG = "OGC_TRACE"
_DEFAULT_DIR = os.path.join("results", "traces")

_BIMODAL_ENV_FLAG = "OGC_BIMODAL_LOG"
_BIMODAL_STDERR_FLAG = "OGC_BIMODAL_STDERR"
_BIMODAL_DEFAULT_PATH = os.path.join("results", "bimodal", "events.jsonl")
_bimodal_recorder = None


# ---------------------------------------------------------------------------
# Null tracer -- the default.  Every method is a no-op; `enabled` is False so
# hot loops can skip building event payloads entirely (`if tr.enabled: ...`).
# ---------------------------------------------------------------------------

class _NullPhase:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class NullTracer:
    enabled = False

    def meta(self, **_kw):
        pass

    def log(self, _kind, **_data):
        pass

    def phase(self, _name):
        return _NullPhase()

    def flush(self):
        return None


# ---------------------------------------------------------------------------
# Real tracer
# ---------------------------------------------------------------------------

class _Phase:
    """Context manager that records a phase's wall-clock span as one event."""

    def __init__(self, tracer: "Tracer", name: str):
        self._tr = tracer
        self._name = name
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            dur = time.monotonic() - self._t0
            self._tr.log("phase", name=self._name, seconds=dur,
                         error=None if exc is None else repr(exc))
        except Exception:
            pass
        return False  # never suppress solver exceptions


class Tracer:
    """Collects events for one algorithm() call and flushes them to JSON.

    Time is recorded as `t` = seconds since the tracer was created (which the
    caller aligns with the solver's own t_start), so the trace timeline matches
    the deadlines the solver computes.
    """

    enabled = True

    def __init__(self, out_dir: str, run_name: str):
        self._t0 = time.monotonic()
        self._out_dir = out_dir
        self._run_name = run_name
        self._meta: dict = {"run_name": run_name}
        self._events: list[dict] = []

    # -- recording ----------------------------------------------------------
    def meta(self, **kw):
        try:
            self._meta.update(kw)
        except Exception:
            pass

    def log(self, kind: str, **data):
        try:
            ev = {"t": round(time.monotonic() - self._t0, 6), "kind": kind}
            ev.update(data)
            self._events.append(ev)
        except Exception:
            pass

    def phase(self, name: str):
        return _Phase(self, name)

    # -- output -------------------------------------------------------------
    def flush(self):
        """Write the trace JSON.  Returns the path, or None on any failure."""
        try:
            os.makedirs(self._out_dir, exist_ok=True)
            # filename: <run_name>_<wallclock-int>.json  (unique per run)
            stamp = int(time.time() * 1000) % 1_000_000_000
            safe = "".join(c if (c.isalnum() or c in "._-") else "_"
                           for c in self._run_name)[:80]
            path = os.path.join(self._out_dir, f"trace_{safe}_{stamp}.json")
            payload = {
                "schema": "ogc2026-trace/1",
                "meta": self._meta,
                "events": self._events,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            return path
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_tracer(run_name: str = "run") -> "Tracer | NullTracer":
    """Return a real Tracer iff OGC_TRACE is set, else a NullTracer.

    Never raises -- on any error it degrades to NullTracer so the solver is
    unaffected.
    """
    try:
        flag = os.environ.get(_ENV_FLAG, "").strip()
        if not flag or flag.lower() in ("0", "false", "off", "no"):
            return NullTracer()
        out_dir = _DEFAULT_DIR if flag.lower() in ("1", "true", "on", "yes") else flag
        return Tracer(out_dir, run_name)
    except Exception:
        return NullTracer()


# ---------------------------------------------------------------------------
# Bimodal probe -- OFF by default, JSONL when explicitly armed.
# ---------------------------------------------------------------------------

class _BimodalRecorder:
    """Buffered JSONL recorder for the prob_13/14/15 bimodality audit.

    This is intentionally separate from Tracer above: the normal trace is a rich
    per-run artifact, while this probe is a many-run reducer.  When disabled,
    every public helper below is a no-op.  When enabled, events are kept in
    memory and flushed in batches so the probe perturbs wall-clock timing as
    little as possible.
    """

    enabled = True

    def __init__(self, path: str, run_name: str, meta: dict):
        self._path = path
        self._t0 = time.monotonic()
        self._seq = 0
        self._events: list[dict] = []
        self._meta: dict = {}
        self._run_id = os.environ.get("OGC_BIMODAL_RUN_ID", "").strip()
        if not self._run_id:
            stamp = int(time.time() * 1000) % 1_000_000_000
            self._run_id = f"{run_name}-{os.getpid()}-{stamp}"
        self.update_meta(run_name=run_name, pid=os.getpid(), **meta)

    def update_meta(self, **meta):
        try:
            self._meta.update({k: v for k, v in meta.items() if v is not None})
        except Exception:
            pass

    def log(self, kind: str, **data):
        try:
            self._seq += 1
            ev = {
                "schema": "ogc2026-bimodal/1",
                "run_id": self._run_id,
                "seq": self._seq,
                "t": round(time.monotonic() - self._t0, 6),
                "kind": kind,
            }
            ev.update(self._meta)
            ev.update(data)
            self._events.append(ev)
        except Exception:
            pass

    def flush(self):
        try:
            if not self._events:
                return None
            parent = os.path.dirname(os.path.abspath(self._path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            events, self._events = self._events, []
            with open(self._path, "a", encoding="utf-8") as f:
                for ev in events:
                    line = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
                    f.write(line + "\n")
                    if os.environ.get(_BIMODAL_STDERR_FLAG, "").strip():
                        try:
                            print(line, file=sys.stderr)
                        except Exception:
                            pass
            return self._path
        except Exception:
            return None


def _bimodal_path_from_env() -> str | None:
    try:
        flag = os.environ.get(_BIMODAL_ENV_FLAG, "").strip()
        if not flag or flag.lower() in ("0", "false", "off", "no"):
            return None
        if flag.lower() in ("1", "true", "on", "yes"):
            return _BIMODAL_DEFAULT_PATH
        return flag
    except Exception:
        return None


def bimodal_start(run_name: str = "run", **meta) -> bool:
    """Arm/update the bimodal recorder if OGC_BIMODAL_LOG is set.

    Never raises.  Returns True only when events will be recorded.
    """
    global _bimodal_recorder
    try:
        path = _bimodal_path_from_env()
        if path is None:
            return False
        if _bimodal_recorder is None:
            _bimodal_recorder = _BimodalRecorder(path, run_name, meta)
            _bimodal_recorder.log(
                "run_start",
                pythonhashseed=os.environ.get("PYTHONHASHSEED"),
            )
        else:
            _bimodal_recorder.update_meta(run_name=run_name, **meta)
        return True
    except Exception:
        _bimodal_recorder = None
        return False


def bimodal_enabled() -> bool:
    try:
        return bool(_bimodal_recorder is not None and _bimodal_recorder.enabled)
    except Exception:
        return False


def bimodal_log(kind: str, **data):
    """Record one bimodal probe event.  Silent unless bimodal_start() armed it."""
    try:
        if _bimodal_recorder is not None:
            _bimodal_recorder.log(kind, **data)
    except Exception:
        pass


def bimodal_flush():
    """Flush pending bimodal events.  Drains the buffer, so repeated calls are OK."""
    try:
        if _bimodal_recorder is not None:
            return _bimodal_recorder.flush()
    except Exception:
        return None
    return None
