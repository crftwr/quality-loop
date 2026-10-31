# Running the loop

## Setting a product up

```
pip install quality-loop      # into the product's own venv, ideally
quality-loop init             # in the product's checkout
```

**Where to install it.** The product's local venv is the recommended place:
the adapter can then import the product, as Keyhac's does. A shared
installation used across several projects also works, but then the adapter is
imported by that installation's Python and must not import the product (read
its version from a command instead). A product pinned to a Python older than
3.11 falls into the shared case.

**`quality-loop init`** does the parts that must not depend on an agent's
reading, and does them the same way every time:

- copies the conductor's skill into `.claude/skills/quality-loop/`, stamped
  with the package's version. Project level, committed, so collaborators
  share it. Whether a user-level skill reaches a room under `--restricted` has
  not been measured, so `init` warns about one, and the audit treats a
  `quality-loop` skill visible to a room as a leaked scoring key;
- writes `qa/quality-loop.toml`, naming the quality-loop command it was run
  as, so the conductor uses the same installation;
- adds the rooms directory to `.gitignore`.

It does not write the adapter, the scenarios or `qa/PLAN.md`. That is
judgement: ask Claude Code, in the checkout, to set quality-loop up. The
skill reads what it can, asks the person a few rounds of questions, proposes
a plan, and writes the adapter and draft scenarios for the person to accept.

`quality-loop init --upgrade` replaces the skill with the installed
package's. A copy edited by hand is shown as a diff and left alone unless
`--force`; what is particular to a product belongs in `qa/PLAN.md`. The
conductor compares the skill's stamped version with `quality-loop --version`
when it starts.

```toml
# qa/quality-loop.toml
command = ".venv/bin/quality-loop"
command_windows = ".venv/Scripts/quality-loop.exe"   # when the venv is in the checkout
adapter = "qa/run.py:Product"
rooms = "rooms"
```

## The commands

```
quality-loop run [scenarios...] [--variant V] [--parallel N] [--known FILE]
quality-loop status [<run>] [--json]
quality-loop watch [<run>]
quality-loop findings [<run>] [--since <run>] [--json]
quality-loop cancel [<run>]
quality-loop restore
quality-loop check
```

`<run>` is a run directory or its name; left out, the latest run.

