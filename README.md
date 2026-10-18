# quality-loop

Measure what a product teaches.

A skill bundle, an MCP server, a CLI - or a manual and the app it describes -
is only as good as what someone with nothing else can do with it.
quality-loop runs an agent on a real task, in a **room** that holds what the
product gives its users and nothing more. The room is started so it cannot
read the repository the answers are in. Afterwards an **operator** agent
reports the problems it finds in what the room did, each with a severity and
the evidence for it.

There is no pass/fail. The point is **discovery**: each run should surface
something the last one did not, and leave a record good enough for a person,
or a development-time agent, to reproduce what it found. Every problem
carries a stable id, so the same problem is recognised across runs:
de-duplicated, seen to be gone, seen to come back.

```
pip install quality-loop            # 'quality-loop[tui]' to drive terminal apps
```

Python 3.11 or later, no runtime dependencies (driving a terminal app needs
`pyte`, the `tui` extra). It drives [Claude Code](https://claude.com/claude-code)
(`claude`) as subprocesses, so that has to be installed and signed in. macOS
and Windows; terminal apps on macOS and Linux.

## See it work

The repository has two products small enough to read in a minute.

```
git clone https://github.com/crftwr/quality-loop && cd quality-loop
make test                                # the harness's own tests
.venv/bin/python examples/toy/run.py     # an agent-facing skill: one room, a few cents
.venv/bin/python examples/tui/run.py     # a terminal app and its manual
```

The toy is a "greeter" skill that reads a house style and writes one file.
The TUI example is a note list whose manual is the only thing the room is
given; the room drives the app itself, and the operator checks it live. The
output is `rooms/<version>-<time>/FINDINGS.md`.

## A run, per scenario

```
build the room - the bundle, RULES.md, and TASK.md holding the scenario's Prompt, verbatim
stand fixtures in for the user's files
operator, phase 1 - put the scenario's screen up, by name
the room's session - isolated, non-interactive
operator, live check - drive the real app, when the scenario asks for one
collect what the room made, put the user's files back, audit the transcript
operator, phase 2 - read the record, check the Must lists with evidence, write REPORT.md
```

## The loop

```
quality-loop init                      # in the product: the conductor skill and settings
quality-loop run 11 12                 # starts a run in the background, prints its id
quality-loop watch                     # follow it from a terminal
quality-loop findings                  # new / still there / gone / back, against the run before
```

`init` installs a skill for the **conductor**: a Claude Code session in the
product's repository that plans with the person, sets the product up, runs,
files findings as GitHub Issues, fixes what the person chooses, and retests,
under a policy the person sets. See [Running the loop](https://github.com/crftwr/quality-loop/blob/main/docs/running.md).

## Documentation

- [Concepts](https://github.com/crftwr/quality-loop/blob/main/docs/concepts.md): rooms, operators, the conductor, scenarios,
  reports, and which parts are code rather than an agent's judgement.
- [Running the loop](https://github.com/crftwr/quality-loop/blob/main/docs/running.md): the command line, watching a run,
  parallel runs, comparing findings, the conductor and its policy.
- [Writing scenarios](https://github.com/crftwr/quality-loop/blob/main/docs/scenarios.md): the Markdown format, doc-driven
  scenarios, and what makes a scenario measure something.
- [Writing an adapter](https://github.com/crftwr/quality-loop/blob/main/docs/adapters.md): what a product supplies, from a
  launch command and a redirected home up to evidence tools of its own.
- [Reports](https://github.com/crftwr/quality-loop/blob/main/docs/reports.md): problems, severities, kinds and ids, the
  reproduction record, and `FINDINGS.md` / `findings.json`.
- [Isolation and permissions](https://github.com/crftwr/quality-loop/blob/main/docs/isolation.md): what keeps the room, the
  operator and the conductor in bounds, why each rule exists, and the known limits.
- [Development](https://github.com/crftwr/quality-loop/blob/main/docs/development.md): tests, live tests, releasing.

## Products using it

- [Keyhac](https://github.com/crftwr/keyhac): `qa/`, `make qa`
- [XeFM](https://github.com/crftwr/xefm) (planned)

## Status

0.x, early. It has been run end to end on macOS against the two examples,
Keyhac and XeFM (including XeFM's terminal UI in a live check), and on
Windows (11, ARM64) against the toy, Keyhac and XeFM, with real page and
terminal screens. Not yet run anywhere for real: synthetic keys and
screenshots of a desktop app (`drive.DesktopApp`); a terminal app is not
driven on Windows yet. The design discussion is
[crftwr/keyhac#205](https://github.com/crftwr/keyhac/issues/205) and this
repository's issues.

MIT licensed.
