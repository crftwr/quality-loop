"""The operator agent: one session per room, in two phases.

Phase 1 puts the scenario's screen up; phase 2, after the room has finished
and the runner has collected and audited, reports the problems. The same
session is resumed for phase 2, so the agent that judges a run is the one
that set it up.

What the operator may do is a short list, and this module is where it is
enforced:

- `--restricted` with an explicit `--tools`: no settings file of the
  operator's applies, so their broad permissions cannot widen this one.
- No MCP servers at all. The screen is checked by the screen CLI with the
  OS's own window list, never through the product under test.
- Bash only for the screen CLI and the product's evidence tools, each as a
  fixed command prefix.
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
import subprocess
import sys
import uuid

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
        evidence_tools: Command prefixes of the product's evidence CLI, as
            the operator must type them (``["/venv/bin/python -m product.evidence"]``).
        evidence_help: One paragraph on what those tools answer.
        manifest: The screen manifest the runner wrote.
        python: The interpreter the screen CLI runs under.
    """
    room: pathlib.Path
    directory: pathlib.Path
    scenario: pathlib.Path
    checkout: pathlib.Path
    evidence_tools: list[str]
    evidence_help: str
    manifest: pathlib.Path
    python: str = sys.executable
    max_turns: int = 60
    model: str | None = None
    claude: str | None = None
    session_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def screen(self) -> str:
        return f"{self.python} -m quality_loop screen"

    def allow(self) -> list[str]:
        """The permission list: read, the two CLIs, and two places to write.

        Writes are granted as Edit rules, which govern every built-in tool
        that changes a file, Write included. Their paths are absolute, which
        Claude Code spells with a leading ``//``. A single ``/`` is relative to
        the settings file, and the first real run was refused every write.
        """
        rules = ["Read", "Glob", "Grep", f"Bash({self.screen}:*)"]
        rules += [f"Bash({tool}:*)" for tool in self.evidence_tools]
        rules += [f"Edit({absolute(self.directory)}/**)",
                  f"Edit({absolute(self.room / 'REPORT.md')})"]
        return rules

    def command(self, phase: int, message: str) -> list[str]:
        command = [self.claude or sessions.find_claude(), "--restricted",
                   "--tools", "Read,Glob,Grep,Bash,Write,Edit",
                   "--add-dir", str(self.room), "--add-dir", str(self.checkout),
                   "--add-dir", str(self.manifest.parent),
                   "--mcp-config", json.dumps({"mcpServers": {}}), "--strict-mcp-config",
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
        from quality_loop.screens import MANIFEST
        env = sessions.Session(allow=[]).environment(self.directory)
        env[MANIFEST] = str(self.manifest)
        return env

    def phase_one_message(self, platform: str) -> str:
        return (f"Phase 1. Read {INSTRUCTIONS} first; it is your whole job description.\n\n"
                f"Scenario: {self.scenario}\nRoom: {self.room}\n"
                f"Your directory: {self.directory}\nThis OS: {platform}\n"
                f"Screen CLI: {self.screen} list | open <name> | close <id>\n")

    def phase_two_message(self) -> str:
        tools = "\n".join(f"  {tool} --help" for tool in self.evidence_tools) or "  (none)"
        return (f"Phase 2. The room has finished. Room: {self.room}\n"
                f"Write {self.room / 'REPORT.md'}, then close the screens you opened.\n\n"
                f"The product's evidence tools - run each with --help first:\n{tools}\n"
                f"{self.evidence_help}\n")

    def _run(self, phase: int, message: str, say) -> int:
        self.directory.mkdir(parents=True, exist_ok=True)
        log = self.directory / f"phase{phase}.jsonl"
        with log.open("w", encoding="utf-8") as out, \
                subprocess.Popen(self.command(phase, message), cwd=self.directory,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 bufsize=1, env=self.environment()) as agent:
            for line in agent.stdout:
                out.write(line)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and (text := sessions.digest(
                        event, self.directory, f"operator {phase}")):
                    say(text)
            return agent.wait()

    def phase_one(self, platform: str, say=print) -> None:
        """Put the screen up. Raises when the room was touched."""
        before = fingerprint(self.room)
        self._run(1, self.phase_one_message(platform), say)
        after = fingerprint(self.room)
        if changed := sorted(set(before.items()) ^ set(after.items())):
            raise OperatorError(
                "phase 1 changed the room, so it is cancelled: "
                + ", ".join(sorted({path for path, _hash in changed})))

    def phase_two(self, say=print) -> pathlib.Path:
        """Write the report. Returns REPORT.md's path, which may not exist if
        the operator wrote nothing - and that is itself reported."""
        self._run(2, self.phase_two_message(), say)
        return self.room / "REPORT.md"
