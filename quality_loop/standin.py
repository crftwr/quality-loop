"""Standing fixtures in for the operator's own files, and putting them back.

A task that edits the product's configuration has to edit a known file, and
must not edit the operator's. So for the length of a room their files are
moved into a marker directory, fixtures take their place, and everything is
put back on the way out - whatever ends the run. An exception, Ctrl-C and
SIGTERM (turned into KeyboardInterrupt by the runner) all unwind through the
same ``finally``. A marker left by a run that could not unwind refuses the
next one until `restore` has put it back.

Everything new in the directories the room can write to moves into the room's
evidence on the way out, not only the files it was asked for: a state file, a
helper package, a backup. Left behind, the next room finds them, and a product
that loads every module in its extensions directory shows them to the user.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import shutil
from typing import Callable


class StandInError(Exception):
    """The run cannot start without risking the operator's files."""


@dataclasses.dataclass
class Watch:
    """A directory the room can write to.

    Attributes:
        directory: The directory.
        label: Where its new entries go under the evidence directory.
        move: Move new entries into evidence (True), or copy them and leave
            them (False - for the operator who asked to keep what a run made).
        skip: Name prefixes that are never collected: the product's own state
            beside the files, which moving would break (an endpoint file, a
            settings file).
    """
    directory: pathlib.Path
    label: str
    move: bool = True
    skip: tuple[str, ...] = ()


def _entries(directory: pathlib.Path) -> set[str]:
    return {p.name for p in directory.iterdir()} if directory.is_dir() else set()


@dataclasses.dataclass
class StandIn:
    """The operator's machine made into the room's starting state, and given back.

    Attributes:
        home: The product's data directory, where the stood-in files live.
        marker: Where the operator's originals wait. Its existence at start
            means a run ended without putting them back.
        fixtures: ``{file name in home: the fixture's text}``.
        evidence: The room's evidence directory.
        backups: A glob, in ``home``, of backups the product keeps of those
            files and prunes. Copies wait in the marker, and any the room's
            writes pruned come back.
        watch: Directories whose new entries are collected.
        staged: ``(source, destination)`` input files a task works from. A
            destination that already exists refuses the run rather than being
            overwritten.
        on_change: Called after the fixtures go in and after the originals
            come back - a reload, so the running product follows the file.
            What it returns is reported if it says something went wrong.
    """
    home: pathlib.Path
    marker: pathlib.Path
    fixtures: dict[str, str]
    evidence: pathlib.Path
    backups: str | None = None
    watch: list[Watch] = dataclasses.field(default_factory=list)
    staged: list[tuple[pathlib.Path, pathlib.Path]] = dataclasses.field(default_factory=list)
    on_change: Callable[[], object] | None = None

    def __enter__(self) -> "StandIn":
        if self.marker.exists():
            raise StandInError(
                f"{self.marker} exists: a run ended without putting the operator's "
                f"files back. Check that what is in it is theirs, then restore it.")
        for _source, destination in self.staged:
            if destination.exists():
                raise StandInError(
                    f"{destination} already exists, and this run puts its own file "
                    f"there. Move it out of the way first.")
        self._before = {str(w.directory): _entries(w.directory) for w in self.watch}
        self.marker.mkdir(parents=True)
        self._had = {}
        for name, text in self.fixtures.items():
            own = self.home / name
            self._had[name] = own.exists()
            if own.exists():
                os.replace(own, self.marker / name)
            # LF on every OS: a fixture compared line by line with what the
            # room left must not differ in its line ends alone.
            own.write_text(text, encoding="utf-8", newline="\n")
        if self.backups:
            for backup in self.home.glob(self.backups):
                shutil.copy2(backup, self.marker / backup.name)
        for source, destination in self.staged:
            shutil.copy2(source, destination)
        if self.on_change:
            self.on_change()
        return self

    def __exit__(self, *exc) -> bool:
        try:
            self.collect()
        finally:
            self.give_back()
        return False

    def collect(self) -> None:
        """Move everything the run made into the evidence."""
        before_dir, after_dir = self.evidence / "before", self.evidence / "after"
        before_dir.mkdir(parents=True, exist_ok=True)
        after_dir.mkdir(parents=True, exist_ok=True)
        for name, text in self.fixtures.items():
            (before_dir / name).write_text(text, encoding="utf-8", newline="\n")
            if (self.home / name).exists():
                shutil.copy2(self.home / name, after_dir / name)
        for watch in self.watch:
            before = self._before.get(str(watch.directory), set())
            for entry in sorted(_entries(watch.directory) - before):
                if watch.directory == self.home and (
                        entry in self.fixtures or entry == self.marker.name):
                    continue
                if watch.skip and entry.startswith(watch.skip):
                    continue
                if entry == "__pycache__":
                    shutil.rmtree(watch.directory / entry, ignore_errors=True)
                    continue
                source = watch.directory / entry
                target = self.evidence / watch.label / entry
                target.parent.mkdir(parents=True, exist_ok=True)
                if watch.move:
                    shutil.move(str(source), target)
                elif source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)

    def give_back(self) -> None:
        """Put the operator's files back."""
        for name, had in self._had.items():
            if had:
                os.replace(self.marker / name, self.home / name)
            else:
                (self.home / name).unlink(missing_ok=True)
        _return_backups(self.marker, self.home)
        shutil.rmtree(self.marker, ignore_errors=True)
        if self.on_change:
            self.on_change()


def _return_backups(marker: pathlib.Path, home: pathlib.Path) -> None:
    for kept in marker.iterdir() if marker.is_dir() else ():
        if kept.is_file() and not (home / kept.name).exists():
            os.replace(kept, home / kept.name)


def restore(marker: pathlib.Path, home: pathlib.Path, names: list[str],
            on_change: Callable[[], object] | None = None) -> list[str]:
    """Put back what a run that could not unwind left in ``marker``.

    A fixture still in place is moved aside to ``<name>.quality-loop-fixture``
    rather than deleted. Returns what it did, one line each.
    """
    done = []
    if not marker.exists():
        return ["nothing to restore"]
    for name in names:
        saved = marker / name
        if not saved.exists():
            continue
        if (home / name).exists():
            aside = home / f"{name}.quality-loop-fixture"
            os.replace(home / name, aside)
            done.append(f"moved the fixture aside to {aside}")
        os.replace(saved, home / name)
        done.append(f"restored {home / name}")
    _return_backups(marker, home)
    shutil.rmtree(marker)
    if on_change:
        on_change()
    return done
