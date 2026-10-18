"""A terminal app in a pseudo-terminal, its screen kept as text.

The app runs under a pty of a fixed size with ``TERM=xterm-256color``; a
terminal emulator (`pyte`) is kept in step with everything it writes, so the
screen can be read as text at any moment, and keys go in as the bytes an
xterm would send. No window, no focus, nothing the person at the machine can
disturb: this is the deterministic way to drive a TUI.

`pyte` is the one dependency outside the standard library, and only for this:
``pip install quality-loop[tui]``. A terminal emulator good enough for a
curses app - scroll regions, the alternate screen, insert and delete line,
answering the cursor-position query - is not something to rewrite.

POSIX only for now. Windows has ConPTY, which this does not drive yet.
"""

from __future__ import annotations

import os
import pathlib
import select
import signal
import subprocess
import threading
import time

from quality_loop.drive import keys as keynames


class TerminalError(Exception):
    pass


#: Seconds after a lone Esc before the next key. A terminal app cannot tell
#: Esc followed quickly by a key from Alt+that key: it waits a moment (PuiKit
#: 0.1s, ncurses ESCDELAY) for the rest of a sequence. The first XeFM live
#: check sent Esc then Ctrl-T 20ms apart, and the command palette never
#: opened - it had arrived as Alt-Ctrl-T.
ESC_SETTLE = 0.3


def _pyte():
    try:
        import pyte
    except ImportError:
        raise TerminalError("driving a terminal app needs pyte: "
                            "pip install 'quality-loop[tui]'") from None
    return pyte


class PtyApp:
    """One terminal app, running.

    Attributes:
        rows, cols: The terminal's size, which the record states: a TUI's
            layout, and so what a step found where, depends on it.
    """

    def __init__(self, argv: list[str], *, rows: int = 40, cols: int = 120,
                 env: dict | None = None, cwd: str | None = None):
        if os.name == "nt":
            raise TerminalError("terminal apps are driven under a pty, which this "
                                "does not do on Windows yet")
        import fcntl
        import pty  # noqa: F401  (POSIX only; imported for the clear failure)
        import struct
        import termios

        pyte = _pyte()
        self.rows, self.cols = rows, cols
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self._master = master
        # The app's answers to queries (cursor position, device attributes)
        # go back down the pty, or a curses app that asks waits forever.
        self.screen.write_process_input = lambda data: self._write(data.encode("utf-8"))
        # ESCDELAY: how long ncurses waits after an ESC to see whether a
        # sequence follows - a second by default. Short, so a lone Esc is an
        # Esc soon enough for ESC_SETTLE below to cover it.
        environment = {"ESCDELAY": "25", **os.environ, **(env or {}),
                       "TERM": "xterm-256color", "LINES": str(rows), "COLUMNS": str(cols)}
        self.process = subprocess.Popen(
            argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=environment,
            start_new_session=True, close_fds=True)
        os.close(slave)
        self._lock = threading.Lock()
        self._changed = self._sent = time.monotonic()
        self._closed = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        while not self._closed:
            try:
                ready, _w, _x = select.select([self._master], [], [], 0.1)
                if not ready:
                    continue
                data = os.read(self._master, 65536)
            except OSError:
                break
            if not data:
                break
            with self._lock:
                self.stream.feed(data)
                self._changed = time.monotonic()

    def _write(self, data: bytes) -> None:
        if not self._closed:
            os.write(self._master, data)

    def send(self, items: list) -> None:
        """Write a parsed key sequence."""
        for item in items:
            if isinstance(item, keynames.Pause):
                time.sleep(item.seconds)
            elif isinstance(item, keynames.Text):
                self._write(item.text.encode("utf-8"))
            else:
                self._write(keynames.terminal_bytes(item))
                if item.name == "Esc" and not item.mods:
                    time.sleep(ESC_SETTLE)
            time.sleep(0.02)
        self._sent = time.monotonic()

    def text(self) -> str:
        """The screen, one line per row, trailing blanks trimmed."""
        with self._lock:
            lines = [line.rstrip() for line in self.screen.display]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    def cursor(self) -> tuple[int, int]:
        with self._lock:
            return self.screen.cursor.y, self.screen.cursor.x

    def wait_quiet(self, quiet: float = 0.4, patience: float = 10.0) -> bool:
        """Wait until the app has written nothing for ``quiet`` seconds.

        Never a fixed sleep: a slow step would be read half drawn, and a fast
        one would waste the wait. Returns False if it was still writing when
        patience ran out, which the record says.

        Quiet is counted from the last key sent as well as the last output: a
        key the app answers with nothing would otherwise be "settled" at once,
        on the silence from before it - the first live check recorded
        ``waited: 0.0`` exactly there.
        """
        deadline = time.monotonic() + patience
        while time.monotonic() < deadline:
            with self._lock:
                since = time.monotonic() - max(self._changed, self._sent)
            if since >= quiet or self.process.poll() is not None:
                return True
            time.sleep(min(quiet / 4, 0.1))
        return False

    def stop(self, grace: float = 3.0) -> int | None:
        """End the app: its process group, politely and then not."""
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                self.process.wait(grace)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except OSError:
                    pass
                self.process.wait()
        self._closed = True
        try:
            os.close(self._master)
        except OSError:
            pass
        return self.process.returncode

    def save(self, path: pathlib.Path) -> pathlib.Path:
        path.write_text(self.text() + "\n", encoding="utf-8")
        return path
