"""``quality-loop init``: the conductor's skill and the product's settings.

Installed by a script, not by an agent copying files. The skill's wording is
load-bearing - the rules about what never reaches a room or an operator
above all - and an agent copying it may summarise or "improve" it; versions
have to match reliably; and before the skill is installed no agent knows how
to install it. An agent may still *run* ``init``: the result does not depend
on who starts it.

What it does, every time to the same effect:

- copies the skill from the package into ``.claude/skills/quality-loop/`` in
  the product's checkout, stamped with the package's version, and records
  what it wrote in ``.quality-loop.json`` beside it;
- writes ``qa/quality-loop.toml`` with the quality-loop command it was run
  as, so the conductor uses the same installation;
- adds the rooms directory to ``.gitignore``.

It does not write the adapter or the scenarios, or arrange ``qa/``: that is
judgement, and the conductor's job with the person.

``--upgrade`` replaces the skill with this package's. A copy edited by hand
is shown as a diff and left alone unless ``--force``: what is particular to a
product belongs in ``qa/PLAN.md``, never in the skill.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import pathlib
import shutil
import sys

import quality_loop

SKILL = pathlib.Path(__file__).with_name("skill")
NAME = "quality-loop"
STAMP = ".quality-loop.json"
VERSION_MARK = "__QUALITY_LOOP_VERSION__"


def _files(root: pathlib.Path) -> dict[str, pathlib.Path]:
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*"))
            if p.is_file() and p.name != STAMP and "__pycache__" not in p.parts}


def packaged() -> dict[str, str]:
    """``{relative path: text}`` of the skill as this package ships it."""
    return {name: path.read_text(encoding="utf-8").replace(VERSION_MARK,
                                                            quality_loop.__version__)
            for name, path in _files(SKILL).items()}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def installed_version(target: pathlib.Path) -> str | None:
    try:
        return json.loads((target / STAMP).read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def edited(target: pathlib.Path) -> list[str]:
    """Files of an installed skill that differ from what init wrote."""
    try:
        recorded = json.loads((target / STAMP).read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError):
        return sorted(_files(target))
    found = []
    present = _files(target)
    for name, digest in recorded.items():
        path = present.get(name)
        if path is None or _hash(path.read_text(encoding="utf-8")) != digest:
            found.append(name)
    found += [name for name in present if name not in recorded]
    return sorted(found)


def write_skill(target: pathlib.Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    texts = packaged()
    for name, text in texts.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    (target / STAMP).write_text(json.dumps(
        {"version": quality_loop.__version__,
         "files": {name: _hash(text) for name, text in texts.items()}}, indent=2) + "\n",
        encoding="utf-8")


def command_for(root: pathlib.Path) -> str:
    """How this installation of quality-loop is run from ``root``."""
    scripts = pathlib.Path(sys.executable).parent
    script = scripts / ("quality-loop.exe" if os.name == "nt" else "quality-loop")
    on_path = shutil.which("quality-loop")
    if script.exists():
        if on_path and pathlib.Path(on_path).resolve() == script.resolve() \
                and root.resolve() not in script.resolve().parents:
            return "quality-loop"
        try:
            return script.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return str(script)
    return "quality-loop" if on_path else f"{sys.executable} -m quality_loop"


def commands_for(root: pathlib.Path) -> dict[str, str]:
    """``command``, and ``command_windows`` beside it when the installation is
    a venv in the checkout: the settings file is committed, and the same
    venv's script is somewhere else on the other OS."""
    found = {"command": command_for(root)}
    for posix, windows in ((".venv/bin/quality-loop", ".venv/Scripts/quality-loop.exe"),):
        mine = found["command"]
        if mine.endswith(posix) or mine.endswith(windows):
            stem = mine[:-len(posix)] if mine.endswith(posix) else mine[:-len(windows)]
            found = {"command": stem + posix, "command_windows": stem + windows}
    return found


def _toml_line(key: str, value: str) -> str:
    return f'{key} = {json.dumps(value)}'


