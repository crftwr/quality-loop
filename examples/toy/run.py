"""A run of quality-loop against a product small enough to read in a minute.

    .venv/bin/python examples/toy/run.py

The product is a "greeter" skill: read the house style, write one file. It
has every part a real product's run has - a stand-in for the user's file,
a room confined to its bundle and one directory, a screen the operator puts
up and takes down, an evidence tool the operator calls - and costs a few
cents of model time, so the harness can be checked end to end cheaply.
"""

import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import quality_loop  # noqa: E402
from quality_loop import adapter, audit, runner, screens, session, standin  # noqa: E402

RULES = """\
# The rules you are under

You are doing the task in TASK.md using **only** the skill in `./skills`.
Read its `SKILL.md`. It is the whole of what you know.

GREETER_HOME is `{home}`.

**Allowed:** everything under `./skills`, and reading and writing in
GREETER_HOME as the skill says.

**Forbidden:** any other directory on this machine, and asking anyone
anything. Nobody will answer.

**When the skill does not tell you something, write it down and guess.**
Append a section to `./QUESTIONS.md` (it already exists; add to it, never
rewrite it):

```
## <what you needed to know>
Where you looked in the skill:
What you did instead:
```

Then finish the task with your best reading.
"""


class Toy(adapter.Adapter):
    name = "toy"
    version = quality_loop.__version__
    checkout = ROOT
    rooms = ROOT / "rooms"
    scenarios = HERE / "scenarios"
    skill_name = "greeter"
    fixtures = HERE / "fixtures"
    screens = {"notice": screens.Page("notice.html", title="Toy notice")}
    python = sys.executable

    def __init__(self):
        # The "user's" greeter home, with a style of their own that the run
        # must set aside and put back.
        self.home = pathlib.Path(tempfile.mkdtemp(prefix="toy-greeter-home-"))
        (self.home / "out").mkdir()
        (self.home / "style.txt").write_text("plain\n")
        # Where their file waits while the fixture stands in: beside the home,
        # never inside it, where the room would find a second style.txt.
        self.aside = pathlib.Path(tempfile.mkdtemp(prefix="toy-greeter-aside-"))
        self.evidence = {"greeter": {
            "argv": [sys.executable, str(HERE / "evidence.py")],
            "help": "greeting <room>: the room's greeting against the house style"}}
        self.evidence_help = ("`greeter` with args [\"greeting\", <room>] says what greeting the "
                              "room left, the style it ran under, whether style.txt "
                              "is unchanged, and whether the greeting matches.")

    def bundle(self):
        return HERE / "skill"

    def rules(self):
        return RULES.format(home=self.home)

    def session(self, room):
        return session.Session(allow=["Read", "Glob", "Grep", "Write", "Edit", "TodoWrite"],
                               add_dirs=[self.home], max_turns=20)

    def policy(self, room):
        return audit.Policy(checkout=self.checkout, forbidden={
            str(self.aside): "the user's own style, set aside"})

    def stand_in(self, case, variant, room):
        return standin.StandIn(
            home=self.home, marker=self.aside / "quality-loop-stand-in",
            fixtures={"style.txt": "uppercase\n"}, evidence=room / "evidence",
            watch=[standin.Watch(self.home / "out", "out")])


if __name__ == "__main__":
    toy = Toy()
    runner.run(toy, sys.argv[1:] or None)
    print(f"  the user's style.txt afterwards: {(toy.home / 'style.txt').read_text().strip()!r}")
