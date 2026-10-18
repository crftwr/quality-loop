"""jot: a note list in the terminal, small enough to read in a minute.

    JOT_HOME=/some/dir python jot.py

The notes are one per line in ``$JOT_HOME/notes.txt``. When
``QUALITY_LOOP_EVENTS`` names a file, jot writes what it does there as JSON
lines - quality-loop's level 1, an event log at the app's own boundary.
"""

import json
import os
import pathlib
import sys
import termios
import tty

HOME = pathlib.Path(os.environ.get("JOT_HOME", pathlib.Path.home() / ".jot"))
NOTES = HOME / "notes.txt"
EVENTS = os.environ.get("QUALITY_LOOP_EVENTS")


def event(**fact):
    if EVENTS:
        with open(EVENTS, "a", encoding="utf-8") as out:
            out.write(json.dumps(fact) + "\n")


def load():
    if not NOTES.exists():
        return []
    return [line for line in NOTES.read_text(encoding="utf-8").splitlines() if line]


def save(notes):
    HOME.mkdir(parents=True, exist_ok=True)
    NOTES.write_text("".join(n + "\n" for n in notes), encoding="utf-8")
    event(kind="saved", count=len(notes))


def draw(notes, selected, status=""):
    out = ["\x1b[2J\x1b[H jot - " + str(len(notes)) + " notes\r\n\r\n"]
    for n, note in enumerate(notes):
        out.append((" > " if n == selected else "   ") + note + "\r\n")
    out.append("\r\n a add  e edit  d delete  q quit\r\n")
    if status:
        out.append(" " + status + "\r\n")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def read_key():
    ch = os.read(0, 1).decode("utf-8", "replace")
    if ch == "\x1b":
        rest = os.read(0, 2).decode("utf-8", "replace")
        return {"[A": "up", "[B": "down"}.get(rest, "esc")
    return ch


def ask(prompt, initial=""):
    """A line of text at the bottom; Enter takes it, Esc gives up."""
    event(kind="prompt", text=prompt)
    typed = initial
    while True:
        sys.stdout.write(f"\r\x1b[K {prompt}{typed}")
        sys.stdout.flush()
        key = read_key()
        if key == "\r":
            return typed
        if key == "esc":
            return None
        if key == "\x7f":
            typed = typed[:-1]
        elif key.isprintable():
            typed += key


def main():
    notes, selected, status = load(), 0, ""
    old = termios.tcgetattr(0)
    tty.setraw(0)
    event(kind="started", notes=len(notes))
    try:
        while True:
            draw(notes, selected, status)
            status = ""
            key = read_key()
            if key == "q":
                event(kind="quit")
                return
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                selected = min(len(notes) - 1, selected + 1)
            elif key == "a":
                text = ask("New note: ")
                if text:
                    notes.append(text)
                    selected = len(notes) - 1
                    save(notes)
                    status = "added"
            elif key == "e" and notes:
                text = ask("Edit: ", notes[selected])
                if text:
                    notes[selected] = text
                    save(notes)
                    status = "changed"
            elif key == "d" and notes:
                # No confirmation: a deliberate rough edge for the operator to find.
                event(kind="deleted", note=notes[selected])
                del notes[selected]
                selected = max(0, min(selected, len(notes) - 1))
                save(notes)
                status = "deleted"
            else:
                status = f"no key {key!r}"
                event(kind="unknown-key", key=key)
    finally:
        termios.tcsetattr(0, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
