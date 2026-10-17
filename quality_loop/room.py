"""Building a room: the product's agent-facing surface, the rules, the task.

A room is a directory holding the bundle under test and nothing else the room
may learn from. It may sit inside the product's checkout - next to the rest
of the work, where its notes are kept - only because the session is started
with `--restricted` (see `session`), which stops Claude Code loading the
checkout's CLAUDE.md and skills. A room anywhere else in the checkout is
refused: it would look deliberate and be protected by nothing.
"""

from __future__ import annotations

import pathlib
import shutil
import zipfile

#: The room's own CLAUDE.md, which a correctly started session never sees.
#:
#: `--restricted` skips CLAUDE.md discovery, so under the runner this file is
#: dead weight. Under a plain `cd <room> && claude` it is loaded first - along
#: with the CLAUDE.md of the repository above, which is the contamination it
#: is here to announce. `audit.audit` looks for the phrase it asks for in the
#: room's reply.
CANARY = """\
# If this arrived on its own, stop

**Did you open this file yourself?** Then nothing is wrong - it is a check
addressed to a different reader, and you should carry on with TASK.md.

This text is only a problem if it reached you *without* being asked for, as
part of the context you started with. That would mean the session was started
without `--restricted`, and Claude Code will have loaded the CLAUDE.md of the
repository above this directory too. The measurement this room exists to take
would already be spoilt.

In that case, and only that case: **do not do the task.** Say that the room was
opened without --restricted and stop, because nothing written from there is
evidence about what you were given.
"""

#: What the room is told to write into, already there so that it appends.
QUESTIONS = """\
# What the skill did not tell me

One section per thing you had to guess. Empty means the run measured nothing -
see RULES.md.
"""


class RoomError(Exception):
    """A room that cannot be built where it was asked for."""


def check_location(room: pathlib.Path, rooms: pathlib.Path,
                   checkout: pathlib.Path | None) -> None:
    """Refuse a room inside the checkout but outside its rooms directory."""
    room, rooms = room.resolve(), rooms.resolve()
    if checkout is None:
        return
    checkout = checkout.resolve()
    inside = room == checkout or checkout in room.parents
    if inside and rooms not in room.parents:
        raise RoomError(
            f"{room} is inside the checkout but not under {rooms}. A room "
            f"there is only clean while the session is started with "
            f"--restricted, and that is worth keeping in one place.")


def build(room: pathlib.Path, *, prompt: str, rules: str, bundle: pathlib.Path,
          skill_name: str, rooms: pathlib.Path,
          checkout: pathlib.Path | None = None) -> pathlib.Path:
    """Build a room and return its path.

    Args:
        room: Where to build it. Must not exist, or be empty.
        prompt: The task, exactly as the user would type it. Written into
            TASK.md as given - never a paraphrase, which is how an answer
            leaks into a room.
        rules: RULES.md's text: what the room may and may not read.
        bundle: The surface under test: a zip (as a user downloads it) or a
            directory. Unpacked under ``skills/<skill_name>``.
        skill_name: The skill's directory name inside the room.
        rooms: The directory rooms are built under.
        checkout: The product's repository, when the rooms are inside it.
    """
    room = pathlib.Path(room)
    check_location(room, rooms, checkout)
    if room.exists() and any(room.iterdir()):
        raise RoomError(f"{room} is not empty - a room starts with nothing in it")
    room.mkdir(parents=True, exist_ok=True)

    target = room / "skills" / skill_name
    bundle = pathlib.Path(bundle)
    if bundle.is_dir():
        shutil.copytree(bundle, target, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc"))
    else:
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(target)

    (room / "CLAUDE.md").write_text(CANARY, encoding="utf-8")
    (room / "RULES.md").write_text(rules, encoding="utf-8")
    (room / "TASK.md").write_text(f"# The task\n\n{prompt.strip()}\n", encoding="utf-8")
    (room / "QUESTIONS.md").write_text(QUESTIONS, encoding="utf-8")
    return room
