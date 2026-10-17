# Isolation and permissions

A run means something only if the room learned from the product's surface
alone, and the operator judged without touching what it judges. Every rule
here was paid for by a run of this harness or of the clean rooms it replaced.
Where that is so, the reason is given.

## The room

The room's session is started with these flags (`session.Session.command`):

| Flag | What it does | Why |
|---|---|---|
| `--restricted` | No CLAUDE.md discovery, no settings files, no skills from the checkout, no Bash | Measured: a session in a room inside the checkout, asked what project it is in and allowed to read nothing, names the product without the flag and answers UNKNOWN with it. Without Bash, the file tools' confinement to the working directories is real. A shell can `cat` its way out of any confinement. |
| `--add-dir` | The few directories outside the room it may reach | The task's own places, such as where an action is written and where its output goes. |
| `--mcp-config` + `--strict-mcp-config` | Exactly the product's servers | Whatever else the user has connected is not part of the product's interface. |
| `--settings` with `permissions.allow` + `--permission-mode dontAsk` | What is listed runs; the rest is refused | A `-p` session with no grant is refused every tool call. A first run reported, accurately and uselessly, that it could not write a file. |
| `--no-session-persistence` | The transcript is kept in the room only | |
| `-p` | Non-interactive | There is nobody to ask, so the only questions are the ones written into QUESTIONS.md. |

And in its environment:

- **`GIT_CEILING_DIRECTORIES`** at the room's parent. `git log` from a room
  inside the checkout answers "not a git repository", instead of reading
  history whose commit titles say what every change to the product was for.
  A clean room modelled on this one had a room run `git log` (crftwr/xefm#650).
- **stdin closed.** A `-p` session with an open stdin waits three seconds for
  piped input and writes a warning to the top of the transcript.

**The room may sit inside the checkout** (`cleanroom/`, gitignored), because
of `--restricted`. `room.build` refuses a room anywhere else in the checkout:
it would look deliberate and be protected by nothing. The room's own
`CLAUDE.md` is a canary. Only a session started *without* `--restricted`
reads it unasked, and it tells such a session to say so and stop.

**The transcript is written outside the room** and moved in at the end. One
room, left with its own log in reach, grepped it to reconstruct the task.

## The audit

`audit.audit(room, policy)` reads the transcript afterwards for the rules no
flag can enforce:

- **Where each tool call was pointed**, meaning the path-bearing fields of its
  input. It does not scan what the call typed or what came back. A room that
  reads a path off the screen and repeats it in its notes is doing its task.
- **A path under the checkout and outside the room** is a breach, in either
  spelling (`/Users/...`, `C:\Users\...`, `\Users\...`). Merely mentioning the
  checkout is not: every honest read of the bundle does.
- **Forbidden paths**: the installed package, the installed app, the user's
  set-aside files. **Other authors' files** in a directory the room may write
  to.
- **Every git call**: refused when git found no repository, a breach otherwise.
- **The init event**:
  - Bash present (when the room should have none) means `--restricted` did not
    take effect.
  - A checkout skill visible means the scoring key leaked.
  - A required MCP server not connected means the room measured the outage.
- **The canary phrase** in the room's reply.

**A refusal is not a breach.** A call the confinement turned down read
nothing. It is reported, as the confinement working in public. Only a call that
came back with something disqualifies a run.

## The operator

The operator has to read the checkout (the scenario, the fixtures, the
product's text) and the room's record. It must not change the room, and it
must not run anything the product did not declare.

| | |
|---|---|
| `--restricted --tools Read,Glob,Grep,Write,Edit` | No Bash. Claude Code lets read-only commands through regardless of the allow list. The first real operator ran `cd room; ls -la; cat QUESTIONS.md; ...`, and `cat` reads anywhere on the machine, while the file tools are confined. |
| One MCP server: quality-loop's own (`python -m quality_loop.mcp`) | Its tools are `screen_list`, `screen_open(name)`, `screen_close(id)` and `evidence(tool, args)`. They are the operator's only way to act. |
| Never the product's MCP | Checking the screen through the product under test is circular. A broken `list_windows` would hide a failed setup and be blamed on the product. |
| Writes: `Edit(//<its directory>/**)` and `Edit(//<room>/REPORT.md)` | Edit rules govern Write too. Absolute paths take Claude Code's `//` spelling, because a single `/` is relative to the settings file, and the first real run was refused every write. |
| `--session-id` in phase 1, `--resume` in phase 2 | The agent that judges the run is the one that set it up. |
| `OPERATOR.md` copied into its directory | The installed package is outside what it may read. The first operator on a real product never saw its job description, and wrote a verdict. |

**Phase 1 cannot change the room.** Every file in the room is hashed before
and after. A changed, added or removed byte cancels the room. `TASK.md` above
all has to reach the room exactly as the runner wrote it.

**Screens by name only.** `screen_open` takes a name from the adapter's
declarations, never a path, URL or script. Terminal scripts run from a copy.
An agent that can write a file and also run a script it names can run
anything.

**Evidence without a shell.** `evidence` runs a declared command with the
operator's arguments as a list. There is no shell, so nothing can be piped,
redirected or chained. What the arguments mean is the evidence tool's own
business, and an adapter declares only tools that read.

## The user's machine

Runs happen on the user's own machine, with their own files:

- Their files are moved into a marker directory and fixtures take their place.
  They come back in a `finally`. The runner turns SIGTERM into
  KeyboardInterrupt, so a killed run unwinds too.
- A marker still present at start means a run could not unwind. The next run
  refuses until `standin.restore` has put the files back.
- The marker must be out of the room's reach. The runner refuses a room
  otherwise.
- Copies of backups the product prunes wait in the marker, and any the room's
  writes pruned come back.
- An input file staged for a task never overwrites one of the user's. The run
  refuses instead.
- Screens left open are closed by the runner after phase 2. Only windows
  quality-loop opened are closed, by the handle it recorded. On macOS a
  Terminal window's own tty processes are ended first: otherwise Terminal
  answers a close with a confirmation sheet and the window stays.

## Known limits

- **The room knows where it is.** A room inside the checkout can see from its
  working directory that it sits under the product's project. It cannot read
  a byte of the checkout, and RULES.md forbids trying.
- **The audit sees where tools were pointed, not what they meant.** An MCP
  tool of the product's that reads files on the room's behalf is outside it.
  Such a tool is the product's interface, and what it hands back is the
  product's to answer for.
- **Evidence tools are trusted to only read.** Nothing enforces it.
- **Windows** screen backends (Edge, Windows Terminal, `EnumWindows`) have not
  yet been run on a Windows machine.
