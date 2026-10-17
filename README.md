# quality-loop

Measure what an agent-facing product teaches.

A skill bundle, an MCP server or a CLI is only as good as what an agent with
nothing else can do with it. quality-loop runs that agent on a real task, in a
**room** that holds the product's agent-facing surface and nothing else. The
room is started so it cannot read the repository where the answers are.
Afterwards an **operator** agent reports the problems it finds in what the
room did, each with a severity. A human decides what to do with the report.

> Status: early development. The shared core is here: rooms, the session's
> isolation, the audit, the transcript reader, standing fixtures in for the
> operator's files, and fixture pages. The operator agent, Markdown scenarios
> and the report format come next. The design is
> [crftwr/keyhac#205](https://github.com/crftwr/keyhac/issues/205).

## What stays code, and why

Anything a run depends on to mean something is code, not something an agent
decides:

- **The prompt the room is handed** is copied verbatim. The operator knows
  what a good answer looks like, so any paraphrase of the prompt can leak it.
- **Isolation.** The room runs with `--restricted`, an explicit permission
  list under `dontAsk`, one MCP configuration and nothing else, git stopped at
  the room, and stdin closed. A transcript audit then checks what no flag can
  enforce.
- **The operator's machine.** Their files are moved aside and replaced with
  fixtures. On the way out they are put back in a `finally`, whether the run
  ended normally, by an exception, by Ctrl-C or by SIGTERM.
- **Evidence.** A report cites what tools recorded, not what the room said.

## Products using it

- [Keyhac](https://github.com/crftwr/keyhac)
- [XeFM](https://github.com/crftwr/xefm) (planned)

## Development

```
make test
```

MIT licensed.
