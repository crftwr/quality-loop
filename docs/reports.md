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
| **skill gap** | The product's agent-facing text should have said it. |
| **product** | The product itself behaves wrongly. |
| **harness** | The runner, or the room's tools. |
| **out of scope** | True of the task or the application, not of the product. |

Only **skill gap** and **product** change the product. Acting on the other two
only grows it.

## The fields a loop needs

- **Id** names the problem, not the run: kebab-case and stable. A later run
  reports the same problem under the same id. That is how a fix is seen to
  have worked, and how a problem that keeps coming back is seen at all.
- **Evidence** is what a tool answered or what the transcript shows, with
  where it is. A problem without evidence is malformed.
- **Where it would be fixed** names the file and section in the product.
- **How a fix is confirmed** names the evidence that would show it fixed,
  usually the same call that found it.

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

## FINDINGS.md and findings.json

`FINDINGS.md` opens with a count by severity and a table of every problem,
most severe first. Each room's report follows. A room whose operator wrote
nothing says so.

`findings.json` holds the same problems as a list of objects:

```json
[{"severity": "high", "title": "...", "id": "fn-f1-not-bound", "kind": "skill gap",
  "must": "...", "evidence": "...", "where": "...", "confirm": "...",
  "detail": "...", "room": "11_f1_off_in_vscode"}]
```

Comparing two runs' `findings.json` by `room` and `id` says what was fixed,
what remains and what is new. That comparison is what the loop's next step
builds on. It is not automated yet.
