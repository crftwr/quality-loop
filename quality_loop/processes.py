"""The agent sessions a run has going, so a cancel can end every one of them.

With one room at a time, Ctrl-C (or SIGTERM, turned into KeyboardInterrupt)
lands in the thread reading the room's session, which terminates it and
unwinds. With rooms side by side, only the main thread gets the interrupt,
and the sessions are being read in workers. So every session is registered
here while it runs, and a cancel terminates them all; each worker's read loop
then ends, and the worker unwinds through the same ``finally`` that puts the
user's files back.

Never anything harder than terminate: a session killed outright leaves no
result event, and a product killed outright may not put its own state back.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading

_lock = threading.Lock()
_live: set[subprocess.Popen] = set()
cancelled = threading.Event()


@contextlib.contextmanager
def tracked(process: subprocess.Popen):
    """Register ``process`` for as long as the block runs."""
    with _lock:
        _live.add(process)
    if cancelled.is_set():
        process.terminate()
    try:
        yield process
    finally:
        with _lock:
            _live.discard(process)


def cancel_all() -> int:
    """Terminate every registered session. Returns how many there were."""
    cancelled.set()
    with _lock:
        live = list(_live)
    for process in live:
        if process.poll() is None:
            process.terminate()
    return len(live)


def reset() -> None:
    """A new run starts with nothing cancelled."""
    cancelled.clear()
