# Reports

The operator writes `REPORT.md` in the room. The runner concatenates every
room's report into `FINDINGS.md` and `findings.json` beside the rooms. No
second agent rewrites what the operators wrote.

## REPORT.md

```markdown
# Report: Stop F1 doing anything in VS Code

One paragraph: what the room was asked, what it did, and what it left.

### [high] F1 binding misses Fn+F1 on macOS
- **Id:** `fn-f1-not-bound`
- **Kind:** skill gap
- **Must:** "With VS Code focused, F1 does nothing ... includes Fn+F1"
- **Evidence:** `replay --app Code --keys Fn-F1` -> consumed: false
- **Where it would be fixed:** references/configuration.md, Key expressions
- **How a fix is confirmed:** re-run; the same replay reports consumed: true
- **Reproduce:** live steps 3-5

Free text: what happened, and why it matters.
```

One `### [severity] title` heading per problem, most severe first, followed by
the fields as `- **Label:** value` lines and then free text.

## Severity

| | |
|---|---|
| **critical** | The run did harm: data destroyed, the user's files rewritten or no longer loading, a destructive control pressed. |
| **high** | A Must not met, or a result that is silently wrong: one that looks right and is not. |
| **medium** | Met, but only by guessing something the product should have said, or after rework a user's agent would repeat. |
| **low** | Friction that cost little: an empty search, a retry, an unclear message. |

## Kind

| | |
|---|---|
| **skill gap** | The product's text - skill, tool descriptions or manual - should have said it, or says something the product does not do. |
| **product** | The product itself behaves wrongly. |
| **harness** | The runner, or the room's tools. |
| **out of scope** | True of the task or the application, not of the product. |

Only **skill gap** and **product** change the product. Acting on the other two
only grows it.

## The fields a loop needs

- **Id** names the problem, not the run: kebab-case and stable. A later run
  reports the same problem under the same id. Runs are not deterministic, so
  the id is first of all how findings are **de-duplicated across runs** -
  filed once, commented on when seen again - and how a problem that is gone,
  or keeps coming back, is seen at all.
- **Evidence** is what a tool answered, what the transcript shows, or a
  recorded live step and its screen, with where it is. A problem without
  evidence is malformed.
- **Where it would be fixed** names the file and section in the product: the
  docs or the product itself.
- **How a fix is confirmed** names the evidence that would show it gone,
  usually the same call that found it.
- **Reproduce** (optional) names the steps in the record a later agent
  follows.

## The reproduction record

What a person, or a development-time agent, needs to see a finding again is
in the room's directory:

- **The starting point**, `evidence/run.json`: the product and its version,
  the commit (and whether the checkout was dirty), the OS, Python, the
  models, the fixtures stood in, each app's terminal size or window title.
  The fixtures themselves are `evidence/before/`.
- **The steps**: the transcript; and for a live check `evidence/live/steps.jsonl`
  (the room's own driving: `evidence/app/`) - every key in order, the wait,
  and the agent's **intent** for each step: why it did it, what it expected.
  The intent is what lets a later agent adapt a step when the screen is
  slightly different.
- **What was seen**: a screen file per step (text, or a PNG), and the app's
  event-log lines since the step before.

An agent reproducing a finding rebuilds the start, follows the steps with the
same app tools, stops where the screen diverges from the record, shortens the
steps, and writes a regression test.

## What the runner checks

`report.parse` reads a report leniently. It reports an entry as **malformed**
when it is something a loop could not use:

- a severity outside the four
- a kind outside the four
- no id
- no evidence

Malformed entries are listed in `FINDINGS.md`, not dropped.

The runner writes a report of its own when a room could not be measured:

| Id | When |
|---|---|
| `phase-one-touched-room` | Operator phase 1 changed a file in the room, so the room was cancelled. |
| `isolation-breach` | The audit found a reach into the checkout, the installed package or the user's files that came back with something. Nothing the room did is evidence. |
| `lost-product`, `lost-model` | The product or the model's API stopped answering mid-run. A machine that sleeps with a room open wakes with no network. |
| `live-check-touched-room` | The live check changed a file in the room outside its own record. |
| `room-failed` | The room ended with an error in the harness or the adapter. The other rooms went on. |
| `room-not-built`, `room-not-started` | The room could not be built where it was asked for, or could not start safely: side by side with another room, it would have shared a directory or reached a stand-in marker. |

## FINDINGS.md and findings.json

`FINDINGS.md` opens with a count by severity and a table of every problem,
most severe first. Each room's report follows. A room whose operator wrote
nothing says so.

`findings.json` holds the same problems as a list of objects:

```json
[{"severity": "high", "title": "...", "id": "fn-f1-not-bound", "kind": "skill gap",
  "must": "...", "evidence": "...", "where": "...", "confirm": "...",
  "reproduce": "...", "detail": "...", "room": "11_f1_off_in_vscode",
  "run": "2.6.0-20261018-101500"}]
```

`quality-loop findings` compares two runs' `findings.json` by `room` and
`id`: new, still there, gone, back. See
[Running the loop](running.md#comparing-runs).
