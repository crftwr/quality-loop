"""A run: for each scenario, a room, its operator, and a report.

    build the room (TASK.md is the scenario's Prompt, verbatim)
    stand fixtures in for the operator's files
    serve the fixture pages, write the screen manifest
    operator phase 1 - puts the screen up; the room must come out unchanged
    the room's session
    operator live check - drives the real app, if the scenario has one
    collect evidence, put the operator's files back
    audit the transcript
    operator phase 2 - writes REPORT.md
    close any screen still open
    ...
    FINDINGS.md and findings.json, concatenated from the reports

There is no verdict. A room that could not be measured - a cancelled phase 1,
an isolation breach, a lost product or model - still gets a report, written
here as a harness problem, so the human reading the findings sees it.

Rooms run one after another unless the adapter says otherwise
(``parallel``, ``resources``, ``needs``): then a queue starts any room whose
resources are free, up to the limit, and a cancel ends every one of them,
each putting its stand-in back in its own ``finally``.

Everything said goes to ``run.log`` and the run's state to ``status.json``,
beside the rooms (`quality_loop.progress`), so another process can follow it.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import pathlib
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

import quality_loop
from quality_loop import (audit, drive, operator, pages, processes, progress, report,
                          room, scenario, screens, standin, transcript)


class RunnerError(Exception):
    """A room the runner will not start."""


def refuse_a_reachable_marker(marker: pathlib.Path, built: pathlib.Path,
                              add_dirs: list[pathlib.Path]) -> None:
    """The operator's set-aside files must be out of the room's reach.

    The first run of the toy put them inside the one directory the room could
    write to. The room saw a second style.txt beside the fixture and ignored
    it. A room that read it would have measured the harness, and one that
    wrote to it could have touched the operator's own file.
    """
    marker = pathlib.Path(marker).resolve()
    for reach in [built, *add_dirs]:
        reach = pathlib.Path(reach).resolve()
        if marker == reach or reach in marker.parents:
            raise RunnerError(
                f"the stand-in keeps the operator's files in {marker}, inside {reach}, "
                f"which the room can reach - put the marker outside it")


def _overlap(a: pathlib.Path, b: pathlib.Path) -> bool:
    a, b = pathlib.Path(a).resolve(), pathlib.Path(b).resolve()
    return a == b or a in b.parents or b in a.parents


class Reach:
    """What the rooms running now can reach, and where their markers are.

    Side by side, a room must not reach a sibling's directories, nor any
    room's set-aside files: one room reading another's work has learned from
    somebody who was not given only the product.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._rooms: dict[str, tuple[list[pathlib.Path], pathlib.Path | None]] = {}

    def claim(self, label: str, built: pathlib.Path, add_dirs: list[pathlib.Path],
              marker: pathlib.Path | None) -> None:
        reach = [pathlib.Path(built), *map(pathlib.Path, add_dirs)]
        with self._lock:
            if marker is not None:
                refuse_a_reachable_marker(marker, built, add_dirs)
            for other, (their_reach, their_marker) in self._rooms.items():
                if marker is not None:
                    for place in their_reach:
                        if _overlap(marker, place):
                            raise RunnerError(f"{label}'s stand-in marker {marker} is "
                                              f"within reach of {other}, running alongside")
                if their_marker is not None:
                    for place in reach:
                        if _overlap(their_marker, place):
                            raise RunnerError(f"{other}'s stand-in marker is within "
                                              f"{label}'s reach")
                for mine in reach[1:]:
                    for theirs in their_reach[1:]:
                        if _overlap(mine, theirs):
                            raise RunnerError(
                                f"{label} and {other} would share {mine} - rooms side by "
                                f"side need directories of their own")
            self._rooms[label] = (reach, marker)

    def release(self, label: str) -> None:
        with self._lock:
            self._rooms.pop(label, None)


def _cancelled(case, what: str, problem_id: str, evidence: str) -> str:
    return (f"# Report: {case.title}\n\nThis room could not be measured.\n\n"
            f"### [critical] {what}\n- **Id:** `{problem_id}`\n- **Kind:** harness\n"
            f"- **Evidence:** {evidence}\n- **Where it would be fixed:** the runner\n"
            f"- **How a fix is confirmed:** the room runs and is reported on\n")


def label_of(case, variant: str) -> str:
    return case.name + (f".{variant}" if variant else "")


def pick_variants(adapter, items, variants: list[str] | None):
    """Only the rooms whose variant was asked for; ``""`` is spelled as the
    adapter's ``default_variant``."""
    if not variants:
        return items
    wanted = set(variants)
    return [(case, variant) for case, variant in items
            if (variant or adapter.default_variant) in wanted or variant in wanted]


