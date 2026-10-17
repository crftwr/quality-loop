# CLAUDE.md: quality-loop

## What this is

A harness that measures what an agent-facing product teaches. A **room**
(an isolated Claude Code session given only the product's bundle) does a
real task, and an **operator** (a second session) reports the problems, each
with a severity and evidence. There is no verdict. Start with
[docs/concepts.md](docs/concepts.md). The design discussion is
[crftwr/keyhac#205](https://github.com/crftwr/keyhac/issues/205).

Users: [Keyhac](https://github.com/crftwr/keyhac) (`qa/`, `make qa`), and
XeFM (planned). Both live as sibling checkouts (`../keyhac`, `../xefm`).

## Rules for working here

- **Anything a run's meaning depends on is code, not an instruction to an
  agent.** That includes the prompt copied verbatim, the isolation, putting
  the user's files back, the room left untouched by phase 1, screens by
  declared name, and evidence from tools. If a change would move one of these
  into OPERATOR.md or RULES.md, stop and say so.
- **The operator has no shell and never uses the product's MCP.** Its tools
  are quality-loop's own MCP server (`quality_loop/mcp.py`). Do not give it
  Bash, even prefixed: Claude Code lets read-only commands such as `cat`
  through regardless of the allow list. [docs/isolation.md](docs/isolation.md)
  has the reasons, one per rule.
- **Comments that record a paid-for lesson are load-bearing.** "The first
  real run was refused every write" is the reason the code looks the way it
  does. Keep them, and add one when a run teaches something new.
- **No runtime dependencies.** The standard library only.
- **After a change to the run's path** (operator, runner, MCP server,
  OPERATOR.md, screens), run the toy:
  `.venv/bin/python examples/toy/run.py`. Unit tests have not caught what
  only a real `claude` shows.
- **Compatibility.** Until 1.0.0, breaking changes can happen in any
  release. From 1.0.0, compatibility is kept outside major releases as a
  rule. quality-loop is a developer tool rather than an end-user product, so
  an exception is judged case by case. Either way, downstream pins
  `quality-loop>=X.Y.Z`, and Keyhac's `qa/` uses the Adapter API,
  `screens.Page/Terminal`, `standin.StandIn/Watch`, `session.Session` and
  `audit.Policy`. Check `../keyhac/qa/run.py` (and XeFM's adapter once there is
  one) before changing any of those. Say in the release note what a downstream
  adapter must change.
- **Docs move with the code.** `docs/` describes the current behaviour. A
  change to a flag, a permission, the report format or the adapter API updates
  the page that describes it in the same commit.
- Releasing: [docs/development.md](docs/development.md#releasing).
