"""A product's test suite in a guest: pytest run there, its output here.

The product stages itself and builds the venv (:meth:`Guest.stage`,
:meth:`Guest.venv`); :func:`run_pytest` does the rest the same way for every
guest, which Keyhac and XeFM each used to carry a copy of:

- **Windows:** pytest runs in the signed-in desktop session, from a scheduled
  task through ``boot/launch.py``, with ``python.exe`` - a console of its
  own, which a test that runs a console program needs to inherit (under
  pythonw such a test saw code page 0, empty child output, and standard
  handles that could not be duplicated). Its output is a log on the share,
  printed here as it grows.
- **macOS over SSH, and a container:** the output comes back on the command's
  own stdout, and is printed and logged as it comes.

Either way ``boot/pytest_main.py`` writes pytest's exit code to a file on the
share when it is done; that is the run's answer. The log and the JUnit XML
are copied to ``results``. :data:`IN_GUEST` is set for the suite, which is how
:mod:`quality_loop.pytest_plugin` knows to skip the ``host_only`` tests.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import time

from quality_loop.guest import IN_GUEST, Guest, sh_quote


def follow(log: pathlib.Path, done: pathlib.Path, patience: float) -> int:
    """Print ``log`` as it grows until ``done`` holds an exit code; 3 when
    nothing ends within ``patience`` seconds."""
    position, deadline, finished_at = 0, time.monotonic() + patience, None
    while True:
        finished = done.exists()
        chunk = ""
        if log.exists():
            with log.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(position)
                chunk = f.read()
                position = f.tell()
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()
        if finished:
            # Over SMB the log's last writes can show up after the exit code
            # does: read on until it has stopped growing.
            if chunk or (time.monotonic() - finished_at if finished_at else 0) < 3:
                finished_at = finished_at or time.monotonic()
                time.sleep(1)
                continue
            return int(done.read_text(encoding="utf-8").strip() or 3)
        if time.monotonic() > deadline:
            print(f"\nvm:      no end within {patience:.0f}s", flush=True)
            return 3
        time.sleep(1)


def run_pytest(guest: Guest, stage: pathlib.Path, python: str, args: list[str], *,
               cwd: str, results: pathlib.Path, environ: dict | None = None,
               path: list[str] | None = None, patience: float = 3600.0,
               task: str = "ql-test") -> int:
    """pytest with ``args`` in the guest, from ``cwd`` (a guest path) with
    ``python`` (the venv's); returns its exit code, 3 when it never told.

    ``environ`` is set for the suite, :data:`IN_GUEST` with it; ``path`` goes
    in front of ``sys.path`` too on Windows, where the scheduled task has no
    shell to set PYTHONPATH in. The log and ``junit.xml`` land in
    ``results``, made if need be."""
    log, done, junit = stage / "pytest.log", stage / "exit-code", stage / "junit.xml"
    environ = {**(environ or {}), IN_GUEST: guest.alias}
    argv = [guest.path(done), "-p", "no:cacheprovider", f"--junitxml={guest.path(junit)}",
            *args]
    runner = guest.path(guest.boot_script(stage, "pytest_main.py"))
    task = f"{task}-{stage.name}"
    code = 3
    try:
        if guest.windows:
            guest.launch(stage, task, python, script=runner, log=log, environ=environ,
                         path=path, cwd=cwd, argv=argv)
            code = follow(log, done, patience)
        else:
            command = (f"cd {sh_quote(cwd)} && "
                       + " ".join(f"{name}={sh_quote(value)}" for name, value in environ.items())
                       + f" {sh_quote(python)} {sh_quote(runner)} "
                       + " ".join(sh_quote(a) for a in argv))
            with log.open("w", encoding="utf-8") as out:
                process = subprocess.Popen(guest.argv(command), stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, errors="replace")
                for line in process.stdout:
                    sys.stdout.write(line)
                    out.write(line)
                process.wait()
            code = int(done.read_text().strip()) if done.exists() else 3
    finally:
        results.mkdir(parents=True, exist_ok=True)
        for kept in (log, junit):
            if kept.exists():
                shutil.copy2(kept, results / kept.name)
        if guest.windows:
            guest.forget_task(task)
    return code
