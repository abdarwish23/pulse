"""Reversible effects: capabilities that can be mounted and unmounted at runtime.

The pattern is borrowed from Cordis (the plugin framework under DeepSeek
Harness): every registration — a route, a background job, a tool, a value
derived from configuration — answers "how do I remove myself?" with a disposer,
and a Scope unwinds those disposers in reverse order. A capability that can
unmount cleanly does not need a process restart to change.

Nothing here knows about HTTP, SQLite or agents: it is the primitive, and the
server decides which registrations become effects.

Stdlib only, like the rest of Pulse.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

__all__ = ["Scope", "JsonSnapshot", "LiveConfig"]


def _warn(text):
    try:
        sys.stderr.write(f"pulse effects: {text}\n")
        sys.stderr.flush()
    except Exception:  # stderr can be gone when the process is shutting down
        pass


def _noop():
    return None


class Scope:
    """Owns effects and disposes them in reverse order (LIFO).

    ``scope.effect(x)`` takes either a disposer callable or a context manager
    and returns an idempotent disposer for that single effect. A scope can be a
    child of another scope, so disposing the parent tears the whole subsystem
    down. A failing disposer is logged and never prevents the others from
    unwinding; an effect added after disposal runs (and is forgotten) at once,
    so a late registration can never leak silently.
    """

    def __init__(self, name="root", parent=None):
        self.name = name
        self.parent = parent
        self._lock = threading.RLock()
        self._effects = []  # [{"label", "dispose", "done"}], registration order
        self._disposed = False
        if parent is not None:
            parent.effect(self.dispose, label=f"scope:{name}")

    # -- registration --------------------------------------------------------
    def effect(self, target, label=None):
        """Register an effect and return its (idempotent) disposer."""
        if hasattr(target, "__enter__") and hasattr(target, "__exit__"):
            label = label or type(target).__name__
            target.__enter__()
            return self._add(label, lambda: target.__exit__(None, None, None))
        if not callable(target):
            raise TypeError("an effect must be a disposer callable or a context manager")
        label = label or getattr(target, "__qualname__", None) or getattr(target, "__name__", None) or "effect"
        return self._add(label, target)

    def add(self, label, dispose):
        """Explicit form of :meth:`effect`, for call sites that build disposers inline."""
        return self._add(label, dispose)

    def _add(self, label, dispose):
        entry = {"label": label, "dispose": dispose, "done": False}
        with self._lock:
            if self._disposed:
                self._run(entry)  # a disposed scope may not silently keep a capability
                return _noop
            self._effects.append(entry)
        return lambda: self._run(entry)

    # -- disposal ------------------------------------------------------------
    def _run(self, entry):
        with self._lock:
            if entry["done"]:
                return
            entry["done"] = True
            try:
                self._effects.remove(entry)
            except ValueError:
                pass
        try:
            entry["dispose"]()
        except Exception as e:  # one broken disposer must not leak the others
            _warn(f"{self.name}: effect {entry['label']!r} failed to dispose: {e!r}")

    def dispose(self):
        """Unwind every effect, newest first. Returns how many were disposed."""
        with self._lock:
            if self._disposed:
                return 0
            self._disposed = True
            entries = list(reversed(self._effects))
            self._effects.clear()
        for entry in entries:
            self._run(entry)
        return len(entries)

    # -- introspection -------------------------------------------------------
    @property
    def disposed(self):
        return self._disposed

    def pending(self):
        """Labels of the effects still mounted, oldest first."""
        with self._lock:
            return [e["label"] for e in self._effects]

    def __len__(self):
        return len(self._effects)

    def __repr__(self):
        state = "disposed" if self._disposed else f"{len(self._effects)} effect(s)"
        return f"<Scope {self.name}: {state}>"


class JsonSnapshot:
    """A value derived from a JSON file, refreshed when the file changes.

    Reading costs one ``stat``: the file is re-parsed only when its inode,
    modification time or size moves, so a request path can check it on every
    call. A parse failure or a vanished file keeps the last good value and logs
    once, so a half-written config can never take the process down. The new
    value is built completely and then swapped in with a single assignment, so
    concurrent readers see either the old value or the new one, never a partial.

    ``build`` receives the parsed JSON and returns the value to expose.
    """

    def __init__(self, path, build, default=None, label=None):
        self.path = Path(path)
        self.build = build
        self.label = label or self.path.name
        self._value = default
        self._stamp = object()  # sentinel: nothing loaded yet
        self._lock = threading.Lock()
        self._last_error = None
        self.reloads = 0
        self.errors = 0
        self.refresh()

    def _stamp_now(self):
        try:
            st = self.path.stat()
        except OSError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def get(self):
        """Current value, re-reading the file first if it changed."""
        stamp = self._stamp_now()
        if stamp != self._stamp:
            with self._lock:
                if stamp != self._stamp:
                    self._load(stamp)
        return self._value

    def refresh(self):
        """Force a reload now (start-up, tests)."""
        with self._lock:
            self._load(self._stamp_now())

    def _load(self, stamp):
        try:
            value = self.build(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            self._stamp = None
            if self._last_error != "missing":
                _warn(f"{self.label}: {self.path} not found; keeping the last value")
                self._last_error = "missing"
            return
        except Exception as e:
            self.errors += 1
            if self._last_error != repr(e):
                _warn(f"{self.label}: cannot reload {self.path} ({e!r}); keeping the last value")
                self._last_error = repr(e)
            self._stamp = stamp  # do not retry the same broken content on every request
            return
        self._value = value  # single assignment: readers see old or new, never partial
        self._stamp = stamp
        self._last_error = None
        self.reloads += 1

    def __repr__(self):
        return f"<JsonSnapshot {self.label}: {self.reloads} reload(s), {self.errors} error(s)>"


class LiveConfig:
    """Dict-like, live view over a :class:`JsonSnapshot`, with process-local overrides.

    Reads always follow ``config.json``, so an edit to the file applies on the next
    request instead of the next restart — without changing a single call site.
    Writing through this object (``CONFIG["x"] = y``) deliberately does *not* touch
    the file: it sets a process-local override, and the next file change clears it
    again, so the file always wins. Use overrides for tests and one-off experiments;
    real changes go through ``save_config`` so the file stays the source of truth.
    """

    def __init__(self, snapshot):
        self._snapshot = snapshot
        self._lock = threading.RLock()
        self._overrides = {}
        self._seen = snapshot.reloads

    # -- reads ---------------------------------------------------------------
    def data(self):
        """The config as this process sees it now (do not mutate the result)."""
        base = self._snapshot.get()  # refresh first: a reload is what makes the file win
        with self._lock:
            if self._snapshot.reloads != self._seen:  # the file moved: the file wins
                self._overrides.clear()
                self._seen = self._snapshot.reloads
            if not self._overrides:
                return base
            merged = dict(base)
            merged.update(self._overrides)
            return merged

    def __getitem__(self, key):
        return self.data()[key]

    def get(self, key, default=None):
        return self.data().get(key, default)

    def __contains__(self, key):
        return key in self.data()

    def __iter__(self):
        return iter(self.data())

    def __len__(self):
        return len(self.data())

    def keys(self):
        return self.data().keys()

    def items(self):
        return self.data().items()

    def values(self):
        return self.data().values()

    def copy(self):
        return self.data()

    # -- process-local overrides (never written to the file) -----------------
    def __setitem__(self, key, value):
        with self._lock:
            self._seen = self._snapshot.reloads
            self._overrides[key] = value

    def __delitem__(self, key):
        with self._lock:
            self._seen = self._snapshot.reloads
            del self._overrides[key]

    def update(self, *args, **kwargs):
        with self._lock:
            self._seen = self._snapshot.reloads
            self._overrides.update(*args, **kwargs)

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def pop(self, key, *default):
        with self._lock:
            self._seen = self._snapshot.reloads
            return self._overrides.pop(key, *default)

    def clear(self):
        with self._lock:
            self._seen = self._snapshot.reloads
            self._overrides.clear()

    # -- introspection -------------------------------------------------------
    def overrides(self):
        """Keys currently overridden in this process (empty when the file leads)."""
        with self._lock:
            return sorted(self._overrides)

    def __repr__(self):
        return f"<LiveConfig {self._snapshot!r} overrides={self.overrides()}>"
