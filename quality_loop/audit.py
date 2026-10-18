"""Checking the transcript for the rules no flag can enforce.

RULES.md forbids the checkout, the installed package and other people's work,
and until there was a transcript the only evidence that a room obeyed was that
it said so. A rule you cannot check is a rule you are assuming.

What is scanned is where a tool was *pointed* - the path-bearing fields of its
input - not what it typed or what came back. A room that reads a path off the
screen and repeats it in its notes is doing its task, not reaching for the
checkout; and a window title is full of paths the room never asked for.

**A refusal is not a breach.** A call the confinement turned down read
nothing, so the measurement is intact. Refusals are reported - they are the
confinement working in public - and only a call that came back with something
disqualifies a run.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import re
from typing import Callable

from quality_loop import transcript as tr

#: Input fields that say where a tool was aimed.
AIMED_AT = ("file_path", "path", "notebook_path", "pattern", "command", "glob")

#: An absolute path in any spelling: /Users/..., C:\Users\... or C:/..., and
#: \Users\... - rooted on the current drive, which Windows accepts too.
ABSOLUTE = re.compile(r"(?:[A-Za-z]:[\\/]|[\\/])[^\s\"'`;|&)]+")

#: A shell command that runs git: at the start, or after a separator, by any
#: path, with or without ".exe".
RUNS_GIT = re.compile(r"(?:^|[;&|(`]|\$\()\s*(?:\S*/)?git(?:\.exe)?\b")

#: What git answers once GIT_CEILING_DIRECTORIES has stopped it at the room.
NOT_A_REPOSITORY = "not a git repository"

#: What room.CANARY asks a contaminated session to say.
CANARY_PHRASE = "without --restricted"


def norm(path: str) -> str:
    """A path in one spelling: forward slashes, and lowercase on Windows,
    where C:\\Users and c:/users are the same place."""
    path = path.replace("\\", "/")
    return path.lower() if os.name == "nt" else path


def paths_in(tool_input: dict) -> list[str]:
    """The absolute paths a tool call was pointed at."""
    aimed = []
    for key in AIMED_AT:
        value = tool_input.get(key)
        if isinstance(value, str):
            value = value.replace("~/", str(pathlib.Path.home()) + "/")
            aimed += ABSOLUTE.findall(value)
    return aimed


@dataclasses.dataclass
class Policy:
    """What a product's rooms must not reach, and what their sessions must have.

    Attributes:
        checkout: The product's repository. A path under it and outside the
            room is a breach - not a mention of it, which every honest read of
            the bundle inside the room also is.
        forbidden: ``{substring: what it is}`` for paths that are a breach
            anywhere: the installed package, the installed app, the operator's
            files set aside.
        foreign: Basenames of other authors' work in a directory the room may
            write to - read one, and the room has learned from somebody who
            had the repository.
        bash: Whether the session has Bash on purpose. When it does not, Bash
            in the init event means `--restricted` did not take effect.
        servers: MCP servers that must be connected; one that is not means
            the room reported on the outage, not the product.
        leaked_skill: Says whether a slash command in the init event is one of
            the checkout's own skills - the scoring key among them.
        run_directory: The run's own directory - run.log, status.json, the
            other rooms and their operators. The runner sets it. A path in it
            and outside the room is a breach: a room once read its own log to
            reconstruct its task, and a sibling's report is the answer key.
    """
    checkout: pathlib.Path
    forbidden: dict[str, str] = dataclasses.field(default_factory=dict)
    foreign: set[str] = dataclasses.field(default_factory=set)
    bash: bool = False
    servers: tuple[str, ...] = ()
    leaked_skill: Callable[[str], bool] | None = None
    run_directory: pathlib.Path | None = None


def under(path: str, root: str) -> bool:
    """Whether ``path`` is ``root`` or inside it - not merely spelled like it:
    a room ``11_f1`` is not inside ``11_f1.operator``."""
    root = root.rstrip("/")
    return path == root or path.startswith(root + "/")


def isolation_held(transcript: pathlib.Path, policy: Policy) -> list[str]:
    """What the session's init event says went wrong with the flags."""
    init = tr.init_event(transcript)
    if init is None:
        return ["the session produced no init event"]
    found = []
    if not policy.bash and "Bash" in init.get("tools", []):
        found.append("the session had Bash: it was not started with --restricted, "
                     "so the checkout's CLAUDE.md was in context from the first token")
    if policy.leaked_skill:
        if leaked := [c for c in init.get("slash_commands", [])
                      if policy.leaked_skill(str(c))]:
            found.append(f"the checkout's own skills were visible to the room: {leaked}")
    servers = {s.get("name"): s.get("status") for s in init.get("mcp_servers", [])
               if isinstance(s, dict)}
    for name in policy.servers:
        if servers.get(name) != "connected":
            found.append(f"MCP server {name} was {servers.get(name, 'absent')}, so what "
                         f"the room reported is about the server, not the product")
    if CANARY_PHRASE in tr.final_reply(transcript).replace("`", ""):
        found.append("the room read its CLAUDE.md canary unasked: the session was "
                     "started without --restricted")
    return found


def audit(room: pathlib.Path, policy: Policy) -> tuple[list[str], list[str]]:
    """``(breaches, refused)`` from the room's transcript."""
    room = pathlib.Path(room).resolve()
    transcript = room / "transcript.jsonl"
    if not transcript.exists():
        return ["no transcript - the room was never driven"], []
    breaches = isolation_held(transcript, policy)
    refused: list[str] = []
    checkout, inside = norm(str(policy.checkout.resolve())), norm(str(room))
    records = (norm(str(pathlib.Path(policy.run_directory).resolve()))
               if policy.run_directory else None)
    forbidden = {norm(path): what for path, what in policy.forbidden.items()}
    for call in tr.tool_calls(transcript):
        landed = refused if call.is_error else breaches
        command = call.input.get("command")
        if isinstance(command, str) and RUNS_GIT.search(command):
            # Refused when git found no repository - the ceiling held.
            (refused if call.is_error or NOT_A_REPOSITORY in call.result
             else breaches).append(f"{call.name} ran git: {command[:80]}")
        for aimed in paths_in(call.input):
            spelled = norm(aimed)
            for path, what in forbidden.items():
                if path in spelled:
                    landed.append(f"{call.name} reached into {what}: {aimed}")
            if under(spelled, checkout) and not under(spelled, inside):
                landed.append(f"{call.name} reached into the checkout: {aimed}")
            elif records and under(spelled, records) and not under(spelled, inside):
                landed.append(f"{call.name} reached into the run's own records: {aimed}")
            if pathlib.PurePath(aimed.replace("\\", "/")).name in policy.foreign:
                landed.append(f"{call.name} read another author's work: {aimed}")
    return sorted(set(breaches)), sorted(set(refused))
