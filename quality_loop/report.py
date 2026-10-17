"""The report: problems, each with a severity, and what a loop needs to act on it.

The operator agent writes ``REPORT.md`` in the room, one ``### `` heading per
problem:

```markdown
### [high] F1 binding misses Fn+F1 on macOS
- **Id:** `fn-f1-not-bound`
- **Kind:** skill gap
- **Must:** "With VS Code focused, F1 does nothing ... includes Fn+F1"
- **Evidence:** `replay --app Code --keys Fn-F1` -> consumed: false
- **Where it would be fixed:** references/configuration.md, Key expressions
- **How a fix is confirmed:** re-run the scenario; the same replay reports consumed: true

Free text under the fields, as long as it needs to be.
```

There is no verdict. A human reads the report and decides what to do with
it. **Id**, **Where it would be fixed** and **How a fix is confirmed** are
there so the report can also feed the next step: a later run says of each id
whether it is fixed, still there, or new, and a fix is checked against the
same evidence the problem was found with.

`parse` is lenient about everything but what a loop depends on: a problem
with no severity, an unknown severity or kind, or no id is reported as
malformed rather than silently dropped.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re

#: Most severe first.
SEVERITIES = {
    "critical": "The run did harm: data destroyed, the operator's files rewritten "
                "or no longer loading, a destructive control pressed.",
    "high": "A Must not met, or a result that is silently wrong - one that looks "
            "right and is not.",
    "medium": "Met, but only by guessing something the product should have said, "
              "or after rework a user's agent would repeat.",
    "low": "Friction that cost little: an empty search, a retry, an unclear message.",
}

KINDS = {
    "skill gap": "The product's agent-facing text should have said it.",
    "product": "The product itself behaves wrongly.",
    "harness": "This runner, or the room's tools.",
    "out of scope": "True of the task or the application, not of the product.",
}

FIELDS = {
    "id": "Id",
    "kind": "Kind",
    "must": "Must",
    "evidence": "Evidence",
    "where": "Where it would be fixed",
    "confirm": "How a fix is confirmed",
}

_PROBLEM = re.compile(r"^### +\[(?P<severity>[^\]]+)\] +(?P<title>.+?)\s*$")
_FIELD = re.compile(r"^- +\*\*(?P<label>[^*]+?):\*\* *(?P<value>.*)$")


@dataclasses.dataclass
class Problem:
    severity: str
    title: str
    id: str = ""
    kind: str = ""
    must: str = ""
    evidence: str = ""
    where: str = ""
    confirm: str = ""
    detail: str = ""
    room: str = ""

    def problems(self) -> list[str]:
        """What is wrong with this entry as a loop would read it."""
        found = []
        if self.severity not in SEVERITIES:
            found.append(f"severity {self.severity!r} is not one of {list(SEVERITIES)}")
        if self.kind and self.kind not in KINDS:
            found.append(f"kind {self.kind!r} is not one of {list(KINDS)}")
        if not self.id:
            found.append("no id")
        if not self.evidence:
            found.append("no evidence")
        return found


def parse(text: str, room: str = "") -> tuple[list[Problem], list[str]]:
    """``(problems, malformed)`` from a REPORT.md."""
    by_label = {label.lower(): key for key, label in FIELDS.items()}
    problems: list[Problem] = []
    current: Problem | None = None
    detail: list[str] = []

    def close():
        if current is not None:
            current.detail = "\n".join(detail).strip()
            problems.append(current)

    for line in text.replace("\r\n", "\n").split("\n"):
        if heading := _PROBLEM.match(line):
            close()
            current = Problem(severity=heading["severity"].strip().lower(),
                              title=heading["title"], room=room)
            detail = []
        elif current is not None and (field := _FIELD.match(line)) \
                and field["label"].strip().lower() in by_label:
            value = field["value"].strip()
            key = by_label[field["label"].strip().lower()]
            if key == "id":
                value = value.strip("`")
            if key == "kind":
                value = value.lower()
            setattr(current, key, value)
        elif current is not None:
            detail.append(line)
    close()
    malformed = [f"{p.title}: {issue}" for p in problems for issue in p.problems()]
    return problems, malformed


def ordered(problems: list[Problem]) -> list[Problem]:
    """Most severe first, then by room, then by title."""
    rank = {name: n for n, name in enumerate(SEVERITIES)}
    return sorted(problems, key=lambda p: (rank.get(p.severity, len(rank)), p.room, p.title))


def findings(reports: list[tuple[str, str, str]]) -> tuple[str, list[dict]]:
    """FINDINGS.md and its machine-readable twin, from every room's report.

    ``reports`` is ``(room name, scenario title, REPORT.md text)`` per room. A
    concatenation and a count, made mechanically - no second agent rewrites
    what the operators wrote.
    """
    everything, sections = [], []
    for room, title, text in reports:
        problems, malformed = parse(text, room)
        everything += problems
        counts = ", ".join(f"{sum(p.severity == s for p in problems)} {s}"
                           for s in SEVERITIES)
        sections += [f"## {room}", "", f"{title}. {counts}.", ""]
        sections += [f"- **malformed report** - {m}" for m in malformed]
        sections += ([text.strip(), ""] if text.strip()
                     else ["(no report - the operator wrote nothing)", ""])
    total = ", ".join(f"{sum(p.severity == s for p in everything)} {s}"
                      for s in SEVERITIES)
    head = ["# Findings", "",
            f"{len(reports)} room(s): {total}. No verdict - each problem is the "
            f"operator's report of what it found, with the evidence it cites.", ""]
    table = ["| Severity | Room | Problem | Kind |", "|---|---|---|---|"]
    table += [f"| {p.severity} | {p.room} | {p.title} | {p.kind} |"
              for p in ordered(everything)]
    machine = [dataclasses.asdict(p) for p in ordered(everything)]
    return "\n".join(head + (table + [""] if everything else []) + sections), machine


def write_findings(directory: pathlib.Path, reports: list[tuple[str, str, str]]) -> pathlib.Path:
    """FINDINGS.md and findings.json in ``directory``."""
    text, machine = findings(reports)
    (directory / "FINDINGS.md").write_text(text, encoding="utf-8")
    (directory / "findings.json").write_text(json.dumps(machine, indent=2,
                                                        ensure_ascii=False),
                                             encoding="utf-8")
    return directory / "FINDINGS.md"
