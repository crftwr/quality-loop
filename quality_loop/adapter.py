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

    def alive(self) -> bool:
        """Whether the product is still answering, asked on the heartbeat."""
        return True
