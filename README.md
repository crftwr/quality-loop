# quality-loop

Measure what an agent-facing product teaches.

A skill bundle, an MCP server or a CLI is only as good as what an agent with
nothing else can do with it. quality-loop runs that agent on a real task, in a
**room** that holds the product's agent-facing surface and nothing more. The
room is started so it cannot read the repository the answers are in.
Afterwards an **operator** agent reports the problems it finds in what the
room did, each with a severity and the evidence for it.

There is no pass/fail. The report is for a human, who decides what to fix.
Every problem carries a stable id, where it would be fixed and how a fix is
confirmed. That is how the loop closes: run, read, fix, run again, and check
by id that the problem is gone.

```
pip install quality-loop
```

Python 3.11 or later, no runtime dependencies. It drives
[Claude Code](https://claude.com/claude-code) (`claude`) as subprocesses, so
that has to be installed and signed in. macOS and Windows.

## See it work

The repository has a product small enough to read in a minute: a "greeter"
skill that reads a house style and writes one file.

```
git clone https://github.com/crftwr/quality-loop && cd quality-loop
make test                                # the harness's own tests
.venv/bin/python examples/toy/run.py     # one room, one operator, a few cents
```

It builds a room, stands a fixture in for the user's `style.txt`, opens a page
in the browser, drives the room, and has the operator report. The output is
`rooms/<version>-<time>/FINDINGS.md`.

## A run, per scenario

```
build the room - the bundle, RULES.md, and TASK.md holding the scenario's Prompt, verbatim
stand fixtures in for the user's files
operator, phase 1 - put the scenario's screen up, by name
the room's session - isolated, non-interactive
collect what the room made, put the user's files back, audit the transcript
operator, phase 2 - read the record, check the Must lists with evidence tools, write REPORT.md
```

## Documentation

- [Concepts](https://github.com/crftwr/quality-loop/blob/main/docs/concepts.md): rooms, operators, scenarios, reports, the
  loop, and which parts are code rather than an agent's judgement.
- [Writing scenarios](https://github.com/crftwr/quality-loop/blob/main/docs/scenarios.md): the Markdown format, and what makes
  a scenario measure something.
- [Writing an adapter](https://github.com/crftwr/quality-loop/blob/main/docs/adapters.md): what a product supplies, including
  its bundle, the room's reach, the stand-in, screens and evidence tools.
- [Reports](https://github.com/crftwr/quality-loop/blob/main/docs/reports.md): problems, severities, kinds and ids, and
  `FINDINGS.md` / `findings.json`.
- [Isolation and permissions](https://github.com/crftwr/quality-loop/blob/main/docs/isolation.md): what keeps the room and
  the operator in bounds, why each rule exists, and the known limits.
- [Development](https://github.com/crftwr/quality-loop/blob/main/docs/development.md): tests, live tests, releasing.

## Products using it

- [Keyhac](https://github.com/crftwr/keyhac): `qa/`, `make qa`
- [XeFM](https://github.com/crftwr/xefm) (planned)

## Status

0.x, early. It has been run end to end on macOS against the toy and against
Keyhac. The Windows screen backends are unit-tested but have not yet been run
on a Windows machine. The design discussion is
[crftwr/keyhac#205](https://github.com/crftwr/keyhac/issues/205).

MIT licensed.
