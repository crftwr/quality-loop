"""This machine kept from idle sleep while a run is going (issue #16).

A run is mostly waiting - on a session, on a VM - and a machine left alone
for it goes to sleep: a Mac on battery within minutes. Nothing fails; the
run just stops while it sleeps, and a VM guest stops with it. One run of
43 minutes had spent 40 of them asleep.

So the runner holds the platform's "the system is busy" assertion for the
length of the run, and lets go when it ends. The display may still sleep,
and closing a laptop's lid still sleeps it: those are the person's to choose.

- macOS: ``caffeinate -i -w <this pid>``, which also ends with this process
  if it dies without letting go.
- Windows: ``SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)``
  from the runner's thread, cleared at the end (and by Windows when the
  process exits).
- Elsewhere nothing is held.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@contextlib.contextmanager
def held(say=print):
    """Idle sleep held off for the ``with`` block, where the platform allows."""
    release = _hold()
    if release is None:
        yield False
        return
    say("awake:   idle sleep is held off for the run (closing the lid still sleeps it)")
    try:
        yield True
    finally:
        release()


def _hold():
    if sys.platform == "darwin":
        return _hold_mac()
    if os.name == "nt":
        return _hold_windows()
    return None


def _hold_mac():
    caffeinate = shutil.which("caffeinate")
    if caffeinate is None:
        return None
    try:
        process = subprocess.Popen([caffeinate, "-i", "-w", str(os.getpid())],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
    except OSError:
        return None

    def release():
        process.terminate()
        try:
            process.wait(5)
        except subprocess.TimeoutExpired:
            process.kill()

    return release


def _hold_windows():
    import ctypes
    try:
        kernel32 = ctypes.WinDLL("kernel32")
    except OSError:
        return None
    kernel32.SetThreadExecutionState.restype = ctypes.c_uint
    kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
    if not kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
        return None
    return lambda: kernel32.SetThreadExecutionState(ES_CONTINUOUS)
