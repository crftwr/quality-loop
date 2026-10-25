# Writing an adapter

An adapter is the product's half of a run. Subclass `quality_loop.adapter.Adapter`,
fill in what is the product's own, and hand an instance to
`quality_loop.runner.run` (or name it in `qa/quality-loop.toml` for the
command line). Everything else is the runner's: building rooms, isolating
sessions, the stand-in, screens, driving the app, the operator, the audit and
the findings.

`examples/toy/run.py` is a complete adapter for a skill in about 100 lines,
and `examples/tui/run.py` one for a terminal app and its manual, with no MCP
and no evidence tools. [Keyhac's `qa/run.py`](https://github.com/crftwr/keyhac/blob/main/qa/run.py)
is a real one: a product with a daemon, an MCP endpoint, screens and evidence
tools of its own.

`qa/quality-loop.toml` names the adapter for the command line
(`adapter = "qa/run.py:Product"`); see [Running the loop](running.md).

```python
from quality_loop import adapter, audit, runner, screens, session, standin

class Product(adapter.Adapter):
    name = "product"
    version = product.__version__
    checkout = ROOT                       # the product's repository
    rooms = ROOT / "cleanroom"            # gitignored; rooms are built here
    scenarios = ROOT / "qa" / "scenarios"
    skill_name = "product"                # the bundle's directory in a room
    fixtures = ROOT / "qa" / "fixtures"   # pages and terminal scripts
    screens = {...}
    evidence = {...}
    evidence_help = "..."

    def bundle(self): ...
    def rules(self): ...
    def session(self, room): ...

runner.run(Product(), names=None)        # or ["11", "12"]
```

## Required

**`bundle()`** returns the surface under test, built for this run: a zip, as a
user downloads it, or a directory. Build it here, not ahead of time. A stale
bundle on disk tests last version's skill and reports its gaps as this
version's.

**`rules()`** returns `RULES.md` for the room. It says what the room may read
and use, what it may not, and how to record a guess in `QUESTIONS.md` (append a
section, never rewrite the file). Say what the product's own tools are
(allowed, because they are the product's interface) and what is forbidden
(the checkout, the installed package, other people's work). Then say it again
plainly: asking anyone is forbidden, and nobody will answer.

**`session(room)`** returns a `quality_loop.session.Session`: what the room's
session may use.

```python
session.Session(
    allow=["Read", "Glob", "Grep", "Write", "Edit", "TodoWrite", "mcp__product"],
    add_dirs=[EXTENSIONS, DESKTOP],          # outside the room, reachable
    mcp_servers={"product": {"command": bridge}},
    tools=None,                              # None: --restricted's default, no Bash
    env={},                                  # e.g. a PATH shim for a CLI product
    max_turns=150)
```

A product whose surface is a CLI grants a narrowed Bash with `tools=[...,
"Bash"]` and `allow=["Bash(product ext:*)", ...]`. Read
[Isolation](isolation.md) first: Claude Code lets read-only shell commands
through whatever the allow list says.

## The least a product needs

A product with no skill, no MCP and no evidence tools is measured against its
manual, with the framework driving its app:

```python
class Jot(adapter.Adapter):
    bundle_place = "docs"                    # the room gets docs/<skill_name>
    room_apps = ("jot",)                     # the UI is the surface: the room drives it
    apps = {"jot": drive.TerminalApp([sys.executable, "jot.py"], rows=20, cols=60,
                                     env={"JOT_HOME": str(HOME)})}

    def bundle(self): return DOCS
    def rules(self): return RULES
    def session(self, room): return session.Session(allow=["Read", "Glob", "Grep"])
    def stand_in(self, case, variant, room):
        return standin.StandIn(home=HOME, marker=ASIDE / "stand-in",
                               fixtures={"notes.txt": FIXTURE}, evidence=room / "evidence")
```

What the product has to allow is in [Concepts](concepts.md#what-a-product-has-to-give):
a launch command, a redirected home, and for a desktop app a window title.

## Apps

**`apps`** declares the product's app by name, for the framework to drive
(`quality_loop.drive`):

- **`drive.TerminalApp(argv, rows=40, cols=120, env={}, cwd=None)`** runs
  under a pseudo-terminal of that size, with a terminal emulator kept in
  step, so its screen is read as text and keys go in as an xterm sends them.
  Nothing on the desktop, nothing the person at the machine can disturb.
  A lone Esc is followed by a short pause, and the app gets `ESCDELAY=25`:
  a terminal app cannot otherwise tell Esc-then-a-key from Alt+that key.
  Needs `quality-loop[tui]`; macOS and Linux.
- **`drive.DesktopApp(argv, title, env={}, cwd=None, patience=20, quit=None)`**
  is launched and recognised by its window title, driven with synthetic keys
  (`CGEventPost` on macOS, `SendInput` on Windows) and read by screenshot.
  Before every key the frontmost window is checked, and a key that would land
  elsewhere is not sent. Text goes in as Unicode, unaffected by the layout
  and the IME; shortcuts as virtual keys. `quit` is the keys that quit it;
  otherwise the process is terminated.

Who drives them:

- **The operator**, in a scenario's **Live check**, after the room has
  finished and before the user's files go back. The steps land in the room's
  `evidence/live/`.
- **The room**, for the names in **`room_apps`**: a human-facing product,
  whose UI is the surface under test. The room's session gets one more MCP
  server, `app`, with the app tools only; its steps are kept outside the room
  while it runs and land in `evidence/app/` afterwards.

Every step is a line of `steps.jsonl`: the keys, the agent's stated intent,
how long the screen took to settle, the screen file it left, and the event
log's lines since the step before. A key remapper running (Keyhac,
Karabiner, AutoHotkey) is warned about: it rewrites synthetic keys too.

**The event log.** Every app is started with `QUALITY_LOOP_EVENTS=<path>`. A
product that writes JSON lines there - one object per fact, at its own API
boundary - is at level 1:

```json
{"kind": "prompt", "text": "Delete 3 files?"}
{"kind": "message", "text": "Saved"}
{"kind": "exception", "type": "KeyError", "where": "ext/trip.py:12"}
{"kind": "launched", "argv": ["open", "/tmp/x.pdf"]}
```

The kinds are the product's own; these are the useful ones. Write nothing
when the variable is unset.

## Optional

**`policy(room)`** returns the `audit.Policy` the transcript is checked
against:

```python
audit.Policy(
    checkout=ROOT,
    forbidden={"site-packages/product": "the installed package",
               str(STAND_IN): "the user's own files, set aside"},
    foreign={"theirs.py"},          # other authors' files the room must not read
    servers=("product",),           # MCP servers that must be connected
    leaked_skill=lambda c: "product" in c,   # the checkout's own skills
    bash=False)                     # True when the room has Bash on purpose
```

**`product()`** is a context manager for the whole run: the product up, if a
room needs it running. Keyhac's starts its daemon with the MCP endpoint on
when none is answering, and quits it at the end. One that is already running
is the user's, and is used and left alone.

**`alive()`** is asked on the room's heartbeat. Two misses in a row end the
room: a room that cannot reach the product measures the outage.

**`stand_in(case, variant, room)`** returns a `standin.StandIn`, or None. Use
it when the task edits the user's files:

```python
standin.StandIn(
    home=PRODUCT_HOME,                       # where the stood-in files live
    marker=PRODUCT_HOME / "stand-in",        # where the user's originals wait
    fixtures={"config.py": fixture_text},
    evidence=room / "evidence",
    backups="config.py.bak-*",               # the product's own backups, kept
    watch=[standin.Watch(EXTENSIONS, "extensions"),
           standin.Watch(DESKTOP, "desktop"),
           standin.Watch(PRODUCT_HOME, "home", skip=("endpoint.json",))],
    staged=[(FIXTURES / "input.csv", DESKTOP / "input.csv")],
    on_change=reload)                        # after swapping in, and back
```

- The **marker must be out of the room's reach**. The runner refuses a room
  whose marker is inside the room or any of its `add_dirs`. The first toy run
  put it inside the one directory the room could write to, and the room found
  a second `style.txt` there.
- **Everything new** in a watched directory moves into the room's evidence,
  not only what the task asked for. `skip` names the product's own state
  files, which moving would break.
- The user's originals come back in a `finally`. A marker left behind by a run
  that could not unwind refuses the next run. `standin.restore()` puts it back.
- Fixtures are written with LF on every OS. The evidence keeps both versions,
  as `evidence/before/<name>` and `evidence/after/<name>`.

**`runs(cases, named)`** returns `(scenario, variant)` pairs. The default is
one room per scenario. Keyhac leaves a scenario with `needs` out unless it was
named. Variants are the product's own idea: whatever a room's label should
carry besides the scenario's name.
**`default_variant`** is what the unnamed variant `""` is called on the
command line, so `--variant template` can pick it.

**`restore()`** puts back what a run that could not unwind left set aside,
for `quality-loop restore`. Usually one call to `standin.restore`.

**`parallel`, `resources`, `needs(case, variant)`, `product_for(room)`** let
rooms run side by side. Declaring none of them keeps one room at a time; see
[Running the loop](running.md#parallel-runs).

## Screens

The operator can put up only what the adapter declares, by name:

```python
screens = {
    "approval-queue": screens.Page("dialog.html", title="Queue — confirm each item"),
    "deploy": screens.Terminal("deploy.py", title="deploy - acme"),
}
```

- **`Page`** is an HTML file under `fixtures`. The runner serves it over a
  local HTTP origin, from a copy outside the checkout, so the address bar does
  not tell the room where the source is. A page reports what was done on it
  by POSTing JSON to `event`. That record is written to
  `evidence/screen-events.jsonl`.
- **`Terminal`** is a **Python** script under `fixtures`, run with the
  adapter's `python` from a copy, in a terminal window of its own. Python
  means one script serves both OSes. The window runs a fixed shell (bash
  without startup files on macOS, PowerShell `-NoProfile` on Windows) and
  stays open after the script ends, so the output is still there to read.
- **`title`** is how the window is recognised, on both OSes, with the OS's own
  window list. Use the page's `<title>`, and a title of your own for a
  terminal.

**Somewhere else than this desktop.** A product whose app runs in a VM puts
its screens there too, with **`screen_backend()`**. It returns
`{"path": file, "settings": {...}}` for one room, or None (the default) for
this OS's own backend:

- **The file** is a Python file in the product's checkout. It answers what
  this OS's module answers: `open_page(url, title, patience)`,
  `open_terminal(command, title, patience)` and `close(kind, handle)`.
  `configure(settings)` is called first, if the file has it.
- **When it is asked:** once per room, after the product is up. So the
  settings can name where the product runs this time, such as a VM clone's
  address.
- **Who uses it:** the operator's `screen_open` and `screen_close`, and the
  runner's sweep of what was left open.
- **What it is handed:** the page's URL and the terminal's command line as
  they are on this machine. Reaching that origin from the VM, and running
  the script there, is the backend's work.

**`platform()`** names the OS the room's app runs on, as `sys.platform`
does. The operator is told it in phase 1. It defaults to this machine's, so
override it along with `screen_backend()`.

## Evidence tools

Commands the operator runs to check a Must line, declared by name:

```python
evidence = {"product": {
    "argv": [sys.executable, str(ROOT / "qa" / "evidence.py")],
    "help": "replay | bindings | preserved | calls | events"}}
evidence_help = "One paragraph: what each subcommand answers, and the names to use."
```

The operator calls them as `evidence(tool="product", args=[...])` through
quality-loop's MCP server. There is no shell, so arguments arrive as a list,
verbatim.

- **An evidence tool only reads.** That is the adapter's promise, and the
  reason the operator may pass arguments of its choosing.
- **Answer facts, as JSON.** "What the focused application received:
  `Cmd-S`" beats a stream of key-down/key-up edges the operator has to
  interpret. A tool that answers the question directly is cited correctly.
- **Read the run's evidence.** That means `room/evidence/`,
  `room/transcript.jsonl`, the screen events and the live check's record.
  Never read the live machine, which has already been put back. Driving the
  live app is the live check's job, not an evidence tool's.
- **Write ground truth out by hand.** A check that reads its expectations from
  the page it is checking would agree with any page, including a broken one.
- Start with `--help`. The operator is told to call each tool with `--help`
  first.

Keyhac's `qa/evidence.py` is the worked example. Its `replay` loads the
room's config in Keyhac's own engine, presses keys through the fake hook, and
answers what the focused application received.

## Running it

```
quality-loop run 11 --variant short          # in the background; prints the run's id
quality-loop run 11 --foreground             # attached
```

or from Python:

```python
from quality_loop import runner
findings = runner.run(Product(), names=["11"], model=None, operator_model=None,
                      variants=None, parallel=None, known=None)
```

`names` picks scenarios by number or name. None means every scenario the
adapter's `runs()` keeps. SIGTERM unwinds like Ctrl-C, so the stand-in still
puts the user's files back. The result is `FINDINGS.md` and `findings.json` in
`rooms/<version>-<time>/`, beside `run.log` and `status.json`. Each room's
directory sits beside them, with `<room>.operator/` holding the operator's
notes and transcripts and `<room>.log` the room's own lines.

Give the product a make target (Keyhac: `make qa CASE=11 CONFIGS=short`).
Runs are authorized by a person, never started by a hook or CI: they cost
model time, swap the user's files, open windows and send keys.