def known_for(known: list[dict] | None, case, label: str) -> list[dict]:
    """The known problems that concern one room: those seen in it, in its
    scenario, or nowhere in particular. Never the whole history - an operator
    handed every id ever reported starts matching instead of looking."""
    found = []
    for entry in known or []:
        where = str(entry.get("room") or entry.get("scenario") or "")
        if not where or where == label or where == case.name or \
                where.split(".", 1)[0] == case.name:
            found.append({"id": entry.get("id", ""), "title": entry.get("title", "")})
    return found


def run_directory(adapter) -> pathlib.Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return adapter.rooms / f"{adapter.version}-{stamp}"


def _install_signals() -> None:
    # SIGTERM unwinds like Ctrl-C, so the stand-in puts the operator's files
    # back instead of dying with them set aside. SIGBREAK is how a detached
    # run is cancelled on Windows.
    raising = lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())  # noqa: E731
    signal.signal(signal.SIGTERM, raising)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, raising)


def run(adapter, names: list[str] | None = None, model: str | None = None,
        operator_model: str | None = None, say=print, *,
        directory: pathlib.Path | None = None, parallel: int | None = None,
        variants: list[str] | None = None, known: list[dict] | None = None,
        log: bool = True) -> pathlib.Path:
    """Run every scenario ``names`` picks, and return FINDINGS.md's path.

    Args:
        adapter: The product's adapter.
        names: Scenarios by number or name; None for every one ``runs`` keeps.
        model, operator_model: Model overrides for the rooms and operators.
        say: Where the progress lines go, besides run.log.
        directory: The run's directory, when the caller chose it (the CLI
            does, to print it before a detached run starts).
        parallel: Rooms at once; None for the adapter's ``parallel``.
        variants: Only these variants (``--variant``).
        known: Problems earlier runs reported, ``[{id, title, room}]``, handed
            to the operators of the rooms they concern as neutral data.
        log: Write run.log - off when stdout already is it.
    """
    sys.stdout.reconfigure(line_buffering=True)
    _install_signals()
    processes.reset()
    cases = scenario.load(adapter.scenarios, names)
    parent = pathlib.Path(directory) if directory else run_directory(adapter)
    parent.mkdir(parents=True, exist_ok=True)
    items = pick_variants(adapter, adapter.runs(cases, named=bool(names)), variants)
    limit = max(1, int(parallel if parallel is not None else adapter.parallel))
    status = progress.Progress(parent, product=adapter.name, version=str(adapter.version),
                               echo=say, log=log, prefix_rooms=limit > 1)
    status.say(f"rooms:   {parent}")
    status.plan([(label_of(c, v), c.name, v) for c, v in items], parallel=limit)
    texts: dict[str, tuple[str, str]] = {}
    reach = Reach()
    state = "done"
    try:
        bundle = adapter.bundle()
        with adapter.product():
            def work(item):
                case, variant = item
                label = label_of(case, variant)
                status.say(f"\n== {label}: {case.title}", label)
                try:
                    text = _one(adapter, case, variant, parent / label, bundle, model,
                                operator_model, status, reach,
                                known_for(known, case, label))
                except standin.StandInError:
                    # The user's files are at risk: nothing more starts.
                    raise
                except Exception as error:  # noqa: BLE001 - one room, not the run
                    # A room that fails is reported, and the others go on.
                    status.say(f"  FAILED: {type(error).__name__}: {error}", label)
                    status.phase(label, "cancelled")
                    text = _cancelled(case, "The room failed with an error", "room-failed",
                                      f"{type(error).__name__}: {error}")
                if text is not None:
                    texts[label] = (case.title, text)
            _drive(adapter, items, limit, work, status)
    except KeyboardInterrupt:
        state = "cancelled"
        status.say("\n  interrupted - the room in progress was collected and the "
                   "operator's files put back")
    except BaseException:
        status.finish("failed")
        raise
    reports = [(label, *texts[label]) for label in
               (label_of(c, v) for c, v in items) if label in texts]
    findings = report.write_findings(parent, reports)
    status.say(f"\n  findings: {findings}")
    status.finish(state, findings)
    return findings


