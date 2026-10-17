# Concepts

## What is being measured

Not whether a model can do the task. The question is whether **the product's
agent-facing surface** lets an agent do it: the skill bundle, the tool
descriptions, the error messages. A model working from inside the product's
repository can read the source and the design notes. It will succeed where a
user's agent fails, and nobody learns why.

So the agent doing the task is given what a user's agent would have, and
nothing more. Every place it has to guess is a gap in the product, whether or
not it guessed right. **The failures are the product of a run.** A run that
goes perfectly and records nothing has told you little.

## The parts

**Scenario.** One Markdown file per task: what a user would type (the
**Prompt**), what must be on screen first (the **Screen**), and what a good
outcome is (**Must** and **Must not**). The Prompt is the only part that
reaches the room. See [Writing scenarios](scenarios.md).

**Room.** A directory holding the product's bundle, `RULES.md`, `TASK.md` (the
Prompt, verbatim) and an empty `QUESTIONS.md`. A Claude Code session is started
in it non-interactively and isolated by flags. It does the task, and writes
into `QUESTIONS.md` every point where the bundle did not tell it something. It
cannot ask anyone: a `-p` session has nobody to ask, and that is deliberate.
"Answer nothing it asks" is a discipline a person breaks at the first
plausible question, and an answered question is a destroyed finding.

**Operator.** A second Claude Code session, one per room, in two phases of one
conversation. Phase 1 puts the screen up. Phase 2 runs after the room has
finished and the runner has collected and audited. It reads the record, checks
each Must line with the product's evidence tools, and writes `REPORT.md`. It
judges the run. It never does the task, and it never touches the room before
or during it.

**Adapter.** The product's half: how its bundle is built, what a room may
reach, which of the user's files are stood in for, which screens exist, and
which evidence tools answer questions about a run. See
[Writing an adapter](adapters.md).

**Report.** Problems, most severe first, each with a severity, a kind, an id,
evidence, where it would be fixed and how a fix is confirmed. No verdict. The
runner concatenates every room's report into `FINDINGS.md` and
`findings.json`. See [Reports](reports.md).

## What is code, and what is judgement

Anything a run's meaning depends on is code, not something an agent decides.

| Code guarantees | Why |
|---|---|
| The Prompt reaches the room verbatim | The operator knows the Must lists. Any paraphrase of the Prompt by the operator is a way for the answer to leak. |
| The room is isolated, and the audit checks it | A rule that rests on an agent keeping it is a rule nobody checked. |
| The user's files are set aside and put back | A run is done on the user's own machine. An exception, Ctrl-C and SIGTERM all unwind through the same `finally`. |
| Phase 1 does not change the room | Every file in the room is hashed before and after. Any difference cancels the room. |
| Screens open by declared name only | An agent that can write a file and run a script it names can run anything. |
| Evidence comes from tools | A report cites what a tool answered, not the room's account and not the operator's impression. |

What is left to the operator is what needs judgement:

- whether the screen it put up is the one the scenario describes
- whether each Must line was met, read from evidence
- which of the room's stumbles a product change would remove
- how severe each one is

## The loop

```
run → read FINDINGS.md → fix the product → run again → compare by id
```

A problem's **id** names the problem, not the run (`fn-f1-not-bound`, not
`room-3-issue`). A later run reports the same problem under the same id, so a
fix shows as an id that is gone. **Where it would be fixed** and **how a fix
is confirmed** are what the fixing step needs. Which problems to fix, and
whether a fix is taken, stay with the human.

## What it costs

Each room is two agent sessions: the room's and the operator's. On the toy
product that is a few cents. On a real product's task it is roughly
$0.5–2 per room, depending on the task and the models. Runs are started by a
person on purpose: they spend money, stand fixtures in for the user's files,
and may open windows.
