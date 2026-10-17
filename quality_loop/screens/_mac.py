"""Screens on macOS: Safari for pages, Terminal for scripts, through AppleScript.

Every step of the page load was paid for by a run of the harness this
replaces. `make new document with properties {URL:...}` returns a document
and does not load it, and a plain two-step sets the URL before the new
document is ready. So the window is made, given a moment, given its URL, and
then waited for by the title the page will take. A screen that never arrives
refuses the run instead of buying it: a room that started without its screen
once hunted for its task across every application the operator had open.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import time

from quality_loop.screens import ScreenError


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(script: str) -> str:
    done = subprocess.run(["osascript", "-e", script], capture_output=True,
                          text=True, check=False)
    if done.returncode != 0:
        raise ScreenError(done.stderr.strip() or "osascript failed")
    return done.stdout.strip()


def page_script(url: str) -> str:
    """The AppleScript that opens ``url`` in a Safari window of its own and
    answers that window's id."""
    return f'''tell application "Safari"
    activate
    make new document
    delay 0.5
    set URL of front document to {_quote(url)}
    return id of front window
end tell'''


#: The shell a terminal screen runs in: bash, without the operator's startup
#: files and with a fixed prompt, so the screen reads the same on every machine.
SHELL = "/bin/bash --noprofile --norc"


def wrapper(command: list[str]) -> str:
    """A bash script that clears the screen, runs ``command``, and then stays in
    the fixed shell, so the output is still on screen for the room to read."""
    run = " ".join(_shell_quote(part) for part in command)
    return ("#!/bin/bash\n"
            "printf '\\033c'\n"
            f"{run}\n"
            "export PS1='$ '\n"
            # macOS's bash announces, every time, that zsh is the default now.
            "export BASH_SILENCE_DEPRECATION_WARNING=1\n"
            f"exec {SHELL} -i\n")


def terminal_script(launch: str, title: str) -> str:
    """The AppleScript that runs ``launch`` in a new Terminal window titled
    ``title`` and answers that window's id.

    Terminal types its command into the operator's own default shell, which
    may not be a POSIX shell at all - on one machine it was a shell that knows
    no ``exec``, and the screen never ran. So what is typed is a single
    absolute path with no arguments, which any shell runs, and everything
    else happens in the script it names.
    """
    return f'''tell application "Terminal"
    activate
    set t to do script {_quote(launch)}
    set custom title of t to {_quote(title)}
    set title displays custom title of t to true
    return id of front window
end tell'''


def _shell_quote(part: str) -> str:
    return "'" + part.replace("'", "'\\''") + "'"


def _wait(application: str, window_id: int, title: str, patience: float) -> None:
    deadline = time.monotonic() + patience
    while time.monotonic() < deadline:
        try:
            name = _osascript(f'tell application "{application}" to get name of '
                              f'(first window whose id is {window_id})')
        except ScreenError:
            name = ""
        if title in name:
            return
        time.sleep(0.5)
    raise ScreenError(f"{application} window {window_id} never showed {title!r}. A "
                      f"sheet left over a window blocks this and shows nowhere else, "
                      f"and {application} may need Automation permission.")


def open_page(url: str, title: str, patience: float) -> int:
    window = int(_osascript(page_script(url)))
    _wait("Safari", window, title, patience)
    return window


def open_terminal(command: list[str], title: str, patience: float) -> int:
    directory = pathlib.Path(tempfile.mkdtemp(prefix="quality-loop-terminal-"))
    launch = directory / "screen"
    launch.write_text(wrapper(command), encoding="utf-8")
    launch.chmod(0o755)
    window = int(_osascript(terminal_script(str(launch), title)))
    _wait("Terminal", window, title, patience)
    return window


def _exists(application: str, handle: int) -> bool:
    return _osascript(f'''if application "{application}" is running then
    tell application "{application}" to return (exists (first window whose id is {int(handle)}))
end if
return false''') == "true"


def close(kind: str, handle: int, patience: float = 5.0) -> None:
    """Close the window ``handle``, and make sure it went.

    A Terminal window whose tab still lists a process answers a close with a
    "terminate running processes?" sheet and stays, saying nothing - which is
    how a closed screen used to stay on the desktop. So the processes on that
    window's own terminal are ended first. They are the script this module
    started and the shell around it, found by the tab's tty, so nothing of
    the operator's is touched.
    """
    application = "Safari" if kind == "page" else "Terminal"
    if not _exists(application, handle):
        return
    if kind == "terminal":
        tty = _osascript(f'tell application "Terminal" to get tty of selected tab of '
                         f'(first window whose id is {int(handle)})')
        if tty.startswith("/dev/tty"):
            subprocess.run(["pkill", "-t", tty.removeprefix("/dev/")], check=False)
            time.sleep(0.5)
    _osascript(f'tell application "{application}" to close '
               f'(first window whose id is {int(handle)})')
    deadline = time.monotonic() + patience
    while time.monotonic() < deadline:
        if not _exists(application, handle):
            return
        time.sleep(0.25)
    raise ScreenError(f"{application} window {handle} is still open after closing it")
