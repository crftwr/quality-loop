"""The ``quality-loop`` command: what a person types, and what the conductor runs.

    quality-loop run [scenarios...] [--variant V] [--parallel N]   start a run, print its id
    quality-loop status [<run>]                                    where it is
    quality-loop watch [<run>]                                     follow it
    quality-loop findings [<run>] [--since <run>]                  new / still there / gone / back
    quality-loop cancel [<run>]                                    stop it; the user's files go back
    quality-loop restore                                           put back what a dead run set aside
    quality-loop check                                             the scenarios, without a run
    quality-loop init [--upgrade]                                  the skill and the settings

A CLI rather than MCP tools for the conductor: it is a session with a shell,
what has to be guaranteed lives in the runner's code either way, and a person
can type the same commands. MCP pays off for an agent without a shell given a
narrow set of tools - the operator's case, which is `quality_loop.mcp`.

``<run>`` is a run directory, or its name under the rooms directory; left out,
it is the latest run.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

import quality_loop
from quality_loop import compare, config, progress


def _say_error(text: str) -> int:
    print(f"error: {text}", file=sys.stderr)
    return 1


def _settings(args) -> config.Config:
    return config.find(explicit=getattr(args, "config", None))


def _run_dir(args, settings: config.Config, adapter=None) -> pathlib.Path:
    given = getattr(args, "run", None)
    if given:
        path = pathlib.Path(given)
        if path.is_dir():
            return path.resolve()
        under = settings.rooms(adapter) / given
        if under.is_dir():
            return under
        raise config.ConfigError(f"no run {given!r}")
    found = compare.latest(settings.rooms(adapter))
    if found is None:
        raise config.ConfigError(f"no runs under {settings.rooms(adapter)}")
    return found


# --- run -----------------------------------------------------------------------------

def cmd_run(args) -> int:
    from quality_loop import runner

    settings = _settings(args)
    adapter = config.load_adapter(settings)
    known = None
    if args.known:
        known = json.loads(pathlib.Path(args.known).read_text(encoding="utf-8"))
    directory = pathlib.Path(args.into) if args.into else runner.run_directory(adapter)
    if args.foreground:
        runner.run(adapter, args.scenarios or None, model=args.model,
                   operator_model=args.operator_model, directory=directory,
                   parallel=args.parallel, variants=args.variant or None, known=known,
                   log=not args.detached)
        return 0
    # Detached: a process of its own, writing run.log and status.json, so
    # whoever started it - a person or the conductor - can follow it, ask
    # after it and cancel it, and is not holding it.
    directory.mkdir(parents=True)
    argv = [sys.executable, "-m", "quality_loop", "run", "--foreground", "--detached",
            "--into", str(directory)]
    if settings.path:
        argv += ["--config", str(settings.path)]
    for flag, value in (("--model", args.model), ("--operator-model", args.operator_model),
                        ("--parallel", args.parallel), ("--known", args.known)):
        if value is not None:
            argv += [flag, str(pathlib.Path(value).resolve()) if flag == "--known" else str(value)]
    for variant in args.variant or []:
        argv += ["--variant", variant]
    argv += list(args.scenarios)
    log = (directory / "run.log").open("a", encoding="utf-8")
    options = ({"creationflags": 0x00000200 | 0x00000008}  # NEW_PROCESS_GROUP | DETACHED
               if os.name == "nt" else {"start_new_session": True})
    child = subprocess.Popen(argv, cwd=settings.root, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONUNBUFFERED="1",
                                      PYTHONIOENCODING="utf-8"), **options)
    log.close()
    progress.write_json(directory / "status.json", {
        "run": directory.name, "product": adapter.name, "version": str(adapter.version),
        "pid": child.pid, "state": "starting", "started": progress.now(),
        "updated": progress.now(), "rooms": {}, "cost_usd": 0.0, "findings": None})
    print(directory.name)
    print(f"  directory: {directory}", file=sys.stderr)
    print(f"  follow:    {settings.command} watch {directory.name}", file=sys.stderr)
    print(f"  log:       {directory / 'run.log'}", file=sys.stderr)
    return 0


# --- status, watch, cancel ------------------------------------------------------------

def cmd_status(args) -> int:
    settings = _settings(args)
    directory = _run_dir(args, settings)
    status = progress.read(directory)
    if status is None:
        return _say_error(f"{directory} has no status.json")
    if args.json:
        status["process_alive"] = progress.process_alive(status.get("pid"))
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        print(progress.summary(status))
    return 0


def _signature(status: dict | None) -> tuple:
    if not status:
        return ()
    return (status.get("state"),
            tuple((k, v.get("phase")) for k, v in status.get("rooms", {}).items()))


def watch(directory: pathlib.Path | None, rooms: pathlib.Path, interval: float = 0.5,
          out=print, until=None) -> None:
    """A run's summary at each change, and its log as it grows.

    Given no run, it follows the latest, and moves on to the next one when it
    starts - so it can be left open across a loop of runs.
    """
    follow = directory is None
    current = directory or compare.latest(rooms)
    if current is None:
        out(f"waiting for a run under {rooms} ...")
    position, seen, warned = 0, None, False
    while until is None or not until():
        if follow:
            newest = compare.latest(rooms)
            if newest is not None and newest != current:
                if current is not None:
                    out(f"\n=== next run: {newest.name}")
                current, position, seen, warned = newest, 0, None, False
        if current is None:
            time.sleep(interval)
            continue
        log = current / "run.log"
        if log.exists():
            with log.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(position)
                chunk = handle.read()
                position = handle.tell()
            if chunk:
                out(chunk.rstrip("\n"))
        status = progress.read(current)
        if _signature(status) != seen:
            seen = _signature(status)
            if status:
                out("── " + progress.summary(status).replace("\n", "\n   "))
        if status and status.get("state") in ("starting", "running") and \
                not progress.process_alive(status.get("pid")) and not warned:
            out("!! the run's process is gone and it never finished - it was killed; "
                "`quality-loop restore` puts back anything it set aside")
            warned = True
        if not follow and status and (status.get("state") in ("done", "cancelled", "failed")
                                      or warned):
            return
        time.sleep(interval)


def cmd_watch(args) -> int:
    settings = _settings(args)
    directory = _run_dir(args, settings) if args.run else None
    try:
        watch(directory, settings.rooms())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_cancel(args) -> int:
    settings = _settings(args)
    directory = _run_dir(args, settings)
    status = progress.read(directory) or {}
    pid = status.get("pid")
    if not progress.process_alive(pid):
        return _say_error(f"{directory.name} is not running ({status.get('state', 'no status')})")
    # Never harder than this: the run turns it into the same unwinding as
    # Ctrl-C, and every stand-in puts the user's files back.
    os.kill(pid, signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
    print(f"cancelling {directory.name} (pid {pid}); it puts the user's files back and "
          f"writes its findings so far")
    return 0


# --- findings --------------------------------------------------------------------

def cmd_findings(args) -> int:
    settings = _settings(args)
    directory = _run_dir(args, settings)
    since = None
    if args.since:
        given = pathlib.Path(args.since)
        since = given if given.is_dir() else directory.parent / args.since
        if not since.is_dir():
            return _say_error(f"no run {args.since!r}")
    result = compare.against_history(directory, since)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json
          else compare.text(result))
    return 0


# --- restore, check, init ----------------------------------------------------------

def cmd_restore(args) -> int:
    adapter = config.load_adapter(_settings(args))
    try:
        for line in adapter.restore():
            print(line)
    except NotImplementedError as error:
        return _say_error(str(error))
    return 0


def check(adapter) -> tuple[list[str], list[str]]:
    """``(errors, warnings)`` about the adapter's scenarios, without a run."""
    from quality_loop import scenario

    errors, warnings = [], []
    try:
        cases = scenario.load(adapter.scenarios)
    except scenario.ScenarioError as error:
        return [str(error)], []
    fixtures = pathlib.Path(adapter.fixtures) if adapter.fixtures else None
    for name, screen in (adapter.screens or {}).items():
        source = getattr(screen, "file", None) or getattr(screen, "script", None)
        if fixtures is None or not (fixtures / source).is_file():
            errors.append(f"screen {name}: {source} is not in the fixtures directory")
    for case in cases:
        # Backticked words; a file name (a staged input) is not a screen.
        named = {word.strip("`.,;:()") for word in case.section("Screen").split()
                 if word.startswith("`") and "." not in word.strip("`.,;:()")}
        if undeclared := sorted(n for n in named if n not in (adapter.screens or {})):
            warnings.append(f"{case.name}: the Screen section names {', '.join(undeclared)}, "
                            f"which no screen is declared as")
        if case.section("Live check").strip() and not adapter.apps:
            errors.append(f"{case.name}: has a Live check, and the adapter declares no apps")
    if not cases:
        warnings.append(f"no scenarios in {adapter.scenarios}")
    return errors, warnings


