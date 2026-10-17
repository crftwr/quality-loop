"""Putting a scenario's screen up, by name, on either OS.

The operator agent reads a scenario's Screen section and decides what has to be
in front. It can only ask for a screen **by name**, from the list the
product's adapter declares, and it never passes a path, a URL or a script. An
agent that can write files and also run a script it names can run anything,
so the mechanics belong in code:

```python
SCREENS = {
    "approval-queue": Page("dialog.html", title="Approval queue"),
    "deploy":         Terminal("deploy.py", title="deploy - acme"),
}
```

The runner writes a manifest of those declarations, with every path made
absolute, into a directory the operator cannot write to, and points
``QUALITY_LOOP_MANIFEST`` at it. ``quality-loop screen open <name>`` opens
one, waits until its window is up, and records it. ``close`` closes only what
``open`` recorded. Both OSes are implemented here, one module each. The
window's title is the contract between the declaration and the check that
the screen is up.

The screen is checked with the OS's own window list, never with the product
under test: a broken product would otherwise hide a failed setup and take
the blame for it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

MANIFEST = "QUALITY_LOOP_MANIFEST"


class ScreenError(Exception):
    """A screen that could not be put up or taken down."""


@dataclasses.dataclass(frozen=True)
class Page:
    """An HTML page from the product's fixtures, served by the runner.

    Attributes:
        file: Its path under the served fixture directory.
        title: Its ``<title>``, which is how its window is recognised.
    """
    file: str
    title: str
    kind: str = "page"


@dataclasses.dataclass(frozen=True)
class Terminal:
    """A Python script run in a terminal window of its own.

    Python so that one script serves both OSes; run with the product's
    interpreter, from a copy outside the checkout, because a terminal shows
    its command line and a path under the repository tells the room where the
    source it may not read is.

    Attributes:
        script: Its path, relative to the adapter's fixture directory.
        title: The window's title, set by the backend rather than the script.
    """
    script: str
    title: str
    kind: str = "terminal"


def write_manifest(path: pathlib.Path, screens: dict, *, fixtures: pathlib.Path,
                   origin: str, python: str, state: pathlib.Path,
                   evidence: dict | None = None) -> pathlib.Path:
    """The declarations, made absolute, for the operator's tools to read.

    ``evidence`` is ``{name: {"argv": [...], "help": "..."}}``: the product's
    evidence commands, run by the operator's MCP server and nothing else.
    """
    entries = {}
    for name, screen in screens.items():
        entry = dataclasses.asdict(screen)
        if isinstance(screen, Page):
            entry["url"] = f"{origin}/{screen.file}"
        else:
            entry["script"] = str((pathlib.Path(fixtures) / screen.script).resolve())
        entries[name] = entry
    path.write_text(json.dumps({"screens": entries, "python": python,
                                "state": str(state), "evidence": evidence or {}},
                               indent=2), encoding="utf-8")
    return path


def _manifest() -> dict:
    where = os.environ.get(MANIFEST)
    if not where:
        raise ScreenError(f"{MANIFEST} is not set - the runner sets it for the operator")
    return json.loads(pathlib.Path(where).read_text(encoding="utf-8"))


def _state_file(manifest: dict) -> pathlib.Path:
    return pathlib.Path(manifest["state"]) / "screens.json"


def _opened(manifest: dict) -> list[dict]:
    path = _state_file(manifest)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _record(manifest: dict, opened: list[dict]) -> None:
    path = _state_file(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(opened, indent=2), encoding="utf-8")


def backend():
    """This OS's implementation."""
    if sys.platform == "darwin":
        from quality_loop.screens import _mac as module
    elif os.name == "nt":
        from quality_loop.screens import _windows as module
    else:
        raise ScreenError(f"no screen backend for {sys.platform}")
    return module


def names() -> dict:
    """``{name: entry}`` - what may be opened."""
    return _manifest()["screens"]


def open_screen(name: str, patience: float = 15.0, os_backend=None) -> dict:
    """Open the screen ``name`` and wait until its window is up."""
    manifest = _manifest()
    screens = manifest["screens"]
    if name not in screens:
        raise ScreenError(f"no screen {name!r}; the adapter declares: "
                          + ", ".join(sorted(screens)))
    entry = screens[name]
    os_backend = os_backend or backend()
    if entry["kind"] == "page":
        handle = os_backend.open_page(entry["url"], entry["title"], patience)
    elif entry["kind"] == "terminal":
        copy = pathlib.Path(tempfile.mkdtemp(prefix="quality-loop-screen-"))
        script = copy / pathlib.Path(entry["script"]).name
        shutil.copy2(entry["script"], script)
        handle = os_backend.open_terminal([manifest["python"], str(script)],
                                          entry["title"], patience)
    else:
        raise ScreenError(f"{name}: unknown kind {entry['kind']!r}")
    opened = _opened(manifest)
    record = {"id": f"{name}-{len(opened) + 1}", "name": name, "kind": entry["kind"],
              "title": entry["title"], "handle": handle, "at": time.time()}
    _record(manifest, opened + [record])
    return record


def close_screen(screen_id: str, os_backend=None) -> dict:
    """Close one screen ``open_screen`` recorded, and nothing else."""
    manifest = _manifest()
    opened = _opened(manifest)
    record = next((r for r in opened if r["id"] == screen_id), None)
    if record is None:
        raise ScreenError(f"{screen_id!r} was not opened here; opened: "
                          + (", ".join(r["id"] for r in opened) or "nothing"))
    (os_backend or backend()).close(record["kind"], record["handle"])
    _record(manifest, [r for r in opened if r["id"] != screen_id])
    return record


def close_all(state: pathlib.Path, os_backend=None) -> list[str]:
    """Close everything still recorded in ``state`` - the runner's own sweep,
    after the operator has had its turn, so a screen it forgot to close does
    not become the next room's second window."""
    path = pathlib.Path(state) / "screens.json"
    if not path.exists():
        return []
    closed = []
    for record in json.loads(path.read_text(encoding="utf-8")):
        try:
            (os_backend or backend()).close(record["kind"], record["handle"])
            closed.append(record["id"])
        except ScreenError:
            pass
    path.unlink()
    return closed
