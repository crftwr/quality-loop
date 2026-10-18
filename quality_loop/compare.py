"""Comparing runs' findings by room and id: new, still there, gone, back.

A problem's id names the problem, not the run, so the same problem reported
by a later run has the same id in the same room. Runs are not deterministic,
so this says what the record shows, nothing more: an id that is **gone** did
not appear this time, which is not yet proof it was fixed.

- **new**: in this run, in no earlier run of that room.
- **still there**: in this run and in the run compared with.
- **gone**: in the run compared with, not in this one, for a room this run
  ran. A room this run did not run says nothing about its problems.
- **back**: in this run, not in the run compared with, but in an earlier one.
"""

from __future__ import annotations

import json
import pathlib

from quality_loop import progress


def stamp(run: pathlib.Path) -> str:
    """``<version>-YYYYMMDD-HHMMSS`` sorts by its last two parts."""
    parts = pathlib.Path(run).name.rsplit("-", 2)
    return "-".join(parts[-2:]) if len(parts) >= 3 else pathlib.Path(run).name


def runs(rooms: pathlib.Path) -> list[pathlib.Path]:
    """Every run directory under ``rooms``, oldest first."""
    rooms = pathlib.Path(rooms)
    if not rooms.is_dir():
        return []
    found = [d for d in rooms.iterdir() if d.is_dir()
             and ((d / "status.json").exists() or (d / "findings.json").exists())]
    return sorted(found, key=stamp)


def latest(rooms: pathlib.Path) -> pathlib.Path | None:
    found = runs(rooms)
    return found[-1] if found else None


def findings(run: pathlib.Path) -> list[dict]:
    try:
        return json.loads((pathlib.Path(run) / "findings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def rooms_run(run: pathlib.Path) -> set[str]:
    """The rooms a run ran - including those that reported nothing, which
    findings.json alone cannot say."""
    status = progress.read(run)
    if status and status.get("rooms"):
        return {label for label, entry in status["rooms"].items()
                if entry.get("phase") == "done"}
    return {d.name for d in pathlib.Path(run).iterdir()
            if d.is_dir() and (d / "TASK.md").exists() and (d / "REPORT.md").exists()}


def _keys(entries: list[dict]) -> dict[tuple[str, str], dict]:
    return {(e.get("room", ""), e.get("id", "")): e for e in entries if e.get("id")}


def compare(run: pathlib.Path, since: pathlib.Path | None,
            earlier: list[pathlib.Path] = ()) -> dict:
    """``{"new", "still", "gone", "back"}``, each a list of findings."""
    now = _keys(findings(run))
    before = _keys(findings(since)) if since else {}
    history: set[tuple[str, str]] = set()
    for old in earlier:
        history |= set(_keys(findings(old)))
    ran = rooms_run(run)
    result = {"run": pathlib.Path(run).name,
              "since": pathlib.Path(since).name if since else None,
              "new": [], "still": [], "gone": [], "back": []}
    for key, entry in now.items():
        if key in before:
            result["still"].append(entry)
        elif key in history:
            result["back"].append(entry)
        else:
            result["new"].append(entry)
    for key, entry in before.items():
        if key not in now and key[0] in ran:
            result["gone"].append(entry)
    return result


def against_history(run: pathlib.Path, since: pathlib.Path | None = None) -> dict:
    """Compare ``run`` with ``since`` (default: the run before it in the same
    rooms directory), counting every run before ``since`` as history."""
    run = pathlib.Path(run)
    every = [r for r in runs(run.parent) if stamp(r) < stamp(run)]
    if since is None:
        since = every[-1] if every else None
    earlier = [r for r in every if since is None or stamp(r) < stamp(since)]
    return compare(run, since, earlier)


def text(result: dict) -> str:
    lines = [f"{result['run']} against {result['since'] or 'nothing earlier'}"]
    names = {"new": "new", "still": "still there", "gone": "gone (not seen this time)",
             "back": "back"}
    for key, name in names.items():
        entries = result[key]
        lines.append(f"\n{name} ({len(entries)})")
        lines += [f"  [{e.get('severity', '?')}] {e.get('room', '')}  {e.get('id', '')}"
                  f"  - {e.get('title', '')}" for e in entries]
    return "\n".join(lines)