def _drive(adapter, items, limit: int, work, status) -> None:
    """Every item through ``work``: in order, or side by side up to ``limit``
    while each one's resources are free."""
    if limit <= 1:
        for item in items:
            work(item)
        return
    capacity = dict(adapter.resources)
    in_use: dict[str, int] = {}
    waiting = list(items)
    running: dict[threading.Thread, tuple] = {}
    failures: list[BaseException] = []
    wake = threading.Condition()

    def worker(item, need):
        try:
            work(item)
        except KeyboardInterrupt:
            pass
        except BaseException as error:  # noqa: BLE001 - re-raised by the main thread
            failures.append(error)
            processes.cancel_all()
        finally:
            with wake:
                for resource in need:
                    in_use[resource] -= 1
                running.pop(threading.current_thread(), None)
                wake.notify_all()

    try:
        with wake:
            while waiting or running:
                if processes.cancelled.is_set():
                    waiting.clear()
                for item in list(waiting):
                    if len(running) >= limit:
                        break
                    need = adapter.needs(*item)
                    if all(in_use.get(r, 0) < capacity.get(r, 1) for r in need):
                        waiting.remove(item)
                        for resource in need:
                            in_use[resource] = in_use.get(resource, 0) + 1
                        thread = threading.Thread(target=worker, args=(item, need),
                                                  daemon=True)
                        running[thread] = item
                        thread.start()
                wake.wait(0.5)
    except KeyboardInterrupt:
        processes.cancel_all()
        while True:
            # Every worker unwinds through its own finally - the stand-ins go
            # back - before the run is reported cancelled.
            try:
                for thread in list(running):
                    thread.join()
                break
            except KeyboardInterrupt:
                continue
        raise
    if failures:
        raise failures[0]


