"""A run's progress, readable from outside it: run.log and status.json.

The runner has always made a long run watchable for the person who started
it: one line per step of the room, and a "thinking" line when the session goes
quiet, so a long turn and a hung process can be told apart. That went to
stdout only. Started by another agent as a worker process, stdout is captured
by that agent and the person sees nothing until the run finishes, minutes
later - no sign it is going at all, and no way to tell slow from stuck.

So everything said is also appended to ``run.log`` in the run's directory,
flushed per line, and a small ``status.json`` beside it is rewritten on every
change: which room is in which phase, how long, what it has cost, when it was
last active, and where the findings are. ``quality-loop watch`` follows both;
an agent reads ``status.json`` to answer "how is it going?" without reading
the log.

Both files sit in the run's directory, outside every room, and the audit
treats a reach into that directory as a breach: a room once read its own log
to reconstruct its task.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import threading
import time
from typing import Callable

#: The phases a room goes through, in order.
PHASES = ("waiting", "operator-1", "room", "live-check", "collecting", "operator-2",
          "done", "cancelled")

#: What a run as a whole can be.
STATES = ("starting", "running", "done", "cancelled", "failed")


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: pathlib.Path, value) -> None:
    """Replace ``path`` atomically, so a reader never sees half a file.

    On Windows a replace fails while a reader has the file open; the next
    change writes it again, so a miss is only a moment's staleness.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    for _attempt in range(5):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            time.sleep(0.05)
    temporary.unlink(missing_ok=True)


class Progress:
    """What a run says, and where it is, kept where a watcher can read it.

    Attributes:
        directory: The run's directory.
        log: ``run.log``: every line said, prefixed with the room when rooms
            run side by side.
        path: ``status.json``.
        status: What ``status.json`` holds.
    """

    def __init__(self, directory: pathlib.Path, *, product: str, version: str,
                 echo: Callable[[str], None] | None = print, log: bool = True,
                 prefix_rooms: bool = False):
        self.directory = pathlib.Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log = self.directory / "run.log"
        self.path = self.directory / "status.json"
        self.echo = echo
        self.write_log = log
        self.prefix_rooms = prefix_rooms
        self._lock = threading.RLock()
        self._last_write = 0.0
        self.status = {
            "run": self.directory.name, "product": product, "version": version,
            "pid": os.getpid(), "state": "starting", "started": now(), "updated": now(),
            "parallel": 1, "rooms": {}, "cost_usd": 0.0, "findings": None,
        }
        self._write()

    # --- what is said ----------------------------------------------------------

    def say(self, text: str, room: str | None = None) -> None:
        """One message: to the console, to run.log, and to the room's own log."""
        with self._lock:
            if self.echo:
                self.echo(text)
            lines = str(text).split("\n")
            if self.write_log:
                shown = [f"[{room}] {line}" if room and self.prefix_rooms and line else line
                         for line in lines]
                self._append(self.log, shown)
            if room:
                self._append(self.directory / f"{room}.log", lines)
                entry = self.status["rooms"].get(room)
                if entry is not None:
                    entry["last_activity"] = now()
                    entry["thinking"] = False
                    self._write(throttle=True)

    def for_room(self, room: str) -> Callable[[str], None]:
        """``say`` for one room's lines."""
        return lambda text: self.say(text, room)

    @staticmethod
    def _append(path: pathlib.Path, lines: list[str]) -> None:
        with path.open("a", encoding="utf-8") as out:
            out.write("".join(line + "\n" for line in lines))
            out.flush()

    # --- where it is -----------------------------------------------------------

    def plan(self, rooms: list[tuple[str, str, str]], parallel: int = 1) -> None:
        """The rooms this run will drive: ``(label, scenario, variant)``."""
        with self._lock:
            self.status["parallel"] = parallel
            self.status["rooms"] = {
                label: {"scenario": scenario, "variant": variant, "phase": "waiting",
                        "started": None, "finished": None, "cost_usd": 0.0,
                        "last_activity": None, "thinking": False}
                for label, scenario, variant in rooms}
            self.status["state"] = "running"
            self._write()

    def phase(self, room: str, phase: str) -> None:
        """A room moving on."""
        with self._lock:
            entry = self.status["rooms"].setdefault(room, {})
            entry["phase"] = phase
            entry["last_activity"] = now()
            entry["thinking"] = False
            if phase != "waiting" and not entry.get("started"):
                entry["started"] = now()
            if phase in ("done", "cancelled"):
                entry["finished"] = now()
            self._write()

    def thinking(self, room: str, quiet: float) -> None:
        """The room's session has said nothing for ``quiet`` seconds."""
        with self._lock:
            entry = self.status["rooms"].setdefault(room, {})
            entry["thinking"] = True
            entry["quiet_seconds"] = int(quiet)
            self._write()

    def cost(self, room: str, dollars: float) -> None:
        """Add what a session cost to the room and to the run."""
        if not dollars:
            return
        with self._lock:
            entry = self.status["rooms"].setdefault(room, {})
            entry["cost_usd"] = round(entry.get("cost_usd", 0.0) + dollars, 4)
            self.status["cost_usd"] = round(self.status["cost_usd"] + dollars, 4)
            self._write()

    def finish(self, state: str, findings: pathlib.Path | None = None) -> None:
        with self._lock:
            self.status["state"] = state
            self.status["finished"] = now()
            if findings is not None:
                self.status["findings"] = str(findings)
            for entry in self.status["rooms"].values():
                if entry.get("phase") not in ("done", "cancelled"):
                    entry["phase"] = "cancelled"
            self._write()

    def _write(self, throttle: bool = False) -> None:
        # A busy room says several lines a second; the file need not follow
        # each one, only phases and the run's own changes.
        if throttle and time.monotonic() - self._last_write < 1.0:
            return
        self._last_write = time.monotonic()
        self.status["updated"] = now()
        write_json(self.path, self.status)


def read(directory: pathlib.Path) -> dict | None:
    """A run's status.json, or None."""
    try:
        return json.loads((pathlib.Path(directory) / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def process_alive(pid: int | None) -> bool:
    """Whether the run's process is still there, without signalling it."""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def summary(status: dict) -> str:
    """A few lines: the run, then one per room."""
    alive = process_alive(status.get("pid"))
    state = status.get("state", "?")
    if state in ("starting", "running") and not alive:
        state += " (its process is gone - it did not finish)"
    lines = [f"run {status.get('run')}: {state}, ${status.get('cost_usd', 0):.2f}"
             + (f", parallel {status['parallel']}" if status.get("parallel", 1) > 1 else "")]
    for label, entry in status.get("rooms", {}).items():
        phase = entry.get("phase", "?")
        note = ""
        if entry.get("thinking") and phase not in ("done", "cancelled"):
            note = f" - thinking ({entry.get('quiet_seconds', '?')}s quiet)"
        elapsed = _elapsed(entry.get("started"), entry.get("finished"))
        lines.append(f"  {label:<36} {phase:<11} {elapsed:>6}  "
                     f"${entry.get('cost_usd', 0):.2f}{note}")
    if status.get("findings"):
        lines.append(f"  findings: {status['findings']}")
    return "\n".join(lines)


def _elapsed(started: str | None, finished: str | None) -> str:
    if not started:
        return ""
    try:
        begin = datetime.datetime.fromisoformat(started)
        end = (datetime.datetime.fromisoformat(finished) if finished
               else datetime.datetime.now().astimezone())
    except ValueError:
        return ""
    seconds = int((end - begin).total_seconds())
    return f"{seconds // 60}:{seconds % 60:02d}"
