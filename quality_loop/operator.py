"""The operator agent: one session per room, in two phases.

Phase 1 puts the scenario's screen up; phase 2, after the room has finished
and the runner has collected and audited, reports the problems. The same
session is resumed for phase 2, so the agent that judges a run is the one
that set it up.

Between the two, a scenario with a **Live check** section gets one more turn
of the same session: with the room finished and what it made still installed,
the operator drives the real app through quality-loop's `app_*` tools, and
every step lands in the room's ``evidence/live/``. Evidence tools read the
run's record and never the live machine, which has been put back by phase 2;
so live driving cannot be an evidence tool, and is a phase of its own instead.

Known problems - ids earlier runs reported for this scenario - are handed to
phase 2 as neutral data: id and title, never a status. "It should be fixed
now" biases a judge toward "fixed"; an id and a title only spare it
re-deriving a name for something already named.

What the operator may do is a short list, and this module is where it is
enforced:

- `--restricted` with an explicit `--tools`: no settings file of the
  operator's applies, so their broad permissions cannot widen this one.
- **No shell.** Claude Code lets read-only commands through whatever the
  allow list says, and `cat` reads anywhere; the first real operator ran
  `cd; ls; cat ...` that way. Its only way to act is quality-loop's own MCP
  server (`quality_loop.mcp`): the declared screens, and the product's
  declared evidence commands run without a shell.
- No other MCP server, the product's least of all: the screen is checked
  with the OS's own window list, never through the product under test.
- Writes only into the operator's own directory and the room's REPORT.md.
- Phase 1 must not change the room. Every file in it is hashed before and
  after, and any difference cancels the room: TASK.md in particular has to
  reach the room exactly as the runner wrote it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import uuid

from quality_loop import processes
from quality_loop import session as sessions

INSTRUCTIONS = pathlib.Path(__file__).with_name("OPERATOR.md")


class OperatorError(Exception):
    """A phase that cannot be trusted, and the room it cancels."""


def absolute(path: pathlib.Path) -> str:
    """A path as a Claude Code permission rule spells an absolute one:
    ``//Users/me/x`` on macOS, ``//c/Users/me/x`` on Windows."""
    posix = pathlib.Path(path).resolve().as_posix()
    if len(posix) > 1 and posix[1] == ":":
        posix = "/" + posix[0].lower() + posix[2:]
    return "/" + posix