def starting_point(adapter, case, variant: str, stand_in, model, operator_model) -> dict:
    """What a later agent needs to rebuild this room's start: the product's
    version and commit, the OS, the fixtures, the models."""
    commit, dirty = "", None
    try:
        done = subprocess.run(["git", "-C", str(adapter.checkout), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        commit = done.stdout.strip()
        changed = subprocess.run(["git", "-C", str(adapter.checkout), "status",
                                  "--porcelain"], capture_output=True, text=True, timeout=10)
        dirty = bool(changed.stdout.strip()) if changed.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "scenario": case.name, "variant": variant, "product": adapter.name,
        "product_version": str(adapter.version), "commit": commit, "dirty": dirty,
        "platform": sys.platform, "os": platform.platform(), "python": sys.version.split()[0],
        "quality_loop": quality_loop.__version__,
        "models": {"room": model, "operator": operator_model},
        "fixtures": sorted(getattr(stand_in, "fixtures", {}) or {}),
        "apps": {name: ({"rows": app.rows, "cols": app.cols} if app.kind == "tui"
                        else {"title": app.title})
                 for name, app in (adapter.apps or {}).items()},
    }


def _room_apps(adapter, session, private: pathlib.Path) -> pathlib.Path | None:
    """Give the room the app tools, for a product whose UI is its surface.

    The record goes to a private directory first and into the evidence once
    the session is over: written inside the room while it runs, it would be a
    log the room could read.
    """
    names = list(adapter.room_apps or ())
    if not names:
        return None
    record = private / "room-steps"
    entries = drive.manifest_entries({n: adapter.apps[n] for n in names})
    manifest = private / "room-apps.json"
    manifest.write_text(json.dumps({"apps": entries, "record": str(record)}, indent=2),
                        encoding="utf-8")
    session.mcp_servers = {**session.mcp_servers, "app": {
        "command": adapter.python, "args": ["-m", "quality_loop.mcp"],
        "env": {screens.MANIFEST: str(manifest)}}}
    if "mcp__app" not in session.allow:
        session.allow = [*session.allow, "mcp__app"]
    return record


def _one(adapter, case, variant, here: pathlib.Path, bundle, model, operator_model,
         status, reach: Reach, known: list[dict]) -> str | None:
    label = here.name
    say = status.for_room(label)
    status.phase(label, "operator-1")
    try:
        built = room.build(here, prompt=case.prompt, rules=adapter.rules(), bundle=bundle,
                           skill_name=adapter.skill_name, rooms=adapter.rooms,
                           checkout=adapter.checkout, place=adapter.bundle_place)
    except room.RoomError as error:
        say(f"  CANCELLED: {error}")
        status.phase(label, "cancelled")
        return _cancelled(case, "The room could not be built", "room-not-built", str(error))
    evidence = built / "evidence"
    evidence.mkdir()
    private = pathlib.Path(tempfile.mkdtemp(prefix="quality-loop-private-"))
    directory = here.with_name(here.name + ".operator")
    session = adapter.session(built)
    if model:
        session.model = model
    room_record = _room_apps(adapter, session, private)
    stand_in = adapter.stand_in(case, variant, built)
    try:
        reach.claim(label, built, session.add_dirs,
                    stand_in.marker if stand_in is not None else None)
    except RunnerError as error:
        say(f"  CANCELLED: {error}")
        status.phase(label, "cancelled")
        shutil.rmtree(private, ignore_errors=True)
        return _cancelled(case, "The room could not start safely", "room-not-started",
                          str(error))
    start = starting_point(adapter, case, variant, stand_in, model, operator_model)
    live = bool(case.section("Live check").strip()) and bool(adapter.apps)
    stand_in = stand_in or contextlib.nullcontext()
    served = pages.Pages(adapter.fixtures) if adapter.fixtures else contextlib.nullcontext()
    own_product = adapter.product_for(built) or contextlib.nullcontext()
    op = None
    backend = None
    try:
        with own_product, stand_in, served as site:
            backend = adapter.screen_backend()
            manifest = screens.write_manifest(
                private / "manifest.json", adapter.screens,
                fixtures=adapter.fixtures or adapter.checkout,
                origin=site.origin if site else "", python=adapter.python,
                state=directory, evidence=adapter.evidence,
                apps=drive.manifest_entries(adapter.apps) if live else None,
                record=evidence / "live", backend=backend)
            op = operator.Operator(
                room=built, directory=directory, scenario=case.path,
                checkout=adapter.checkout,
                evidence_help=adapter.evidence_help, manifest=manifest,
                python=adapter.python, model=operator_model, known=known)
            say("  operator: phase 1 - the screen")
            op.phase_one(adapter.platform(), say=say)
            _checkpoint()
            status.phase(label, "room")
            say("  room:    running")
            ran = session.run(built, alive=adapter.alive, say=say,
                              on_quiet=lambda quiet: status.thinking(label, quiet))
            if site:
                site.write(evidence / "screen-events.jsonl")
            if room_record is not None and room_record.exists():
                shutil.copytree(room_record, evidence / "app", dirs_exist_ok=True)
            _checkpoint()
            if live:
                status.phase(label, "live-check")
                say("  operator: live check - the real app")
                op.live_check(say=say)
                _checkpoint()
            status.phase(label, "collecting")
        room_cost = float((transcript.result_event(ran.transcript) or {})
                          .get("total_cost_usd") or 0)
        status.cost(label, room_cost)
        (evidence / "run.json").write_text(json.dumps(
            {**start, "exit_code": ran.exit_code, "product_lost": ran.product_lost,
             "model_lost": transcript.lost_the_model(ran.transcript),
             "room_cost_usd": room_cost}, indent=2), encoding="utf-8")
        policy = adapter.policy(built)
        policy.run_directory = here.parent
        theirs = policy.leaked_skill
        # The conductor's skill is a scoring key too: it knows the scenarios.
        policy.leaked_skill = lambda command: "quality-loop" in command or bool(
            theirs and theirs(command))
        if room_record is not None and "app" not in policy.servers:
            policy.servers = (*policy.servers, "app")
        breaches, refused = audit.audit(built, policy)
        (evidence / "audit.json").write_text(json.dumps(
            {"breaches": breaches, "refused": refused}, indent=2), encoding="utf-8")
        for line in breaches:
            say(f"  BREACH: {line}")
        status.phase(label, "operator-2")
        say("  operator: phase 2 - the report")
        written = op.phase_two(say=say)
        text = written.read_text(encoding="utf-8") if written.exists() else ""
        if breaches:
            text = _cancelled(case, "The room broke isolation; nothing it did is evidence",
                              "isolation-breach", "; ".join(breaches)) + "\n" + text
        if ran.product_lost or transcript.lost_the_model(ran.transcript):
            what = "the product" if ran.product_lost else "the model's API"
            text = _cancelled(case, f"{what} stopped answering during the run",
                              "lost-" + ("product" if ran.product_lost else "model"),
                              "run.json") + "\n" + text
        status.phase(label, "done")
        return text
    except operator.OperatorError as error:
        say(f"  CANCELLED: {error}")
        status.phase(label, "cancelled")
        which = ("The live check changed the room" if "live check" in str(error)
                 else "Operator phase 1 changed the room")
        return _cancelled(case, which, "phase-one-touched-room"
                          if "phase 1" in str(error) else "live-check-touched-room",
                          str(error))
    except KeyboardInterrupt:
        status.phase(label, "cancelled")
        raise
    finally:
        if op is not None:
            status.cost(label, op.cost)
        closed = (screens.close_all(directory, screens.load_backend(backend)
                                    if backend else None)
                  if directory.exists() else [])
        if closed:
            say(f"  closed:  {', '.join(closed)} (left open by the operator)")
        shutil.rmtree(private, ignore_errors=True)
        reach.release(label)


def _checkpoint() -> None:
    """Stop between phases once a run is cancelled: a session that was
    terminated has returned normally, and the next phase must not start."""
    if processes.cancelled.is_set():
        raise KeyboardInterrupt()