**`run`** starts a run in a process of its own and prints its id at once.
`--foreground` runs it attached instead, which is what a make target wants.
Scenarios are picked by number or name; `--variant` keeps only those variants
(the adapter's `default_variant` names the unnamed one).

**`check`** parses every scenario, checks that every declared screen's file
is in the fixtures, warns about a backticked name in a Screen section that no
screen is declared as, and refuses a Live check when no app is declared.

**`restore`** asks the adapter to put back what a run that could not unwind
set aside. A run that was cancelled normally needs none.

## Watching a run

Everything a run says goes to `run.log` in its directory, flushed per line,
and its state to `status.json` beside it:

```json
{"run": "1.4.0-20261018-101500", "state": "running", "pid": 4242, "cost_usd": 0.41,
 "rooms": {"11_f1_off_in_vscode": {"phase": "room", "started": "...",
           "cost_usd": 0.12, "last_activity": "...", "thinking": true,
           "quiet_seconds": 40}}}
```

A room's phase is `waiting`, `operator-1`, `room`, `live-check`,
`collecting`, `operator-2`, `done` or `cancelled`. `thinking` means the
session has been quiet but is alive; a `running` run whose process is gone
was killed, and `status` and `watch` say so.

`quality-loop watch` prints the summary at every change and the log as it
grows. With no run named it follows the latest, and moves on to the next one
when it starts, so it can be left open across a loop of runs.

Both files sit in the run's directory, outside every room. The audit treats a
room's reach into that directory - its log, its status, a sibling room, an
operator's notes - as a breach.

**Cancelling.** `quality-loop cancel` sends SIGTERM (CTRL_BREAK on Windows),
which the run turns into the same unwinding as Ctrl-C: every room in
progress is collected, the user's files go back, and the findings so far are
written. Never stop a run harder than that.

**Sleep.** A run holds off this machine's idle sleep while it goes
(`caffeinate -i` on macOS, `SetThreadExecutionState` on Windows) and says so
in its log (`awake:`); a machine left alone during a run would otherwise
sleep through it, a VM guest with it. The display may still sleep, and
closing a laptop's lid still sleeps the machine.

## Parallel runs

By default rooms run one after another. An adapter that can do better says
so:

```python
class Product(adapter.Adapter):
    parallel = 4                                   # rooms at once
    resources = {"desktop": 1, "user-home": 1}     # resource -> capacity

    def needs(self, case, variant):                # what one room holds
        return {"desktop"} if case.meta.get("screen") else set()

    def product_for(self, room):                   # optional: one product per room
        return ProductInstance(room)
```

What limits parallelism is what rooms would share, not how many apps can
start:

| Resource | Why it is shared | Side by side when |
|---|---|---|
| The stand-in | Swaps the user's files in their home | The product's home can be redirected per room |
| The desktop | Synthetic keys and screens go to the focused window | Never, on one desktop |
| A product daemon | `product()` brings up one for the run | The product can run one per room (`product_for`) |
| A pty, a cloud API | Nothing | Always |

- Declaring nothing means `parallel = 1`: exactly the behaviour before.
- `needs` defaults to every declared resource, so declaring a resource never
  lets two rooms share it by accident.
- `--parallel N` on the command line lowers or raises the limit for one run;
  the resources still apply.
- Rooms side by side must not share an `add_dirs` directory, and no room may
  reach another's stand-in marker. The runner refuses the second room.
- Each room logs to `<room>.log` beside it, and `run.log` prefixes each line
  with the room's name.
- A room that fails with an error gets a harness report (`room-failed`) and
  the others go on. A stand-in marker left behind, or a product that has
  gone, stops the run: the rooms already running are unwound.

## Comparing runs

```
quality-loop findings                 # the latest run against the one before
quality-loop findings <run> --since <earlier run>
```

By room and id:

- **new**: never seen in that room before;
- **still there**: in the run compared with too;
- **gone**: in the run compared with, not in this one, for a room this run
  ran (a room it did not run says nothing);
- **back**: not in the run compared with, but in an earlier one.

Runs are not deterministic. "Gone" is not yet proof of a fix: how many clean
runs it takes depends on how reliably the problem appeared before.

## Known problems

```
quality-loop run 11 --known known.json
```

```json
[{"id": "fn-f1-not-bound", "title": "F1 binding misses Fn+F1", "room": "11_f1_off_in_vscode"}]
```

Each room's operator gets the entries for its room, its scenario, or none in
particular - id and title, never a status. It reuses those ids when it sees a
problem again, and spends its attention on what is not on the list.
"It should be fixed now" is never said: an expectation biases a judge.

## The conductor

The conductor is a Claude Code session in the product's repository, with the
skill `init` installed. It is the third tier:

| Tier | Knows | Does |
|---|---|---|
| room | What the product gives its users | Does the task |
| operator | The record, the Must lists, the evidence tools | Judges the room's run |
| conductor | Everything: past findings, fixes, the source, the person's intent | Plans, runs, files, fixes, iterates |

**The information boundary is code where it can be.** The conductor never
writes in a room: it calls `quality-loop run` with scenario names, and the
runner copies the Prompt verbatim. It reaches the operator only through
`--known`, which carries ids and titles and nothing else. Must lines are the
person's, changed only when they accept a proposal. The operator keeps no
shell and no product MCP whatever the conductor does.

**GitHub Issues are the ledger.** Each finding's id is the first line of its
Issue's body (`quality-loop id: <id>`), which is how the conductor
de-duplicates. Labels: `quality-loop:finding`, `quality-loop:<severity>`,
`quality-loop:<kind>`. A person triages with labels and comments, which is
also how they talk to the conductor between sessions. `harness` findings go
to quality-loop's repository; `out of scope` is not filed.

**The policy** - the goal, the scenarios, when to stop, what needs asking,
where runs may happen - is set in conversation and written down, in a
tracking Issue labelled `quality-loop:loop` or in `qa/LOOP.md`. The defaults
are conservative: filing, fixing, opening a PR, closing an Issue and
accepting a scenario all ask, and pushing to the default branch or releasing
always ask unless the policy explicitly allows them.

**Runs are authorized by a person**, through the policy. They cost model
time, swap the user's files, open windows and send keys. Unattended loops
belong on a dedicated VM or user account, where none of that can disturb
anyone; on the person's own machine, the person stays present.

**Fixes by the conductor** are PRs reviewed by a person, one finding each,
naming the Issue, the id and what the reproduction showed. A scenario and its
Must lines never change in the same PR as the fix that makes them pass: the
temptation is to change docs until the operator stops complaining, which
tunes the product to an LLM rather than to its users.

**The skill is written for the common Agent Skills format**, with no Claude
Code-specific tool names; the commands are a CLI anyone can type. For now
the conductor, the room and the operator all assume Claude Code.
