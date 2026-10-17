# Writing scenarios

A scenario is one Markdown file in the product's scenarios directory, named
`NN_short_name.md`. The number orders the run and lets a person pick one
(`11`, `11_f1_off_in_vscode` or `f1_off_in_vscode` all name the same file).
Files starting with `_` or `README` are not scenarios. A product can keep
shared material there, such as Keyhac's `_always.md`, which holds what every
room is held to.

```markdown
+++
title = "Stop F1 doing anything in VS Code"
edits_config = true
configs = ["template", "short", "grown"]
+++

## Prompt

I keep hitting F1 by accident in VS Code and it throws up the command palette.
Make F1 do nothing in VS Code - everywhere else it should stay as it is.

## Screen

None. The room works on config.py through the product's own tools.

## Must

- With VS Code focused, F1 does nothing; in any other application it still
  arrives as F1. On macOS that includes Fn+F1.
- The reply asks the user to press F1 in VS Code, since nothing in the tools
  can.

## Must not

- Bind F1 in the global table.
- Report it working before anyone has pressed it.
```

## Front matter

TOML between `+++` lines. `title` is required. Every other key belongs to the
product, which receives the whole table as `Scenario.meta`. Keyhac uses:

| Key | Meaning |
|---|---|
| `edits_config` | The task changes the user's config, so it runs on every fixture config. |
| `configs` | Which fixture configs to run it on. |
| `staged` | `[[fixture, name], ...]` input files put on the Desktop. |
| `needs` | A screen only the person running it can put up. The scenario is left out of a run of everything and runs when named. |

## Sections

The `## ` headings, in any order. Headings inside fenced code are ignored.

- **Prompt** (required). What a user would actually type, and the only part
  that reaches the room. It is copied into `TASK.md` exactly as written.
- **Screen**. What the operator must put up before the room starts, written
  for the operator. Name the product's declared screens in backticks
  (`` `approval-queue` ``), or say "None".
- **Must** (required). The observable outcomes first, then what to read for.
  The operator checks each line against evidence.
- **Must not**. What a run must not do.

## What makes a scenario measure something

**The Prompt names an intent, never a mechanism.** "Make F1 do nothing in VS
Code", not "use `define_keytable(app=...)` to bind F1 to a no-op". A prompt
that names the API has done the bundle's work for it, and the run measures
nothing.

**Each Prompt stands on its own.** A room gets one scenario and nothing else.
"Same as above" sends it looking for the half it was not given.

**Name things the way the screen names them.** If the page calls itself
"SystemA", the prompt says SystemA. The room should have to find it, not
decode it.

**Must lines are observable.** "F1 sends nothing with VS Code focused" can be
checked with an evidence tool. "The room understood tables" cannot. Put the
outcome first, then the reading ("the condition uses the config's own idea of
a terminal").

**Platform differences belong in the Must lines.** For example: "On macOS
that includes Fn+F1, which is how F1 is typed while the top row is on media
keys." The operator turns that into the right evidence calls on each OS.

**The scoring key never reaches the room.** The parser refuses a scenario
whose Prompt contains one of its own Must or Must not lines (20 characters or
longer, whitespace-insensitive). That is the copy-paste one line too long. It
cannot catch a paraphrase, so keep the two sections apart when you edit.

## Checking scenarios without a run

A product's own tests should parse every scenario and check what can be
checked without a room. Keyhac's `tests/test_qa.py` does this: every
scenario parses, every screen it names is declared, every staged file exists.

```python
from quality_loop import scenario

cases = scenario.load(SCENARIOS_DIR)
```