def fingerprint(room: pathlib.Path) -> dict[str, str]:
    """``{relative path: sha256}`` of every file in the room."""
    found = {}
    for path in sorted(pathlib.Path(room).rglob("*")):
        if path.is_file():
            found[path.relative_to(room).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return found


@dataclasses.dataclass
class Operator:
    """One room's operator.

    Attributes:
        room: The room directory.
        directory: The operator's own, beside the room and outside it.
        scenario: The scenario file.
        checkout: The product's repository, readable in both phases.
        evidence_help: One paragraph on what the evidence tools answer.
        manifest: The manifest the runner wrote: screens and evidence tools.
        python: The interpreter quality-loop's MCP server runs under.
    """
    room: pathlib.Path
    directory: pathlib.Path
    scenario: pathlib.Path
    checkout: pathlib.Path
    evidence_help: str
    manifest: pathlib.Path
    python: str = sys.executable
    max_turns: int = 60
    model: str | None = None
    claude: str | None = None
    session_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    known: list = dataclasses.field(default_factory=list)
    cost: float = 0.0

    def allow(self) -> list[str]:
        """The permission list: read, quality-loop's tools, two places to write.

        Writes are granted as Edit rules, which govern every built-in tool
        that changes a file, Write included. Their paths are absolute, which
        Claude Code spells with a leading ``//``. A single ``/`` is relative to
        the settings file, and the first real run was refused every write.
        """
        return ["Read", "Glob", "Grep", "mcp__quality-loop",
                f"Edit({absolute(self.directory)}/**)",
                f"Edit({absolute(self.room / 'REPORT.md')})"]

    def servers(self) -> dict:
        from quality_loop.screens import MANIFEST
        return {"quality-loop": {"command": self.python, "args": ["-m", "quality_loop.mcp"],
                                 "env": {MANIFEST: str(self.manifest)}}}

    def command(self, phase, message: str) -> list[str]:
        command = [self.claude or sessions.find_claude(), "--restricted",
                   "--tools", "Read,Glob,Grep,Write,Edit",
                   "--add-dir", str(self.room), "--add-dir", str(self.checkout),
                   "--add-dir", str(self.manifest.parent),
                   "--mcp-config", json.dumps({"mcpServers": self.servers()}),
                   "--strict-mcp-config",
                   "--settings", json.dumps({"permissions": {"allow": self.allow()}}),
                   "--permission-mode", "dontAsk",
                   "--max-turns", str(self.max_turns),
                   "--output-format", "stream-json", "--verbose"]
        command += (["--session-id", self.session_id] if phase == 1
                    else ["--resume", self.session_id])
        if self.model:
            command += ["--model", self.model]
        return command + ["-p", message]

    def environment(self) -> dict:
        return sessions.Session(allow=[]).environment(self.directory)

    @property
    def instructions(self) -> pathlib.Path:
        """OPERATOR.md, copied into the operator's own directory.

        The package's copy is wherever quality-loop is installed, which is
        outside everything the operator may read. A product's first real run
        had an operator that never saw its job description, and wrote a
        verdict.
        """
        return self.directory / "OPERATOR.md"

    def phase_one_message(self, platform: str) -> str:
        return (f"Phase 1. Read {self.instructions} first; it is your whole job description.\n\n"
                f"Scenario: {self.scenario}\nRoom: {self.room}\n"
                f"Your directory: {self.directory}\nThis OS: {platform}\n"
                f"Your tools: screen_list, screen_open, screen_close, evidence.\n")

    @property
    def known_file(self) -> pathlib.Path:
        """known.md in the operator's directory: ids earlier runs reported."""
        return self.directory / "known.md"

    def write_known(self) -> None:
        if not self.known:
            return
        lines = ["# Problems earlier runs reported for this scenario", "",
                 "Ids and titles only. Use the same id for the same problem.", ""]
        lines += [f"- `{k.get('id', '')}`: {k.get('title', '')}" for k in self.known]
        self.known_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def live_message(self) -> str:
        return (f"Live check. The room has finished; what it made is still in place. "
                f"Room: {self.room}\nDo the scenario's **Live check** section on the real "
                f"app, as {self.instructions} describes: app_list, app_start, app_keys "
                f"(with an intent for every step), app_screen, app_events, app_stop. "
                f"The steps are recorded in {self.room / 'evidence' / 'live'}. Stop every "
                f"app you started, then write live.md in your directory.\n")

    def phase_two_message(self) -> str:
        known = (f"Earlier runs named problems in this scenario; their ids are in "
                 f"{self.known_file}. Read it before you name a problem.\n"
                 if self.known else "")
        return (f"Phase 2. The room has finished. Room: {self.room}\n"
                f"Write {self.room / 'REPORT.md'} in the format {self.instructions} gives - "
                f"problems with severities, no verdict - then close the screens you opened.\n\n"
                f"{known}"
                f"The product's evidence tools are in the `evidence` tool - call each "
                f"with args [\"--help\"] first.\n{self.evidence_help}\n")

    def _run(self, phase, message: str, say) -> int:
        self.directory.mkdir(parents=True, exist_ok=True)
        log = self.directory / f"phase{phase}.jsonl"
        with log.open("w", encoding="utf-8") as out, \
                subprocess.Popen(self.command(phase, message), cwd=self.directory,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 bufsize=1, env=self.environment()) as agent, \
                processes.tracked(agent):
            for line in agent.stdout:
                out.write(line)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("type") == "result":
                    self.cost += float(event.get("total_cost_usd") or 0)
                if isinstance(event, dict) and (text := sessions.digest(
                        event, self.directory, f"operator {phase}")):
                    say(text)
            return agent.wait()

    def phase_one(self, platform: str, say=print) -> None:
        """Put the screen up. Raises when the room was touched."""
        self.directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(INSTRUCTIONS, self.instructions)
        self.write_known()
        before = fingerprint(self.room)
        self._run(1, self.phase_one_message(platform), say)
        after = fingerprint(self.room)
        if changed := sorted(set(before.items()) ^ set(after.items())):
            raise OperatorError(
                "phase 1 changed the room, so it is cancelled: "
                + ", ".join(sorted({path for path, _hash in changed})))

    def live_check(self, say=print) -> None:
        """Drive the real app for the scenario's Live check. The room must
        come out unchanged but for the record the app tools write."""
        before = {k: v for k, v in fingerprint(self.room).items()
                  if not k.startswith("evidence/live/")}
        self._run("live", self.live_message(), say)
        after = {k: v for k, v in fingerprint(self.room).items()
                 if not k.startswith("evidence/live/")}
        if changed := sorted(set(before.items()) ^ set(after.items())):
            raise OperatorError(
                "the live check changed the room: "
                + ", ".join(sorted({path for path, _hash in changed})))

    def phase_two(self, say=print) -> pathlib.Path:
        """Write the report. Returns REPORT.md's path, which may not exist if
        the operator wrote nothing - and that is itself reported."""
        self._run(2, self.phase_two_message(), say)
        return self.room / "REPORT.md"