def write_settings(root: pathlib.Path, rooms: str, adapter: str | None, say) -> None:
    path = root / "qa" / "quality-loop.toml"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        import tomllib
        values = tomllib.loads(text)
        additions = []
        if "command" not in values:
            additions += [_toml_line(k, v) for k, v in commands_for(root).items()]
        if "adapter" not in values and adapter:
            additions.append(_toml_line("adapter", adapter))
        if additions:
            path.write_text(text.rstrip("\n") + "\n" + "\n".join(additions) + "\n",
                            encoding="utf-8")
            say(f"updated  {path.relative_to(root)}: {', '.join(a.split()[0] for a in additions)}")
        else:
            say(f"kept     {path.relative_to(root)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if adapter is None and (root / "qa" / "run.py").exists():
        adapter = "qa/run.py"
    lines = ["# quality-loop's settings for this product. See `quality-loop --help`.",
             "", "# The installation the conductor runs.",
             *[_toml_line(k, v) for k, v in commands_for(root).items()],
             "", "# The adapter: a file, and optionally its class (qa/run.py:Product)."]
    lines.append(_toml_line("adapter", adapter) if adapter
                 else '# adapter = "qa/run.py"')
    lines += ["", "# Where runs are kept. Gitignored.", _toml_line("rooms", rooms), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    say(f"wrote    {path.relative_to(root)}")


def ignore_rooms(root: pathlib.Path, rooms: str, say) -> None:
    path = root / ".gitignore"
    entry = "/" + rooms.strip("/") + "/"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    names = {line.strip().strip("/") for line in text.splitlines()}
    if rooms.strip("/") in names:
        return
    path.write_text(text + ("" if text.endswith("\n") or not text else "\n")
                    + f"\n# quality-loop's rooms and run records\n{entry}\n", encoding="utf-8")
    say(f"ignored  {entry} in .gitignore")


def init(root: pathlib.Path, *, upgrade: bool = False, force: bool = False,
         rooms: str | None = None, adapter: str | None = None, say=print) -> int:
    root = pathlib.Path(root).resolve()
    target = root / ".claude" / "skills" / NAME
    current = quality_loop.__version__
    have = installed_version(target) if target.exists() else None
    if not target.exists():
        write_skill(target)
        say(f"skill    .claude/skills/{NAME} ({current})")
    elif not upgrade:
        if have == current:
            say(f"skill    .claude/skills/{NAME} is {current} already")
        else:
            say(f"skill    .claude/skills/{NAME} is {have or 'unstamped'}; this package is "
                f"{current} - run `quality-loop init --upgrade`")
    else:
        changed = edited(target)
        if changed and not force:
            say(f"skill    .claude/skills/{NAME} was edited by hand: {', '.join(changed)}")
            new = packaged()
            for name in changed:
                path = target / name
                old = path.read_text(encoding="utf-8").splitlines(keepends=True) \
                    if path.exists() else []
                say("".join(difflib.unified_diff(
                    old, new.get(name, "").splitlines(keepends=True),
                    f"installed/{name}", f"{current}/{name}")))
            say("Nothing was changed. What is particular to this product belongs in "
                "qa/PLAN.md. Run with --force to replace the skill anyway.")
            return 1
        write_skill(target)
        say(f"skill    .claude/skills/{NAME}: {have or 'unstamped'} -> {current}")
    settings = root / "qa" / "quality-loop.toml"
    if rooms is None:
        rooms = "rooms"
        if settings.exists():
            import tomllib
            rooms = tomllib.loads(settings.read_text(encoding="utf-8")).get("rooms", rooms)
    write_settings(root, rooms, adapter, say)
    ignore_rooms(root, rooms, say)
    user_level = pathlib.Path.home() / ".claude" / "skills" / NAME
    if user_level.exists():
        say(f"warning  {user_level} exists. Whether a user-level skill reaches a room "
            f"under --restricted has not been measured; keep the skill in the project.")
    import tomllib
    configured = tomllib.loads(settings.read_text(encoding="utf-8")).get("adapter")
    if configured:
        say("\nNext: `quality-loop check`, then ask Claude Code in this checkout to plan "
            "a run - the skill takes it from there.")
    else:
        say("\nNext: ask Claude Code, in this checkout, to set quality-loop up for this "
            "product. The skill takes it from there - a few questions, a plan, an "
            "adapter and first scenarios.")
    return 0