def cmd_check(args) -> int:
    adapter = config.load_adapter(_settings(args))
    errors, warnings = check(adapter)
    for line in errors:
        print(f"error:   {line}")
    for line in warnings:
        print(f"warning: {line}")
    if not errors:
        from quality_loop import scenario
        print(f"ok: {len(scenario.load(adapter.scenarios))} scenario(s)")
    return 1 if errors else 0


def cmd_init(args) -> int:
    from quality_loop import install

    root = pathlib.Path(args.root or os.getcwd())
    return install.init(root, upgrade=args.upgrade, force=args.force, rooms=args.rooms,
                        adapter=args.adapter)


def cmd_screen(args) -> int:
    from quality_loop import screens

    try:
        if args.action == "list":
            answer = {name: {"kind": e["kind"], "title": e["title"]}
                      for name, e in screens.names().items()}
        elif args.action == "open":
            answer = screens.open_screen(args.name)
        else:
            answer = screens.close_screen(args.id)
    except screens.ScreenError as error:
        return _say_error(str(error))
    print(json.dumps(answer, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="quality-loop", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    top.add_argument("--version", action="version",
                     version=f"quality-loop {quality_loop.__version__}")
    commands = top.add_subparsers(dest="command", required=True)

    def add(name, function, help_text):
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("--config", help="qa/quality-loop.toml, if not found from here")
        command.set_defaults(function=function)
        return command

    run = add("run", cmd_run, "start a run and print its id")
    run.add_argument("scenarios", nargs="*", help="by number or name; none for all")
    run.add_argument("--variant", action="append", help="only this variant (repeatable)")
    run.add_argument("--parallel", type=int, help="rooms at once (the adapter's limit "
                     "and resources still apply)")
    run.add_argument("--model", help="model for the rooms")
    run.add_argument("--operator-model", help="model for the operators")
    run.add_argument("--known", help="JSON list of known problems [{id, title, room}], "
                     "handed to the operators as neutral data")
    run.add_argument("--foreground", "-f", action="store_true",
                     help="run here, attached, instead of in the background")
    run.add_argument("--into", help=argparse.SUPPRESS)
    run.add_argument("--detached", action="store_true", help=argparse.SUPPRESS)

    for name, function, help_text in (("status", cmd_status, "where a run is"),
                                      ("watch", cmd_watch, "follow a run's log and status"),
                                      ("cancel", cmd_cancel, "stop a run; it puts the "
                                       "user's files back")):
        command = add(name, function, help_text)
        command.add_argument("run", nargs="?", help="a run directory or name; default latest")
        if name == "status":
            command.add_argument("--json", action="store_true")

    findings = add("findings", cmd_findings, "a run's findings against an earlier run's")
    findings.add_argument("run", nargs="?")
    findings.add_argument("--since", help="the run to compare with; default the one before")
    findings.add_argument("--json", action="store_true")

    add("restore", cmd_restore, "put back what a run that could not unwind set aside")
    add("check", cmd_check, "check the scenarios and screens without a run")

    init = commands.add_parser("init", help="install the conductor skill and the settings")
    init.add_argument("--upgrade", action="store_true", help="replace the skill with this "
                      "version's")
    init.add_argument("--force", action="store_true", help="replace it even if edited")
    init.add_argument("--rooms", help="where runs are kept, relative to the checkout")
    init.add_argument("--adapter", help="the adapter, e.g. qa/run.py:Product")
    init.add_argument("--root", help="the product's checkout; default here")
    init.set_defaults(function=cmd_init)

    screen = commands.add_parser("screen", help="put up or take down a declared screen "
                                 "(the operator's, under a run)")
    actions = screen.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="the screens the adapter declares")
    opening = actions.add_parser("open", help="open one, and wait for its window")
    opening.add_argument("name")
    closing = actions.add_parser("close", help="close one that `open` recorded")
    closing.add_argument("id")
    screen.set_defaults(function=cmd_screen)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.function(args)
    except config.ConfigError as error:
        return _say_error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
