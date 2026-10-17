# Development

```
make test                         # every test that needs no window and no model
QUALITY_LOOP_LIVE=1 make test     # also opens real windows on this OS
.venv/bin/python examples/toy/run.py   # a real run, end to end, a few cents
```

## Layout

```
quality_loop/
  room.py         build a room: bundle, RULES.md, TASK.md, QUESTIONS.md, the canary
  session.py      the room's session: flags, environment, driving it, the heartbeat
  audit.py        the transcript audit
  transcript.py   reading stream-json, tolerantly
  standin.py      fixtures in for the user's files, and back
  pages.py        fixture pages over HTTP, and their event record
  screens/        screens by name: the manifest, macOS and Windows backends
  mcp.py          the operator's tools, as a stdio MCP server
  operator.py     the operator's session, two phases
  OPERATOR.md     the operator's instructions (package data)
  scenario.py     Markdown scenarios
  report.py       REPORT.md, FINDINGS.md, findings.json
  adapter.py      what a product supplies
  runner.py       a run, per scenario
  __main__.py     `python -m quality_loop screen ...`, for a person
examples/toy/     a complete product and adapter, for an end-to-end run
tests/
```

## Tests

- **Unit tests** cover everything that can go wrong without a model:
  - the room's contents and refusals
  - the session's flags and environment, including a real `git` under the
    ceiling
  - the audit against hand-written transcripts
  - the transcript reader on every malformed shape a real one has had
  - the stand-in, including an interrupted run and a stale marker
  - the screen manifest and "close only what was opened"
  - the MCP server's protocol and refusals
  - the operator's command line, and phase 1's room check
  - scenario parsing and the leak check
  - report parsing
- **Live tests** (`QUALITY_LOOP_LIVE=1`) open and close a real page and a real
  terminal on the OS they run on. On macOS they need Automation permission for
  Safari and Terminal. They leave nothing open, and a test that does is a bug.
- **The toy run** is the integration test. It costs a few cents and a minute.
  Run it after any change to the operator, the runner, the MCP server or
  OPERATOR.md. Changes to those have broken in ways only a real `claude`
  shows: a permission rule spelled wrong, a file outside what the operator may
  read.

The Windows backends are unit-tested only, pending a run on a Windows machine.

## Conventions

- **No runtime dependencies.** Everything is the standard library, including
  the MCP server.
- **Paid for, then written down.** A rule that exists because a run went
  wrong says so in a comment or docstring: what happened, and what it cost.
  That is what stops the next person from "simplifying" it away.
- **Anything a run depends on is code.** When a choice is between telling an
  agent to do something and making the code do it, make the code do it. See
  [Concepts](concepts.md).
- **Windows ctypes** declare every `argtypes` and `restype`. The default
  `c_int` restype truncates handles on 64-bit.

## Releasing

The version lives only in `quality_loop/__init__.py`. `pyproject.toml` reads
it.

1. Check that `main` is clean and up to date, and that `make test` passes.
   Run the toy if anything in the run's path changed.
2. Set `__version__`, and commit "Releasing X.Y.Z".
3. `make build` builds the sdist and the wheel, and runs `twine check --strict`.
4. Install the wheel into a fresh venv and smoke-test it. Check that
   `quality_loop.operator.INSTRUCTIONS` exists, and that `python -m
   quality_loop.mcp` answers `initialize`. OPERATOR.md is package data, and a
   wheel without it gives an operator with no instructions.
5. Run `git tag -a vX.Y.Z` and push `main` and the tag.
6. `.venv/bin/python -m twine upload dist/quality_loop-X.Y.Z*`. A PyPI version
   can never be re-uploaded, so this comes after the tag is pushed.
7. `gh release create vX.Y.Z --notes-file <note> dist/quality_loop-X.Y.Z*`,
   with a hand-written note:
   - It starts `## quality-loop X.Y.Z`.
   - Each change is a bold headline in user terms followed by prose.
8. Check what downstream waits on it, for example a `quality-loop>=X.Y.Z` pin
   in Keyhac or XeFM.
