# Concepts

## What is being measured

Not whether a model can do the task. The question is whether **what the
product gives its users** lets them do it: for an agent-facing product the
skill bundle, the tool descriptions, the error messages; for a human-facing
one the manual and the UI itself. A model working from inside the product's
repository can read the source and the design notes. It will succeed where a
user fails, and nobody learns why.

So the agent doing the task is given what a user would have, and nothing
more. Every place it has to guess is a gap in the product, whether or not it
guessed right. **The failures are the product of a run.** A run that goes
perfectly and records nothing has told you little.

| | Agent-facing | Human-facing |
|---|---|---|
| The bundle | A skill, tool descriptions | A manual, a README, help |
| The surface | MCP, a CLI | The UI, driven with keys and read off the screen |
| The room plays | A user's agent | A first-time user with only the docs |

For a human-facing product the app tools are the surface, so the room gets
them. For an agent-facing one they stay with the checking side.

**Be honest about the limits.** An LLM is not a human tester. It reads long
docs to the end, keeps going where a person would give up, guesses from
training (vim keys, the usual shortcut) where the docs fall short, and does
not perceive contrast or a confusing layout. What a run gives a human-facing
product is **consistency between the docs and the behaviour, plus friction an
agent observed**, not a substitute for usability testing. Requiring every
guess to be written to QUESTIONS.md keeps the trained-in guesses visible as
gaps in the docs.

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

**Operator.** A second Claude Code session, one per room, in phases of one
conversation. Phase 1 puts the screen up. If the scenario has a **Live check**,
the operator then drives the real app, with what the room made still in
place, and every key and screen is recorded. Phase 2 runs after the runner
has collected and audited. It reads the record, checks each Must line with
evidence, and writes `REPORT.md`. It judges the run. It never does the task,
and it never touches the room before or during it.

**Conductor.** A third agent, above the other two: a Claude Code session in
the product's repository that plans with a person, runs, files findings as
Issues, fixes what the person chooses and retests. It knows everything the
tiers below must not, which is why what reaches them is code. See
[Running the loop](running.md).

**Adapter.** The product's half: how its bundle is built, what a room may
reach, which of the user's files are stood in for, which screens and apps
exist, and which evidence answers questions about a run. See
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
| Evidence comes from the record | A report cites what a tool answered, a transcript step, or a recorded live step and its screen - not the room's account and not the operator's impression. |
| Live driving is recorded | Every key the operator or the room sends is written down with its intent, the wait and the screen after. Keys go only to the app's own window, checked before every key. |
| Known problems reach the operator as ids | Id and title, never a status: an expectation biases the judge. |

What is left to the operator is what needs judgement:

- whether the screen it put up is the one the scenario describes
- whether each Must line was met, read from evidence
- which of the room's stumbles a product change would remove
- how severe each one is

## What a product has to give

| | |
|---|---|
| **Practically required** | It can be launched (and quit) by a command. Its config and data location can be redirected - an environment variable, an argument, a home directory - so fixtures stand in and the user's real data is never touched. This is the requirement that matters for safety. A desktop app's window can be recognised by its title. |
| **Level 0** | Nothing more. Judged from the transcript, the stood-in files' diff and the screen, as text or an image. |
| **Level 1: an event log** | When `QUALITY_LOOP_EVENTS=<path>` is set, the app writes JSON lines at its API boundary: prompts shown, messages, exceptions, programs launched. A few lines of hooks, far lighter than an evidence tool, and it turns "what the screenshot seems to show" into facts. |
| **Level 2: evidence tools** | Commands of the product's own that answer questions about a run. Keyhac's `replay` is the example. |
| **Nice to have** | First-run rituals (wizards, sign-in, update checks, consent) that can be skipped; `--version`; no network, or a test endpoint; a terminal variant of a GUI. |

OS permissions (Accessibility, Screen Recording) belong to whatever runs
quality-loop, not to the product.

## The loop

```
run → read the findings → fix the product → run again → compare by id
```

The loop's use is **discovery**: each run should surface problems the last
did not. A run need not be deterministic, as long as it leaves enough record
to reproduce what it found - the starting point, every step with its intent,
and what was seen. A development-time agent can then rebuild the start,
follow the steps, stop where the screen diverges, and write a regression
test. quality-loop finds; development-time agents reproduce and fix.

A problem's **id** names the problem, not the run (`fn-f1-not-bound`, not
`room-3-issue`). A later run reports the same problem under the same id. Ids
are how findings are **de-duplicated across runs**, and how a problem that is
gone, or comes back, is noticed at all. Which problems to fix, and whether a
fix is taken, stay with the human - or with the conductor, as far as the
person's policy lets it.

## What it costs

Each room is two agent sessions: the room's and the operator's. On the toy
product that is a few cents. On a real product's task it is roughly
$0.5–2 per room, depending on the task and the models. Runs are **authorized
by a person**, directly or through the conductor's written policy, never by a
hook or CI: they spend money, stand fixtures in for the user's files, open
windows and send keys.
