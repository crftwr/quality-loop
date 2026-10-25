# Development

```
make test                         # every test that needs no window and no model
QUALITY_LOOP_LIVE=1 make test     # also opens real windows on this OS
.venv/bin/python examples/toy/run.py   # a real run, end to end, a few cents
.venv/bin/python examples/tui/run.py   # a terminal app and its manual, with a live check
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
  drive/          driving the app: key notation, a pty with pyte, OS keys and screenshots
  mcp.py          quality-loop's tools, as a stdio MCP server: screens, evidence, apps
  operator.py     the operator's session: phase 1, the live check, phase 2
  OPERATOR.md     the operator's instructions (package data)
  scenario.py     Markdown scenarios
  report.py       REPORT.md, FINDINGS.md, findings.json
  adapter.py      what a product supplies
  runner.py       a run: the queue, and per room the phases
  progress.py     run.log and status.json
  processes.py    the sessions running, so a cancel ends them all
  compare.py      findings across runs: new, still there, gone, back
  config.py       qa/quality-loop.toml, and loading the adapter it names
  install.py      `quality-loop init`: the skill and the settings
  skill/          the conductor's skill (package data)
  cli.py          the `quality-loop` command
examples/toy/     a skill and its adapter, for an end-to-end run
examples/tui/     a terminal app, its manual and its adapter
tests/            fake_claude.py stands in for `claude` on the runner's whole path
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
  - the key notation, a terminal app driven in a pty, and the step record
  - status.json, run.log and `watch`; comparing runs; `init` and `--upgrade`
  - the queue: its limit, its resources, a failure, rooms that would share
  - a whole run, side by side, detached and cancelled - with
    `tests/fake_claude.py` standing in for `claude`
- **Live tests** (`QUALITY_LOOP_LIVE=1`) open and close a real page and a real
  terminal on the OS they run on. On macOS they need Automation permission for
  Safari and Terminal. They leave nothing open, and a test that does is a bug.
- **The toy run** is the integration test. It costs a few cents and a minute.
  Run it after any change to the operator, the runner, the MCP server or
  OPERATOR.md, and the TUI example after a change to `drive/` or the live
  check. Changes to those have broken in ways only a real `claude`
  shows: a permission rule spelled wrong, a file outside what the operator may
  read.

The screen backends have run live on both OSes. The desktop-app key and
screenshot backends (`drive/_mac.py`, `drive/_windows.py`) are unit-tested
only. On Windows the fake `claude` (a shell script) and the pty backend are
skipped, so the whole-run and terminal-app tests run on macOS and Linux.

## Conventions

- **No runtime dependencies.** Everything is the standard library, including
  the MCP server. The one exception is the `tui` extra: `pyte`, a terminal
  emulator, imported only when a terminal app is driven.
- **Paid for, then written down.** A rule that exists because a run went
  wrong says so in a comment or docstring: what happened, and what it cost.
  That is what stops the next person from "simplifying" it away.
- **Anything a run depends on is code.** When a choice is between telling an
  agent to do something and making the code do it, make the code do it. See
  [Concepts](concepts.md).
- **Windows ctypes** declare every `argtypes` and `restype`. The default
  `c_int` restype truncates handles on 64-bit.

## Compatibility

- **Before 1.0.0**, any release may break the API: the adapter interface, the
  scenario and report formats, the operator's tools.
- **From 1.0.0**, compatibility is kept outside major releases as a rule.
  quality-loop is a developer tool, not an end-user product, so an exception
  is weighed case by case rather than ruled out.

Either way, a release note says what a downstream adapter has to change.

## Releasing

The version lives only in `quality_loop/__init__.py`. `pyproject.toml` reads
it.

1. Check that `main` is clean and up to date, and that `make test` passes.
   Run the toy if anything in the run's path changed.
2. Set `__version__`, and commit "Releasing X.Y.Z".
3. `make build` builds the sdist and the wheel, and runs `twine check --strict`.
4. Install the wheel into a fresh venv and smoke-test it. Check that
   `quality_loop.operator.INSTRUCTIONS` exists, that `python -m
   quality_loop.mcp` answers `initialize`, and that `quality-loop init` in an
   empty directory writes `.claude/skills/quality-loop/` with its references.
   The MCP server will not start without a screens manifest: write one with
   `screens.write_manifest` and name it in `QUALITY_LOOP_MANIFEST`.
   OPERATOR.md and the skill are package data: a wheel without them gives an
   operator with no instructions and a conductor with no skill.
5. Run `git tag -a vX.Y.Z` and push `main` and the tag.
6. `.venv/bin/python -m twine upload dist/quality_loop-X.Y.Z*`. A PyPI version
   can never be re-uploaded, so this comes after the tag is pushed.
7. `gh release create vX.Y.Z --notes-file <note> dist/quality_loop-X.Y.Z*`,
   with a hand-written note:
   - It starts `## quality-loop X.Y.Z`.
   - Each change is a bold headline in user terms followed by prose.
8. Check what downstream waits on it, for example a `quality-loop>=X.Y.Z` pin
   in Keyhac or XeFM.
