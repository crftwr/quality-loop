"""A run of quality-loop against a human-facing terminal app and its manual.

    .venv/bin/python examples/tui/run.py        (needs quality-loop[tui])

The product is jot, a note list (`jot.py`), and its manual. No skill, no MCP,
no evidence tools: the room plays a first-time user with only the manual and
the app, which it drives through quality-loop's app tools; the operator
checks the notes file, the app's event log and, in a live check, the app
itself. This whole adapter is what a level-0/1 product needs.
"""

import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import quality_loop  # noqa: E402
from quality_loop import adapter, audit, drive, runner, session, standin  # noqa: E402

RULES = """\
# The rules you are under

You are a first-time user of jot, doing the task in TASK.md. You have its
manual, `./docs/jot/MANUAL.md`, and jot itself through the app tools
(app_start, app_keys, app_screen, app_stop). That is the whole of what you
know. Read the manual first.

**Forbidden:** any other file on this machine, and asking anyone anything.
Nobody will answer.

**When the manual does not tell you something, write it down and guess.**
Append a section to `./QUESTIONS.md` (it already exists; add to it, never
rewrite it):

```
## <what you needed to know>
Where you looked in the manual:
What you did instead:
```

That includes a key you tried because it usually works elsewhere.
"""

FIXTURE = "bread\nmilk\neggs\n"


class Jot(adapter.Adapter):
    name = "jot"
    version = quality_loop.__version__
    checkout = ROOT
    rooms = ROOT / "rooms"
    scenarios = HERE / "scenarios"
    skill_name = "jot"
    bundle_place = "docs"
    room_apps = ("jot",)

    def __init__(self):
        # The "user's" jot home, and where their notes wait during a room.
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="jot-home-"))
        (self.home / "notes.txt").write_text("my own notes\n")
        self.aside = pathlib.Path(tempfile.mkdtemp(prefix="jot-aside-"))
        self.apps = {"jot": drive.TerminalApp([sys.executable, str(HERE / "jot.py")],
                                              rows=20, cols=60,
                                              env={"JOT_HOME": str(self.home)})}

    def bundle(self):
        return HERE / "docs"

    def rules(self):
        return RULES

    def session(self, room):
        return session.Session(allow=["Read", "Glob", "Grep", "Write", "Edit", "TodoWrite"],
                               max_turns=40)

    def policy(self, room):
        return audit.Policy(checkout=self.checkout, forbidden={
            str(self.aside): "the user's own notes, set aside",
            str(self.home): "jot's data, which the room reaches only through jot"})

    def stand_in(self, case, variant, room):
        return standin.StandIn(home=self.home, marker=self.aside / "stand-in",
                               fixtures={"notes.txt": FIXTURE}, evidence=room / "evidence")

    def restore(self):
        return standin.restore(self.aside / "stand-in", self.home, ["notes.txt"])


if __name__ == "__main__":
    jot = Jot()
    runner.run(jot, sys.argv[1:] or None)
    print(f"  the user's notes afterwards: {(jot.home / 'notes.txt').read_text().strip()!r}")
