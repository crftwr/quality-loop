"""What a product supplies: its surface, its rooms' limits, its evidence.

A product subclasses `Adapter` and fills in what is its own. Everything else -
building rooms, isolating the session, the stand-in, the screens, the
operator, the audit, the findings - is the runner's and is the same for
every product.
"""

from __future__ import annotations

import contextlib
import pathlib
import sys

from quality_loop import audit, scenario, session, standin


class Adapter:
    """One product's half of a run.

    Attributes:
        name: The product's name, used in the run directory and messages.
        version: The product's version, which names the run directory.
        checkout: The product's repository.
        rooms: Where rooms are built. Inside the checkout is fine, because the
            session is `--restricted`; anywhere else in the checkout is refused.
        scenarios: The directory of scenario files.
        skill_name: The bundle's directory name inside a room.
        fixtures: The directory screens are served or copied from, or None.
        screens: ``{name: Page | Terminal}`` - all the operator may put up.
        evidence: ``{name: {"argv": [...], "help": "..."}}`` - commands that
            read, which the operator runs through its MCP server with
            arguments of its choosing and no shell.
        evidence_help: One paragraph on what those tools answer.
        python: The interpreter the operator's CLIs run under.
        bundle_place: The directory the bundle goes under in a room:
            ``skills`` for an agent-facing skill, ``docs`` for a manual.
        apps: ``{name: drive.TerminalApp | drive.DesktopApp}`` - the product's
            app, launched by the framework (see `quality_loop.drive`). The
            operator drives them in a scenario's live check.
        room_apps: Names from ``apps`` the room itself may drive, for a
            human-facing product whose UI is the surface under test. Empty
            for an agent-facing one: there, driving the app is for checking.
        default_variant: What the variant ``""`` is called on the command
            line (``--variant``), e.g. Keyhac's ``template`` config.
        parallel: How many rooms may run at once. 1, the default, is one
            after another, exactly as before parallel runs existed.
        resources: ``{resource: capacity}`` - what rooms share, and how many
            may hold each at once: a desktop's focus, the user's home.
    """
    name = "product"
    version = "0"
    checkout: pathlib.Path
    rooms: pathlib.Path
    scenarios: pathlib.Path
    skill_name = "product"
    fixtures: pathlib.Path | None = None
    screens: dict = {}
    evidence: dict = {}
    evidence_help = ""
    python = sys.executable
    bundle_place = "skills"
    apps: dict = {}
    room_apps: tuple = ()
    default_variant = ""
    parallel = 1
    resources: dict = {}

    def bundle(self) -> pathlib.Path:
        """The surface under test - a zip or a directory - built for this run."""
        raise NotImplementedError

    def rules(self) -> str:
        """RULES.md: what the room may read and what it must write down."""
        raise NotImplementedError

    def session(self, room: pathlib.Path) -> session.Session:
        """How the room's session is started: its tools, permissions, servers."""
        raise NotImplementedError

    def policy(self, room: pathlib.Path) -> audit.Policy:
        """What the audit flags for this product."""
        return audit.Policy(checkout=self.checkout)

    def product(self):
        """A context manager for the length of a run: the product up, if it
        has to be running for the room to use it."""
        return contextlib.nullcontext()

    def stand_in(self, case: scenario.Scenario, variant: str,
                 room: pathlib.Path) -> standin.StandIn | None:
        """The operator's files stood in for, for one room, or None."""
        return None

    def runs(self, cases: list[scenario.Scenario],
             named: bool = False) -> list[tuple[scenario.Scenario, str]]:
        """``(scenario, variant)`` pairs: the same scenario on several fixture
        configs is several rooms. The default is one room per scenario.

        ``named`` says the scenarios were picked by name rather than being
        every one there is - a product can leave out of a run of everything
        those that need a screen only the person running it can put up.
        """
        return [(case, "") for case in cases]

    def screen_backend(self) -> dict | None:
        """Where the declared screens are put up, when not on this desktop.

        ``{"path": file, "settings": {...}}``: a Python file with
        ``open_page``, ``open_terminal`` and ``close`` as in
        `quality_loop.screens`, and what its ``configure(settings)`` is given.
        Asked once per room, after the product is up, so settings may name
        where it runs this time. None, the default, is this OS's own backend.
        """
        return None

    def platform(self) -> str:
        """The OS the room's app runs on, as ``sys.platform`` names it - what
        the operator is told. Not this machine's when the product runs in a VM."""
        return sys.platform

    def alive(self) -> bool:
        """Whether the product is still answering, asked on the heartbeat."""
        return True

    def needs(self, case: scenario.Scenario, variant: str) -> set[str]:
        """The resources one room holds while it runs. The default is every
        declared resource, so declaring a resource without saying who needs
        it never lets two rooms share it."""
        return set(self.resources)

    def product_for(self, room: pathlib.Path):
        """A context manager for one room: a product instance of its own, for
        a product that can run one per room. None uses ``product()``'s."""
        return None

    def restore(self) -> list[str]:
        """Put back what a run that could not unwind left set aside - the
        stand-in's marker. One line per thing done."""
        raise NotImplementedError("this adapter does not say how to restore")
