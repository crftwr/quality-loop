"""Starting a room's session, and the flags that make it a clean one.

The room is driven non-interactively on purpose. "Answer nothing it asks" is a
discipline, and a discipline fails at the first plausible-sounding question; a
`-p` session has nobody to ask, so the only questions it can raise are the
ones it writes into QUESTIONS.md - which is what the exercise produces.

Every flag here was paid for by a run:

- `--restricted`: a session in a room inside the checkout, asked what project
  it is in and allowed to read nothing, names the product without it and
  answers UNKNOWN with it. It also hides the checkout's own skills, the
  scoring key among them, and ignores the settings files.
- `--strict-mcp-config` with exactly the servers given: whatever else the
  operator has connected is not part of the product's interface.
- `--settings` with the permission list, under `--permission-mode dontAsk`:
  a `-p` session with no grant is refused every tool call, and a first run
  reported, accurately and uselessly, that it could not write a file.
- `--no-session-persistence`: the transcript is kept in the room.
- `GIT_CEILING_DIRECTORIES` at the room's parent, so `git log` from the room
  answers "not a git repository" rather than reading the checkout's history,
  whose commit titles say what every change to the product was for.
- stdin closed: a `-p` session with an open one waits three seconds for
  piped input and writes a warning to the top of the transcript.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

#: The sentence a room is opened with, and the whole of what it is told.
PROMPT = "Read RULES.md, then do TASK.md."


def find_claude() -> str:
    """The `claude` binary, which is routinely not on PATH.

    It often lives inside the VS Code extension only, so a script that just
    calls "claude" fails at the last step of a run that has already built a
    room. ``CLAUDE_BIN`` overrides the search.
    """
    if override := os.environ.get("CLAUDE_BIN"):
        return override
    if found := shutil.which("claude"):
        return found
    binary = "claude.exe" if os.name == "nt" else "claude"
    candidates = list(pathlib.Path.home().glob(
        f".vscode/extensions/anthropic.claude-code-*/resources/native-binary/{binary}"))
    local = pathlib.Path.home() / ".claude" / "local" / binary
    if local.exists():
        candidates.append(local)
    if not candidates:
        raise FileNotFoundError(
            "no `claude` binary - put it on PATH or set CLAUDE_BIN=/path/to/claude")
    # Newest install wins; version strings sort wrong (2.1.99 > 2.1.251).
    return str(max(candidates, key=lambda p: p.stat().st_mtime))


@dataclasses.dataclass
class Session:
    """How a product's rooms are started.

    Attributes:
        allow: The permission list - the room's job description. What is
            listed runs; everything else is refused.
        tools: The built-in tools the session has at all (``--tools``), or
            None for `--restricted`'s default, which has no Bash. A product
            whose surface is a CLI grants a narrowed Bash here and in
            ``allow``.
        add_dirs: Directories outside the room the file tools may reach.
        mcp_servers: ``{name: server config}`` - exactly these, nothing else.
        env: Extra environment for the session (a PATH shim, a shell).
        max_turns: Turn limit for a non-interactive run.
        model: Model override, or None for the default.
    """
    allow: list[str]
    tools: list[str] | None = None
    add_dirs: list[pathlib.Path] = dataclasses.field(default_factory=list)
    mcp_servers: dict = dataclasses.field(default_factory=dict)
    env: dict = dataclasses.field(default_factory=dict)
    max_turns: int = 150
    model: str | None = None
    claude: str | None = None

    def command(self, interactive: bool = False) -> list[str]:
        """The command line, without ``-p`` when a person will drive it."""
        command = [self.claude or find_claude(), "--restricted"]
        if self.tools is not None:
            command += ["--tools", ",".join(self.tools)]
        for directory in self.add_dirs:
            command += ["--add-dir", str(directory)]
        command += [
            "--mcp-config", json.dumps({"mcpServers": self.mcp_servers}),
            "--strict-mcp-config",
            # --restricted ignores the settings files, so the permissions have
            # to be handed over directly.
            "--settings", json.dumps({"permissions": {"allow": self.allow}}),
            "--permission-mode", "dontAsk",
        ]
        if interactive:
            return command
        command += ["-p", PROMPT, "--no-session-persistence",
                    "--max-turns", str(self.max_turns),
                    "--output-format", "stream-json", "--verbose"]
        if self.model:
            command += ["--model", self.model]
        return command

    def environment(self, room: pathlib.Path) -> dict:
        """The operator's environment, with git stopped at the room."""
        return dict(os.environ, **self.env,
                    GIT_CEILING_DIRECTORIES=str(pathlib.Path(room).resolve().parent))

    def printable(self, room: pathlib.Path, shell: str | None = None) -> str:
        """The same session, for a person to paste - flags and all.

        A bare `cd <room> && claude` is how a room in the checkout gets opened
        without `--restricted`, which is the failure the whole arrangement
        trades on not happening. ``shell`` is "posix" or "powershell"; the
        default is this OS's.
        """
        shell = shell or ("powershell" if os.name == "nt" else "posix")
        variables = {**self.env,
                     "GIT_CEILING_DIRECTORIES": str(pathlib.Path(room).parent)}
        command = self.command(interactive=True)
        if shell == "powershell":
            quote = _powershell_quote
            lines = [f"Set-Location {quote(str(room))}"]
            lines += [f"$env:{name} = {quote(str(value))}"
                      for name, value in variables.items()]
            lines.append("& " + " `\n    ".join(_paired(command, quote)))
            return "\n".join(lines)
        quote = shlex.quote
        assignments = [f"{name}={quote(str(value))}" for name, value in variables.items()]
        return (f"cd {quote(str(room))} && \\\n    "
                + " \\\n    ".join(assignments + _paired(command, quote)))

    def run(self, room: pathlib.Path, on_event: Callable[[dict], None] | None = None,
            alive: Callable[[], bool] | None = None, heartbeat: float = 20.0,
            say: Callable[[str], None] = print) -> "Run":
        """Drive the room to completion, keeping the transcript in it.

        The transcript is written outside the room and moved in at the end:
        left in the room it is a file the room can read, and one room did -
        grepping its own log to reconstruct the task its prompt referred to.

        ``alive`` is asked on the heartbeat whether the product is still
        answering. Two misses in a row end the run: a room that cannot reach
        the product measures the outage, and one went on for twenty-three
        minutes after its product had died.
        """
        room = pathlib.Path(room)
        transcript = (pathlib.Path(tempfile.gettempdir())
                      / f"quality-loop-{room.parent.name}-{room.name}.jsonl")
        result = Run(room / "transcript.jsonl")
        clock = _Clock()
        try:
            with subprocess.Popen(self.command(), cwd=room, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", bufsize=1,
                                  env=self.environment(room)) as session, \
                    transcript.open("w", encoding="utf-8") as log:
                beat = threading.Thread(target=_heartbeat, daemon=True,
                                        args=(session, clock, alive, heartbeat, say, result))
                beat.start()
                try:
                    for line in session.stdout:
                        log.write(line)
                        clock.touch()
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(event, dict):
                            if on_event:
                                on_event(event)
                            if text := digest(event, room, clock):
                                say(text)
                except BaseException:
                    # Ctrl-C or SIGTERM: the session goes with the run, so
                    # nothing is still writing into what is being collected.
                    session.terminate()
                    raise
                result.exit_code = session.wait()
        finally:
            if transcript.exists():
                shutil.move(transcript, result.transcript)
        return result


