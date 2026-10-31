"""A product's app in a VM, off the host's keyboard and screen (keyhac#271, xefm#750).

Everything Claude does stays on the host: the room, the operator, the
evidence, the rooms directory. Only the product's app moves into a guest, and
the run reaches it the way it reaches a local one:

- **A folder is shared.** The host writes into its host side (the stage, the
  run's home, results); the guest reads the same files under its guest side.
  :meth:`Guest.path` turns one into the other.
- **The guest is an SSH host alias.** Its address, user and key live in
  ``~/.ssh/config``, never here. A port the app opens in the guest is
  forwarded to the host (:meth:`Guest.forward`), and one the host serves is
  forwarded into the guest (:meth:`Guest.reverse`).
- **The guest's runtime is its own image's.** The image carries a Python
  runtime and nothing that is under test (xefm#750, "Decisions on the shared
  test image"): the product's working tree and what else its makers build are
  staged every run, and third-party packages are installed into a fresh venv
  in the guest every run (:meth:`Guest.venv`), with pip's download cache on
  the host side of the share so a revert does not lose the downloads.
- **What has to be on the desktop runs in the desktop session**, where a
  window is seen and can take focus - not in the SSH session, which has
  neither. Windows starts it from a scheduled task run as the logged-in user
  (:meth:`Guest.run_in_session`).

The VM should be clean when a run starts: a Tart clone of a base image, or a
VMware snapshot reverted to. When the per-machine settings name the VM for
the alias, :meth:`Guest.machine` does that itself.

Per-machine settings live outside every repository - they name this
machine's VMs, paths and Keychain items, never a secret itself -
in ``~/.config/quality-loop/guests.toml`` (``QUALITY_LOOP_GUESTS`` moves it):

    [qa-mac]
    share = "~/.cache/qa-guest=/Volumes/My Shared Files/qa"
    python = "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
    tart = "<base VM>"                  # cloned per run, deleted after
    visible = true

    [qa-win]
    share = "~/mnt/qa-win=C:\\\\qa"
    python = "C:\\\\Python314\\\\python.exe"
    vmx = "~/Virtual Machines.localized/<VM>.vmwarevm/<VM>.vmx"
    snapshot = "<snapshot>"             # reverted to before the run
    vm_password = "keychain:<service>"  # the VM's encryption password
    smb = "//<user>@<guest>/<share>"    # remounted on the share's host side
    smb_password = "keychain:<service>"

Without a VM named, the run uses the guest as it is, already running.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import ntpath
import os
import pathlib
import posixpath
import shutil
import socket
import subprocess
import tempfile
import time
import tomllib
import urllib.parse

#: Per-machine settings, by SSH alias. QUALITY_LOOP_GUESTS moves it.
GUESTS = pathlib.Path("~/.config/quality-loop/guests.toml")

HERE = pathlib.Path(__file__).resolve().parent


class GuestError(Exception):
    """The guest could not be reached, started or used."""


def settings_for(alias: str, path: pathlib.Path | str | None = None) -> dict:
    """The table for ``alias`` in the per-machine settings, or ``{}``."""
    where = pathlib.Path(path or os.environ.get("QUALITY_LOOP_GUESTS", GUESTS)).expanduser()
    try:
        with where.open("rb") as f:
            return tomllib.load(f).get(alias, {})
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as error:
        raise GuestError(f"{where}: {error}") from None


def secret(value: str) -> str:
    """``keychain:<service>`` read from the login Keychain; anything else as
    it is. Read when a run needs it, never written anywhere."""
    if not value.startswith("keychain:"):
        return value
    service = value.removeprefix("keychain:")
    said = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                          capture_output=True, text=True)
    if said.returncode != 0:
        raise GuestError(f"no Keychain item {service!r}: add it with "
                         f"security add-generic-password -a <account> -s {service} -w")
    return said.stdout.rstrip("\n")


def sh_quote(word: str) -> str:
    return "'" + word.replace("'", "'\\''") + "'"


def ps_quote(word: str) -> str:
    """A PowerShell single-quoted literal."""
    return "'" + word.replace("'", "''") + "'"


class Guest:
    """One VM, reached as an SSH host alias, sharing a folder with the host."""

    def __init__(self, alias: str, host_share: pathlib.Path, guest_share: str,
                 settings: dict | None = None):
        self.alias = alias
        self.host_share = pathlib.Path(host_share).resolve()
        self.guest_share = guest_share
        self.settings = settings or {}
        self._windows: bool | None = None
        #: Set while a run's clone is up: its address, which the alias's
        #: HostName does not know.
        self.hostname: str | None = None

    @classmethod
    def from_settings(cls, alias: str, settings: dict, share: str | None = None) -> "Guest":
        """A guest from its settings table; ``share`` (``host=guest``)
        overrides the table's."""
        share = share or settings.get("share", "")
        host, _, guest = share.partition("=")
        if not host or not guest:
            raise GuestError(f"the guest {alias!r} needs share = <host dir>=<guest dir>: "
                             "a folder shared with the VM, as each side sees it")
        host_share = pathlib.Path(host).expanduser()
        if not host_share.is_dir():
            raise GuestError(f"the share's host side, {host_share}, is not a directory")
        return cls(alias, host_share, guest, settings)

    @classmethod
    def from_environment(cls, variable: str = "QUALITY_LOOP_GUEST",
                         share_variable: str | None = None,
                         settings_path: pathlib.Path | str | None = None) -> "Guest | None":
        """The guest ``variable`` names, or None when it names none. A product
        passes its own variable names (``KEYHAC_QA_GUEST``)."""
        alias = os.environ.get(variable)
        if not alias:
            return None
        share = os.environ.get(share_variable) if share_variable else None
        return cls.from_settings(alias, settings_for(alias, settings_path), share)

    def to_settings(self) -> dict:
        """What :mod:`quality_loop.guest.screens` needs to reach this guest
        from another process: JSON, no secrets."""
        return {"alias": self.alias, "hostname": self.hostname,
                "host_share": str(self.host_share), "guest_share": self.guest_share,
                "windows": self.windows, "python": self.python}

    @classmethod
    def from_screen_settings(cls, settings: dict) -> "Guest":
        guest = cls(settings["alias"], pathlib.Path(settings["host_share"]),
                    settings["guest_share"], {"python": settings.get("python")})
        guest._windows = settings["windows"]
        guest.hostname = settings.get("hostname")
        return guest

    # --- talking to it ---------------------------------------------------------

    def ssh_options(self) -> list[str]:
        if self.hostname is None:
            return []
        # A clone answers with its base's host key at a new address each time.
        return ["-o", f"HostName={self.hostname}", "-o", f"HostKeyAlias={self.alias}",
                "-o", "StrictHostKeyChecking=accept-new"]

    def ssh(self, command: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(["ssh", "-o", "BatchMode=yes", *self.ssh_options(),
                               self.alias, command],
                              capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)

    def reachable(self, patience: float) -> bool:
        """Whether SSH gets in within ``patience`` seconds."""
        deadline = time.monotonic() + patience
        while time.monotonic() < deadline:
            try:
                if self.ssh("echo up", timeout=15).stdout.strip() == "up":
                    return True
            except subprocess.TimeoutExpired:
                pass
            time.sleep(3)
        return False

    def machine(self):
        """A context manager for the run: the VM up from a clean state, and
        put away afterwards, when the settings name one."""
        if "tart" in self.settings:
            return TartMachine(self)
        if "vmx" in self.settings:
            return VMwareMachine(self)
        return contextlib.nullcontext()

    @property
    def windows(self) -> bool:
        """Whether the guest is Windows - asked once. A Windows guest's shell
        is PowerShell, where `uname` is no command."""
        if self._windows is None:
            said = self.ssh("uname -s")
            if said.returncode == 255:
                raise GuestError(f"cannot reach the VM as {self.alias!r}:\n{said.stderr}")
            self._windows = said.stdout.strip() != "Darwin"
        return self._windows

    @property
    def platform(self) -> str:
        """``sys.platform`` as the guest's own Python would say it."""
        return "win32" if self.windows else "darwin"

    @property
    def python(self) -> str:
        """The image's interpreter, as the guest names it (``python`` in the
        settings)."""
        python = self.settings.get("python")
        if not python:
            raise GuestError(f"the guest {self.alias!r} has no python = in its settings: "
                             "the image's interpreter, as the guest names it")
        return python

    def path(self, host_path: pathlib.Path | str) -> str:
        """A path under the host side of the share, as the guest sees it."""
        parts = pathlib.Path(host_path).resolve().relative_to(self.host_share).parts
        join = ntpath.join if self.windows else posixpath.join
        return join(self.guest_share, *parts)

    def mkdtemp(self, prefix: str) -> pathlib.Path:
        """A new directory on the share (its host side)."""
        return pathlib.Path(tempfile.mkdtemp(prefix=prefix, dir=self.host_share)).resolve()

    def kill(self, pid: int) -> None:
        if self.windows:
            self.ssh(f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue")
        else:
            self.ssh(f"kill -INT {int(pid)}; sleep 3; kill -9 {int(pid)} 2>/dev/null; true")

    def forward(self, port: int) -> subprocess.Popen:
        """The guest's 127.0.0.1:port as the host's, until terminated."""
        return self._tunnel("-L", port)

    def reverse(self, port: int) -> subprocess.Popen:
        """The host's 127.0.0.1:port as the guest's, until terminated."""
        return self._tunnel("-R", port, start_new_session=True)

    def _tunnel(self, direction: str, port: int, **popen) -> subprocess.Popen:
        return subprocess.Popen(
            ["ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
             *self.ssh_options(), direction, f"{port}:127.0.0.1:{port}", self.alias],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            **popen)

    # --- what runs in it ---------------------------------------------------------

    def stage(self, prefix: str = "ql-stage-") -> pathlib.Path:
        """A new stage on the share, carrying what runs in the guest on
        quality-loop's behalf: its screen backends and the boot scripts
        (``<stage>/ql``). The product adds its own files beside them."""
        stage = self.mkdtemp(prefix)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        package = HERE.parent
        ql = stage / "ql" / "quality_loop"
        ql.mkdir(parents=True)
        # quality_loop/__init__.py and screens/ need nothing else; guest/ is
        # copied for its boot scripts.
        shutil.copy2(package / "__init__.py", ql / "__init__.py")
        shutil.copytree(package / "screens", ql / "screens", ignore=ignore)
        shutil.copytree(HERE, ql / "guest", ignore=ignore)
        return stage

    def boot_script(self, stage: pathlib.Path, name: str) -> pathlib.Path:
        """``name`` among the boot scripts, as staged."""
        return stage / "ql" / "quality_loop" / "guest" / "boot" / name

    def venv(self, stage: pathlib.Path, requirements: list[str], *,
             timeout: float = 900) -> str:
        """A fresh venv in the guest with ``requirements`` installed, from the
        image's Python; returns its interpreter as the guest names it.

        Made on the guest's own disk, which the revert after the run throws
        away, so every run gets what the working tree asks for now. pip's
        download cache is on the share (``<host share>/.pip-cache``), so the
        next run downloads only what changed. Nothing that is under test goes
        in here: the product stages its own code and its makers' packages."""
        lines = "\n".join(requirements) + "\n"
        digest = hashlib.sha256(lines.encode()).hexdigest()[:12]
        (stage / "requirements.txt").write_text(lines, encoding="utf-8")
        cache = self.host_share / ".pip-cache"
        cache.mkdir(exist_ok=True)
        if self.windows:
            where = rf"$env:LOCALAPPDATA\ql-venv-{digest}"
            python = rf"{where}\Scripts\python.exe"
            command = (f"$ErrorActionPreference = 'Stop'; "
                       f"& {ps_quote(self.python)} -m venv \"{where}\"; "
                       f"if ($LASTEXITCODE) {{ exit $LASTEXITCODE }}; "
                       f"& \"{python}\" -m pip install --disable-pip-version-check -q "
                       f"--cache-dir {ps_quote(self.path(cache))} "
                       f"-r {ps_quote(self.path(stage / 'requirements.txt'))}; "
                       f"if ($LASTEXITCODE) {{ exit $LASTEXITCODE }}; "
                       f"Write-Output \"{python}\"")
        else:
            where = f"$HOME/.ql-venv-{digest}"
            python = f"{where}/bin/python"
            command = (f"set -e; {sh_quote(self.python)} -m venv \"{where}\"; "
                       f"\"{python}\" -m pip install --disable-pip-version-check -q "
                       f"--cache-dir {sh_quote(self.path(cache))} "
                       f"-r {sh_quote(self.path(stage / 'requirements.txt'))}; "
                       f"echo \"{python}\"")
        said = self.ssh(command, timeout=timeout)
        if said.returncode != 0:
            raise GuestError(f"could not install the run's packages in the VM:\n"
                             f"{said.stdout[-1500:]}{said.stderr[-1500:]}")
        return said.stdout.strip().splitlines()[-1].strip()

    def run_in_session(self, stage: pathlib.Path, task: str, python: str,
                       script: pathlib.Path, *arguments: str) -> None:
        """Windows: start ``script`` (on the stage) with ``python`` - a
        ``pythonw.exe``, which opens no console window on that desktop - in
        the logged-in user's desktop session, and return.

        A scheduled task, run interactively, is how a process gets into that
        session from SSH, where a window it opens is seen and EnumWindows
        finds it. The task is XML, not schtasks /tr: the program and its
        arguments stay apart, so nothing has to survive PowerShell's quoting
        of a native command line - and the ScheduledTasks cmdlets need CIM,
        which refuses a standard user over SSH. The task is left defined;
        :meth:`forget_task` removes it."""
        if not self.windows:
            raise GuestError("run_in_session is for a Windows guest; on macOS, start "
                             "the app with `open`, which reaches the desktop session")
        definition = stage / f"{task}.xml"
        definition.write_text(task_xml(
            python, " ".join(f'"{a}"' for a in ("-s", self.path(script), *arguments))),
            encoding="utf-16")
        quoted = ps_quote(task)
        said = self.ssh(f"schtasks /create /tn {quoted} /xml "
                        f"{ps_quote(self.path(definition))} /f; schtasks /run /tn {quoted}")
        if "SUCCESS: Attempted to run" not in said.stdout:
            raise GuestError(f"could not run {script.name} in the VM's desktop session:\n"
                             f"{said.stdout}{said.stderr}")

    def launch(self, stage: pathlib.Path, task: str, python: str, *,
               script: str, log: pathlib.Path, environ: dict | None = None,
               path: list[str] | None = None, cwd: str | None = None,
               argv: list[str] | None = None) -> None:
        """Windows: run ``script`` (a guest path) as ``__main__`` in the
        desktop session, through ``boot/launch.py``: ``environ`` set, ``path``
        put in front of ``sys.path``, ``cwd`` entered, stdout and stderr into
        ``log`` (on the share), ``argv`` as its arguments. ``python`` should be
        a ``pythonw.exe``: a console window would open on the desktop the room
        looks at."""
        settings = {"log": self.path(log), "script": script,
                    "environ": dict(environ or {}), "path": list(path or []),
                    "cwd": cwd, "argv": list(argv or [])}
        launch = stage / f"{task}.json"
        launch.write_text(json.dumps(settings), encoding="utf-8")
        self.run_in_session(stage, task, python, self.boot_script(stage, "launch.py"),
                            self.path(launch))

    def forget_task(self, task: str) -> None:
        if self.windows:
            self.ssh(f"schtasks /delete /tn {ps_quote(task)} /f")

    def windowless(self, python: str) -> str:
        """``python``'s ``pythonw.exe`` beside it, on Windows."""
        if self.windows and python.lower().endswith("python.exe"):
            return python[:-len("python.exe")] + "pythonw.exe"
        return python


def task_xml(command: str, arguments: str) -> str:
    """A scheduled task that runs ``command`` in the creating user's desktop
    session (InteractiveToken), with no time limit."""
    from xml.sax.saxutils import escape
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def listening(port: int) -> bool:
    """Whether something answers on the host's 127.0.0.1:port."""
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def end_tunnels(stage: pathlib.Path) -> None:
    """The reverse tunnels :mod:`quality_loop.guest.screens` started for the
    screens' pages: it records each one's pid on the stage, and the operator
    that started them is gone by the run's end."""
    for pid_file in (stage / "tunnels").glob("*.pid"):
        try:
            os.kill(int(pid_file.read_text()), 15)
        except (OSError, ValueError):
            pass


# --- the machines -----------------------------------------------------------------

class TartMachine:
    """A Tart VM cloned from the base for this run, and deleted after it.

    Its share is ``tart run --dir``, tagged with the last part of the share's
    guest side (``/Volumes/My Shared Files/qa`` -> ``qa``). Shown in a window
    when ``visible = true``; watch it, but do not type into it.
    """

    def __init__(self, guest: Guest, patience: float = 240.0):
        self.guest, self.patience = guest, patience
        self.base = guest.settings["tart"]
        self.name = f"{self.base}-run-{os.getpid()}"
        self.process = None

    def _tart(self, *args, check=True) -> subprocess.CompletedProcess:
        said = subprocess.run(["tart", *args], capture_output=True, text=True)
        if check and said.returncode != 0:
            raise GuestError(f"tart {' '.join(args)}: {said.stderr.strip()}")
        return said

    def __enter__(self):
        self._tart("clone", self.base, self.name)
        tag = posixpath.basename(self.guest.guest_share.rstrip("/"))
        args = ["tart", "run", f"--dir={tag}:{self.guest.host_share}", self.name]
        if not self.guest.settings.get("visible"):
            args.insert(2, "--no-graphics")
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + self.patience
        while time.monotonic() < deadline:
            said = self._tart("ip", self.name, check=False)
            if said.returncode == 0 and said.stdout.strip():
                self.guest.hostname = said.stdout.strip()
                break
            time.sleep(2)
        if self.guest.hostname is None or not self.guest.reachable(
                max(10.0, deadline - time.monotonic())):
            self.__exit__()
            raise GuestError(f"the clone {self.name} of {self.base} did not come up")
        print(f"vm:      {self.name}, a clone of {self.base}, at {self.guest.hostname}")
        return self

    def __exit__(self, *exc):
        self._tart("stop", self.name, check=False)
        if self.process is not None:
            try:
                self.process.wait(30)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self._tart("delete", self.name, check=False)
        self.guest.hostname = None
        print(f"vm:      {self.name} deleted")
        return False


class VMwareMachine:
    """A VMware Fusion VM reverted to a snapshot before the run.

    A snapshot taken while the VM was running comes back running, signed in
    and with SSH up, after `vmrun start`. The SMB share that was mounted on
    the host does not survive the revert, so it is mounted again. The VM is
    shut down afterwards, its share unmounted first: the next run reverts it
    anyway, and a VM `vmrun` left running headless is one the Fusion app
    cannot open. ``visible`` has no say here: `vmrun` can only resume it
    without a window. ``vm_password`` is the VM's encryption password, which
    `vmrun` needs for a VM with a vTPM.

    Learnt on Fusion 26 with a vTPM-encrypted Windows 11 VM: `vmrun` cannot
    linked-clone it ("Cannot read the virtual machine configuration file"),
    nor snapshot it while it runs ("Authentication for encrypted virtual
    machine failed") - take a running-state snapshot in the Fusion app, after
    `vmrun suspend` (a headless VM does not show there).
    """

    VMRUN = "/Applications/VMware Fusion.app/Contents/Library/vmrun"

    def __init__(self, guest: Guest, patience: float = 180.0):
        self.guest, self.patience = guest, patience
        settings = guest.settings
        self.vmx = str(pathlib.Path(settings["vmx"]).expanduser())
        self.snapshot = settings["snapshot"]
        self.password = settings.get("vm_password")

    def _vmrun(self, *args, check: bool = True) -> bool:
        command = [self.VMRUN, "-T", "fusion"]
        if self.password:
            command += ["-vp", secret(self.password)]
        # Into a file, not a pipe: `vmrun start` hands its stdout on to the
        # vmware-vmx it starts, so a pipe would not close until the VM stops.
        with tempfile.TemporaryFile("w+") as output:
            said = subprocess.run(command + list(args), stdin=subprocess.DEVNULL,
                                  stdout=output, stderr=subprocess.STDOUT, text=True)
            output.seek(0)
            if said.returncode != 0 and check:
                raise GuestError(f"vmrun {args[0]}: {output.read().strip()}")
            return said.returncode == 0

    def __enter__(self):
        self._vmrun("revertToSnapshot", self.vmx, self.snapshot)
        # nogui: start with no argument means gui, which Fusion refuses for a
        # VM a running-state snapshot left suspended ("The operation is not
        # supported"). Opening Fusion afterwards shows the running VM.
        self._vmrun("start", self.vmx, "nogui")
        if not self.guest.reachable(self.patience):
            raise GuestError(f"{self.guest.alias} did not answer over SSH after the revert "
                             f"to {self.snapshot!r}")
        self._mount()
        self._wait_for_the_clock()
        print(f"vm:      {self.guest.alias} reverted to {self.snapshot!r}")
        return self

    def _mount(self) -> None:
        url = self.guest.settings.get("smb")
        if not url:
            return
        mount = str(self.guest.host_share)
        subprocess.run(["umount", mount], capture_output=True)
        password = self.guest.settings.get("smb_password")
        if password:
            user, _, where = url.removeprefix("//").partition("@")
            url = f"//{user}:{urllib.parse.quote(secret(password), safe='')}@{where}"
        # -N: never prompt. Without smb_password, the Keychain's internet
        # password for the server (Finder's "Remember") has to do.
        said = subprocess.run(["mount_smbfs", "-N", url, mount],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if said.returncode != 0:
            raise GuestError(f"could not mount the share on {mount}: {said.stderr.strip()}")

    def _wait_for_the_clock(self, patience: float = 60.0) -> None:
        """A snapshot comes back with the time it was taken; VMware Tools
        sets it right within seconds. Wait for that, so the run's own record
        of times means something."""
        deadline = time.monotonic() + patience
        while time.monotonic() < deadline:
            said = self.guest.ssh("[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"
                                  if self.guest.windows else "date +%s")
            try:
                if abs(int(said.stdout.strip()) - time.time()) < 30:
                    return
            except ValueError:
                pass
            time.sleep(3)
        print("vm:      the guest's clock is still off - carrying on")

    def __exit__(self, *exc):
        if self.guest.settings.get("smb"):
            subprocess.run(["umount", str(self.guest.host_share)], capture_output=True)
        # hard: the snapshot it is reverted to next time is all that counts.
        if self._vmrun("stop", self.vmx, "hard", check=False):
            print(f"vm:      {self.guest.alias} stopped")
        else:
            print(f"vm:      could not stop {self.guest.alias} - stop it before opening Fusion")
        return False
