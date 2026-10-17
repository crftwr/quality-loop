"""Scenarios: one Markdown file per task, written in natural language.

```markdown
+++
title = "Stop F1 doing anything in VS Code"
edits_config = true
+++

## Prompt

What a user would actually type - the only part that reaches the room.

## Screen

What has to be in front before the room starts, for the operator to put up.

## Must

- The observable outcomes, then what to read for.

## Must not

- What a run must not do.
```

The front matter is TOML between ``+++`` lines. ``title`` is required; every
other key is the product's to define (which configs to run on, which input
files to stage, a screen only the operator can supply) and is handed to it
as-is in ``Scenario.meta``.

The sections are the ``## `` headings. **Prompt** and **Must** are required.
The prompt is taken verbatim - the text between its heading and the next one -
because it is the one thing that reaches the room, and the runner, not the
operator agent, is what copies it there. A Must line that also appears in the
prompt refuses the scenario: that is the scoring key leaking, and it has
happened through a copy-paste one line too long.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import tomllib

#: Sections every scenario has.
REQUIRED = ("Prompt", "Must")

_HEADING = re.compile(r"^## +(.+?)\s*$")
_FENCE = re.compile(r"^(```|~~~)")


class ScenarioError(Exception):
    """A scenario file that cannot be run as written."""


@dataclasses.dataclass
class Scenario:
    """One task, as its file states it.

    Attributes:
        path: The file.
        name: Its stem: ``11_f1_off_in_vscode``.
        number: The leading number of the stem, or None.
        title: From the front matter.
        meta: The whole front matter, for the product to read.
        sections: ``{heading: text}``, in file order.
    """
    path: pathlib.Path
    name: str
    number: int | None
    title: str
    meta: dict
    sections: dict[str, str]

    @property
    def prompt(self) -> str:
        """What the room is handed, exactly as written."""
        return self.sections["Prompt"]

    def section(self, heading: str) -> str:
        """A section's text, or "" when the scenario has none."""
        return self.sections.get(heading, "")


def parse(path: pathlib.Path) -> Scenario:
    """Read one scenario file, or say what is wrong with it."""
    path = pathlib.Path(path)
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    meta, body = _front_matter(text, path)
    if not isinstance(meta.get("title"), str) or not meta["title"].strip():
        raise ScenarioError(f"{path.name}: the front matter has no title")
    sections = _sections(body)
    if missing := [h for h in REQUIRED if not sections.get(h, "").strip()]:
        raise ScenarioError(f"{path.name}: no {', '.join(missing)} section")
    _refuse_a_leak(sections, path)
    number = re.match(r"(\d+)", path.stem)
    return Scenario(path=path, name=path.stem,
                    number=int(number.group(1)) if number else None,
                    title=meta["title"].strip(), meta=meta, sections=sections)


def load(directory: pathlib.Path, names: list[str] | None = None) -> list[Scenario]:
    """Every scenario in ``directory`` in file order, or those ``names`` picks -
    by number, by stem, or by the stem without its number."""
    found = [parse(path) for path in sorted(pathlib.Path(directory).glob("*.md"))
             if not path.name.startswith(("_", "README"))]
    if not names:
        return found
    wanted = []
    for name in map(str, names):
        match = [s for s in found
                 if name in (s.name, s.name.split("_", 1)[-1])
                 or (name.isdigit() and s.number == int(name))]
        if not match:
            raise ScenarioError(f"no scenario {name!r}; have: "
                                + ", ".join(s.name for s in found))
        wanted += match
    return wanted


def _front_matter(text: str, path: pathlib.Path) -> tuple[dict, str]:
    if not text.startswith("+++\n"):
        raise ScenarioError(f"{path.name}: does not start with +++ front matter")
    end = text.find("\n+++\n", 4)
    if end < 0:
        raise ScenarioError(f"{path.name}: the front matter is never closed with +++")
    try:
        meta = tomllib.loads(text[4:end])
    except tomllib.TOMLDecodeError as error:
        raise ScenarioError(f"{path.name}: front matter: {error}") from None
    return meta, text[end + len("\n+++\n"):]


def _sections(body: str) -> dict[str, str]:
    """``## `` headings and the text under each, ignoring fenced code."""
    sections: dict[str, list[str]] = {}
    current = None
    fenced = False
    for line in body.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading:
            current = heading.group(1)
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {h: "\n".join(lines).strip("\n") + "\n" for h, lines in sections.items()}


def _refuse_a_leak(sections: dict[str, str], path: pathlib.Path) -> None:
    prompt = " ".join(sections["Prompt"].split()).lower()
    for heading in ("Must", "Must not"):
        for line in sections.get(heading, "").splitlines():
            said = " ".join(line.strip().lstrip("-*").split()).lower()
            if len(said) >= 20 and said in prompt:
                raise ScenarioError(
                    f"{path.name}: the prompt carries a line of {heading}: {line.strip()!r}"
                    f" - that is the scoring key reaching the room")