@dataclasses.dataclass
class Run:
    """What driving a room came to."""
    transcript: pathlib.Path
    exit_code: int | None = None
    product_lost: bool = False


def _paired(command: list[str], quote) -> list[str]:
    """Each flag on one line with its value."""
    parts = [quote(part) for part in command]
    lines, index = [], 0
    while index < len(parts):
        flag, value = command[index], parts[index + 1:index + 2]
        if flag.startswith("--") and value and not command[index + 1].startswith("--"):
            lines.append(f"{parts[index]} {value[0]}")
            index += 2
        else:
            lines.append(parts[index])
            index += 1
    return lines


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class _Clock:
    def __init__(self):
        self.started = self.last = time.monotonic()

    def touch(self):
        self.last = time.monotonic()

    def __str__(self):
        seconds = int(time.monotonic() - self.started)
        return f"{seconds // 60:>2}:{seconds % 60:02d}"


def _heartbeat(session, clock, alive, every, say, result) -> None:
    """Say the run is alive while it thinks, and end it when the product is not.

    A model between tool calls writes nothing, so a long turn and a hung
    process look identical; a line every quiet ``every`` seconds tells them
    apart.
    """
    missed = 0
    while session.poll() is None:
        time.sleep(every / 4)
        quiet = time.monotonic() - clock.last
        if quiet < every:
            continue
        say(f"  [{clock}] … thinking ({int(quiet)}s since the last step)")
        clock.touch()
        if alive is None:
            continue
        missed = 0 if alive() else missed + 1
        if missed >= 2:
            say(f"  [{clock}] !! the product stopped answering - ending the run")
            result.product_lost = True
            session.terminate()
            return


def _hint(given: dict, room: pathlib.Path) -> str:
    """The part of a tool call worth one line: a path's tail, or a pattern."""
    for key in ("file_path", "path", "notebook_path"):
        if value := given.get(key):
            shown = str(value)
            return shown[len(str(room)) + 1:] if shown.startswith(str(room)) else shown
    for key in ("pattern", "command", "app", "action", "title", "role", "text", "name"):
        if value := given.get(key):
            return str(value)[:70]
    return ""


def digest(event: dict, room: pathlib.Path, clock="") -> str | None:
    """One line per thing the room did, so a long run is watchable."""
    from quality_loop.transcript import parts

    lines = []
    kind = event.get("type")
    if kind == "assistant":
        for part in parts(event):
            if part.get("type") == "tool_use":
                given = part.get("input") if isinstance(part.get("input"), dict) else {}
                lines.append(f"  [{clock}] · {part.get('name')} {_hint(given, room)}".rstrip())
            elif part.get("type") == "text" and str(part.get("text", "")).strip():
                lines.append(f"  [{clock}]   {str(part['text']).strip().splitlines()[0][:110]}")
    elif kind == "user":
        # A refusal is the one result worth a line: it is what a wrong
        # permission list or a reach outside the room looks like from here.
        for part in parts(event):
            if part.get("type") == "tool_result" and part.get("is_error"):
                said = str(part.get("content", "")).replace("\n", " ")
                lines.append(f"  [{clock}] ! refused - {said[:120]}")
    elif kind == "result":
        lines.append(f"\n  turns:   {event.get('num_turns', '?')}, "
                     f"{(event.get('duration_ms') or 0) / 1000:.0f}s, "
                     f"${event.get('total_cost_usd') or 0:.2f}")
    return "\n".join(lines) or None
