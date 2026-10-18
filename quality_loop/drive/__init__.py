"""Driving the product's app, and recording every step of it.

A product that has no MCP endpoint and no evidence tools of its own can still
be checked, if the framework operates the app: a terminal app in a pty, read
as text; a desktop app with synthetic keys and screenshots. The product is
asked for very little:

- **practically required:** a command that launches it, a way to redirect its
  config and data (so the user's own are never touched), and for a desktop
  app a window title to recognise;
- **optional, level 1:** an event log. Every app is started with
  ``QUALITY_LOOP_EVENTS=<path>``; a product that writes JSON lines there (a
  prompt shown, a message, an exception, a program launched) turns "what the
  screenshot seems to show" into facts;
- **optional, level 2:** evidence tools of its own, as Keyhac has.

An adapter declares its apps by name, as it declares screens:

```python
apps = {
    "xefm": drive.TerminalApp(["xefm", "--home", HOME], rows=40, cols=120),
    "notes": drive.DesktopApp(["open", "-n", "-a", "Notes"], title="Notes"),
}
```

and an agent - the operator in its live check, or the room itself when the
product is human-facing - drives them through quality-loop's MCP server, by
name only. Every key sent, with the agent's stated intent, the wait, the
screen afterwards and the event-log lines since the last step, is written to
the record (``steps.jsonl`` and the screens beside it). That record is what a
report cites, and what a later agent follows to reproduce a finding.

Synthetic keys go only to the app's own window: before every key the
frontmost window is checked, and a send is refused when it is not the app's,
so input never lands in another application because the person at the
machine clicked somewhere.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import time

from quality_loop.drive import keys as keynames

#: The environment variable a product's event log is named by.
EVENTS = "QUALITY_LOOP_EVENTS"

#: Key remappers, by process name: they rewrite synthetic keys too, so what
#: was sent is not what the app received. Keyhac is one - for Keyhac's own QA
#: it is the product, and the warning says what to expect.
REMAPPERS = ("keyhac", "karabiner_grabber", "karabiner-elements", "autohotkey",
             "bettertouchtool", "powertoys.keyboardmanagerengine", "keyd", "kmonad",
             "xkeysnail", "hammerspoon")


class DriveError(Exception):
    """A step that was not taken, and why."""


@dataclasses.dataclass(frozen=True)
class TerminalApp:
    """A terminal app, driven in a pseudo-terminal and read as text.

    Attributes:
        argv: How it is launched. Point its config and data somewhere the
            run owns (an argument, an environment variable, HOME).
        rows, cols: The terminal's size.
        env: Extra environment.
        cwd: Its working directory.
    """
    argv: list
    rows: int = 40
    cols: int = 120
    env: dict = dataclasses.field(default_factory=dict)
    cwd: str | None = None
    kind: str = "tui"


@dataclasses.dataclass(frozen=True)
class DesktopApp:
    """A desktop app, driven with synthetic keys and read by screenshot.

    Attributes:
        argv: How it is launched.
        title: Part of its window's title: how the window is recognised, and
            what must be frontmost before a key is sent.
        env: Extra environment.
        cwd: Its working directory.
        patience: How long its window may take to appear.
        quit: Keys that quit it, sent at the end; otherwise the process is
            terminated.
    """
    argv: list
    title: str
    env: dict = dataclasses.field(default_factory=dict)
    cwd: str | None = None
    patience: float = 20.0
    quit: list | None = None
    kind: str = "gui"


def manifest_entries(apps: dict) -> dict:
    """``{name: entry}`` as the MCP server reads them."""
    return {name: dataclasses.asdict(app) for name, app in apps.items()}


def backend():
    if sys.platform == "darwin":
        from quality_loop.drive import _mac as module
    elif os.name == "nt":
        from quality_loop.drive import _windows as module
    else:
        raise DriveError(f"no desktop backend for {sys.platform}")
    return module


def remappers(listing: list[str] | None = None) -> list[str]:
    """Key remappers running now."""
    if listing is None:
        try:
            listing = backend().processes()
        except DriveError:
            return []
    found = set()
    for name in listing:
        lowered = name.lower().removesuffix(".exe")
        found.update(r for r in REMAPPERS if r in lowered)
    return sorted(found)


def preflight(apps: dict) -> dict:
    """What would stop a desktop app being driven, said before the first key."""
    if not any(entry.get("kind") == "gui" for entry in apps.values()):
        return {"warnings": []}
    module = backend()
    granted = module.permissions()
    warnings = [f"{what.replace('_', ' ')} is not granted to the application this run "
                f"was started from" for what, ok in granted.items() if not ok]
    if running := remappers():
        warnings.append(f"key remappers are running ({', '.join(running)}): synthetic "
                        f"keys pass through them, so an app may receive something other "
                        f"than what was sent")
    return {"permissions": granted, "warnings": warnings}


class _Desktop:
    """A desktop app, running."""

    def __init__(self, entry: dict, events: pathlib.Path):
        self.entry, self.title = entry, entry["title"]
        self.os = backend()
        self.process = subprocess.Popen(
            entry["argv"], cwd=entry.get("cwd"), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, **entry.get("env", {}), **{EVENTS: str(events)}))
        deadline = time.monotonic() + entry.get("patience", 20.0)
        self.owner = None
        while time.monotonic() < deadline:
            self.owner = self.os.find(self.title)
            if self.owner is not None:
                break
            time.sleep(0.5)
        if self.owner is None:
            self.stop()
            raise DriveError(f"no window titled {self.title!r} appeared")
        self.os.raise_window(*self._ref())
        time.sleep(0.5)

    def _ref(self) -> tuple:
        return (self.owner, self.title) if sys.platform == "darwin" else (self.owner,)

    def focused(self) -> tuple[bool, str]:
        owner, title = self.os.frontmost()
        if sys.platform == "darwin":
            return owner == self.owner and self.title in title, f"{owner}: {title}"
        return owner == self.owner, title

    def send(self, items: list) -> None:
        for item in items:
            if not isinstance(item, keynames.Pause):
                ok, front = self.focused()
                if not ok:
                    raise DriveError(f"the frontmost window is {front!r}, not "
                                     f"{self.title!r} - nothing more was sent, so no key "
                                     f"lands in another application")
            self.os.send([item])

    def shot(self, path: pathlib.Path) -> pathlib.Path:
        return self.os.screenshot(*self._ref(), path)

    def wait_quiet(self, scratch: pathlib.Path, quiet: float = 0.4,
                   patience: float = 8.0) -> bool:
        """Until two screenshots ``quiet`` apart are the same."""
        deadline = time.monotonic() + patience
        previous = None
        while time.monotonic() < deadline:
            time.sleep(quiet)
            try:
                current = self.shot(scratch).read_bytes()
            except Exception:  # noqa: BLE001 - a missed frame is retried
                current = None
            if current is not None and current == previous:
                return True
            previous = current
        return False

    def stop(self) -> int | None:
        if self.entry.get("quit") and self.owner is not None:
            try:
                self.send(keynames.sequence(self.entry["quit"]))
                self.process.wait(5)
            except (DriveError, subprocess.TimeoutExpired, Exception):  # noqa: BLE001
                pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        return self.process.returncode


class Driver:
    """The apps one agent session may drive, and the record of what it did.

    Attributes:
        apps: ``{name: entry}`` from the manifest.
        record: The directory the steps and screens are written to.
    """

    def __init__(self, apps: dict, record: pathlib.Path):
        self.apps = apps
        self.record = pathlib.Path(record)
        self.record.mkdir(parents=True, exist_ok=True)
        self.running: dict[str, dict] = {}
        self.step = self._last_step()
        self._warned = False

    def _last_step(self) -> int:
        steps = self.record / "steps.jsonl"
        if not steps.exists():
            return 0
        return sum(1 for line in steps.read_text(encoding="utf-8").splitlines() if line)

    def _log(self, entry: dict) -> None:
        with (self.record / "steps.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _app(self, ident: str) -> dict:
        if ident not in self.running:
            raise DriveError(f"no running app {ident!r}; running: "
                             + (", ".join(self.running) or "none"))
        return self.running[ident]

    def _events_since(self, app: dict) -> list:
        path: pathlib.Path = app["events"]
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        new, app["events_seen"] = lines[app["events_seen"]:], len(lines)
        found = []
        for line in new[-50:]:
            try:
                found.append(json.loads(line))
            except ValueError:
                found.append({"unparsed": line[:500]})
        return found

    def _look(self, app: dict, step: int) -> dict:
        """The screen now, saved under the step's number."""
        stem = f"{step:03d}-{app['id']}"
        if app["kind"] == "tui":
            text = app["runner"].text()
            path = app["runner"].save(self.record / f"{stem}.txt")
            return {"screen": text, "screen_file": path.name,
                    "cursor": list(app["runner"].cursor())}
        path = app["runner"].shot(self.record / f"{stem}.png")
        return {"image": str(path), "screen_file": path.name}

    def list(self) -> dict:
        return {name: {"kind": e["kind"], **({"title": e["title"]} if "title" in e else {}),
                       **({"size": f"{e['rows']}x{e['cols']}"} if e["kind"] == "tui" else {})}
                for name, e in self.apps.items()}

    def start(self, name: str, intent: str = "") -> dict:
        if name not in self.apps:
            raise DriveError(f"no app {name!r}; declared: " + ", ".join(sorted(self.apps)))
        entry = self.apps[name]
        ident = f"{name}-{sum(1 for a in self.running.values() if a['name'] == name) + 1}"
        while ident in self.running:
            ident += "x"
        events = self.record / f"{ident}.events.jsonl"
        warnings = []
        if not self._warned:
            warnings = preflight(self.apps).get("warnings", [])
            self._warned = True
        if entry["kind"] == "tui":
            from quality_loop.drive import terminal
            try:
                runner = terminal.PtyApp(entry["argv"], rows=entry["rows"], cols=entry["cols"],
                                         env={**entry.get("env", {}), EVENTS: str(events)},
                                         cwd=entry.get("cwd"))
            except (terminal.TerminalError, OSError) as error:
                raise DriveError(str(error)) from None
            runner.wait_quiet(patience=15.0)
        elif entry["kind"] == "gui":
            runner = _Desktop(entry, events)
            runner.wait_quiet(self.record / ".scratch.png")
        else:
            raise DriveError(f"{name}: unknown kind {entry['kind']!r}")
        app = {"id": ident, "name": name, "kind": entry["kind"], "runner": runner,
               "events": events, "events_seen": 0}
        self.running[ident] = app
        self.step += 1
        seen = self._look(app, self.step)
        record = {"step": self.step, "at": time.time(), "action": "start", "app": ident,
                  "intent": intent, "argv": entry["argv"],
                  "size": ([entry["rows"], entry["cols"]] if entry["kind"] == "tui" else None),
                  "screen_file": seen["screen_file"], "events": self._events_since(app)}
        self._log(record)
        return {"id": ident, "step": self.step, "warnings": warnings, **seen,
                "events": record["events"]}

    def keys(self, ident: str, keys, intent: str) -> dict:
        if not str(intent).strip():
            raise DriveError("say why: intent is what you expect this step to do, and "
                             "the record keeps it for whoever reproduces the step")
        app = self._app(ident)
        try:
            items = keynames.sequence(keys)
        except keynames.KeysError as error:
            raise DriveError(str(error)) from None
        self.step += 1
        record = {"step": self.step, "at": time.time(), "action": "keys", "app": ident,
                  "keys": keynames.describe(items), "intent": intent}
        try:
            app["runner"].send(items)
        except Exception as error:  # noqa: BLE001 - recorded, then answered
            record["refused"] = str(error)
            self._log(record)
            raise DriveError(str(error)) from None
        started = time.monotonic()
        if app["kind"] == "tui":
            settled = app["runner"].wait_quiet()
        else:
            settled = app["runner"].wait_quiet(self.record / ".scratch.png")
        record["waited"] = round(time.monotonic() - started, 2)
        record["settled"] = settled
        seen = self._look(app, self.step)
        record["screen_file"] = seen["screen_file"]
        record["events"] = self._events_since(app)
        if app["kind"] == "tui" and app["runner"].process.poll() is not None:
            record["exited"] = app["runner"].process.returncode
        self._log(record)
        return {"step": self.step, "settled": settled, **seen, "events": record["events"],
                **({"exited": record["exited"]} if "exited" in record else {})}

    def screen(self, ident: str) -> dict:
        app = self._app(ident)
        self.step += 1
        seen = self._look(app, self.step)
        self._log({"step": self.step, "at": time.time(), "action": "look", "app": ident,
                   "screen_file": seen["screen_file"], "events": self._events_since(app)})
        return {"step": self.step, **seen}

    def events(self, ident: str) -> list:
        app = self._app(ident)
        path: pathlib.Path = app["events"]
        if not path.exists():
            return []
        return [json.loads(line) if line.startswith("{") else {"unparsed": line}
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.strip()][-200:]

    def stop(self, ident: str) -> dict:
        app = self._app(ident)
        code = app["runner"].stop()
        del self.running[ident]
        self.step += 1
        self._log({"step": self.step, "at": time.time(), "action": "stop", "app": ident,
                   "exit_code": code})
        return {"id": ident, "exit_code": code}

    def stop_all(self) -> None:
        for ident in list(self.running):
            try:
                self.stop(ident)
            except Exception:  # noqa: BLE001 - everything is stopped that can be
                pass
