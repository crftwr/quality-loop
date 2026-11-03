"""The guest layer, without a VM: SSH is faked, and what runs in the guest -
the boot scripts - is run here, on the stage it would read in the guest.

A real VM is checked by the products that use it (Keyhac's and XeFM's qa/).
"""

import json
import pathlib
import subprocess
import sys

import pytest

from quality_loop import guest as guests
from quality_loop.guest import Guest, GuestError
from quality_loop.guest import screens as guest_screens
from quality_loop.screens import ScreenError


@pytest.fixture
def share(tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    return share.resolve()


def _guest(share, windows=False, **settings):
    guest = Guest("qa-test", share, r"C:\qa" if windows else str(share),
                  {"python": sys.executable, **settings})
    guest._system = "Windows" if windows else "Darwin"
    return guest


class FakeSSH:
    """Records commands; answers with ``answer(command)``."""

    def __init__(self, answer=lambda command: ("", 0)):
        self.commands, self.answer = [], answer

    def __call__(self, command, timeout=60):
        self.commands.append(command)
        out, code = self.answer(command)
        return subprocess.CompletedProcess([], code, out, "")


# --- settings ---------------------------------------------------------------------

def test_settings_by_alias_from_the_named_file(tmp_path, monkeypatch, share):
    where = tmp_path / "guests.toml"
    where.write_text(f'[qa-win]\nshare = "{share}=C:\\\\qa"\npython = "C:\\\\P\\\\python.exe"\n')
    monkeypatch.setenv("QUALITY_LOOP_GUESTS", str(where))
    assert guests.settings_for("qa-win")["python"] == r"C:\P\python.exe"
    assert guests.settings_for("nobody") == {}
    monkeypatch.setenv("QA_GUEST", "qa-win")
    guest = Guest.from_environment("QA_GUEST")
    assert (guest.host_share, guest.guest_share) == (share, r"C:\qa")
    assert Guest.from_environment("UNSET_QA_GUEST") is None


def test_a_share_needs_both_sides_and_an_existing_host_side(share):
    with pytest.raises(GuestError, match="share ="):
        Guest.from_settings("x", {"share": str(share)})
    with pytest.raises(GuestError, match="not a directory"):
        Guest.from_settings("x", {"share": f"{share}/missing=C:\\qa"})


def test_python_must_be_named(share):
    guest = Guest("x", share, "C:\\qa", {})
    with pytest.raises(GuestError, match="python ="):
        guest.python


def test_a_keychain_secret_is_read_and_anything_else_passes(monkeypatch):
    assert guests.secret("plain") == "plain"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, "s3cret\n", ""))
    assert guests.secret("keychain:qa-vm") == "s3cret"


# --- paths and quoting ---------------------------------------------------------------

def test_a_host_path_as_the_guest_sees_it(share):
    (share / "stage").mkdir()
    assert _guest(share, windows=True).path(share / "stage" / "a.json") == r"C:\qa\stage\a.json"
    assert _guest(share).path(share / "stage") == f"{share}/stage"


def test_the_task_keeps_program_and_arguments_apart():
    xml = guests.task_xml(r"C:\P\pythonw.exe", '"-s" "C:\\qa\\a & b.py"')
    assert "<Command>C:\\P\\pythonw.exe</Command>" in xml
    assert "a &amp; b.py" in xml and "InteractiveToken" in xml


def test_quoting():
    assert guests.ps_quote("it's") == "'it''s'"
    assert guests.sh_quote("it's") == "'it'\\''s'"


def test_windowless_is_pythonw_beside_it(share):
    assert _guest(share, windows=True).windowless(r"C:\P\python.exe") == r"C:\P\pythonw.exe"
    assert _guest(share).windowless("/usr/bin/python3") == "/usr/bin/python3"


# --- the stage, the venv, the session --------------------------------------------------

def test_the_stage_carries_the_screens_and_the_boot_scripts(share):
    stage = _guest(share).stage()
    ql = stage / "ql" / "quality_loop"
    assert (ql / "__init__.py").exists() and (ql / "screens" / "_windows.py").exists()
    assert _guest(share).boot_script(stage, "screen_agent.py").exists()
    assert not list(stage.rglob("__pycache__"))


def test_the_venv_is_made_in_the_guest_with_the_cache_on_the_share(share, monkeypatch):
    guest = _guest(share, windows=True, python=r"C:\Python314\python.exe")
    ssh = FakeSSH(lambda c: ("C:\\Users\\qa\\AppData\\Local\\ql-venv-x\\Scripts\\python.exe\n", 0))
    monkeypatch.setattr(guest, "ssh", ssh)
    stage = guest.stage()
    python = guest.venv(stage, ["pillow>=9", "truststore"])
    assert python.endswith(r"Scripts\python.exe")
    (command,) = ssh.commands
    assert r"'C:\Python314\python.exe' -m venv" in command
    assert r"--cache-dir 'C:\qa\.pip-cache'" in command
    assert (share / ".pip-cache").is_dir()
    assert (stage / "requirements.txt").read_text() == "pillow>=9\ntruststore\n"


def test_a_failed_install_says_what_pip_said(share, monkeypatch):
    guest = _guest(share)
    monkeypatch.setattr(guest, "ssh", FakeSSH(lambda c: ("No matching distribution", 1)))
    with pytest.raises(GuestError, match="No matching distribution"):
        guest.venv(guest.stage(), ["nothing-like-this"])


def test_run_in_session_is_a_task_and_launch_hands_it_the_json(share, monkeypatch):
    guest = _guest(share, windows=True)
    ssh = FakeSSH(lambda c: ("SUCCESS: Attempted to run the scheduled task", 0))
    monkeypatch.setattr(guest, "ssh", ssh)
    stage = guest.stage()
    guest.launch(stage, "ql-app", r"C:\P\pythonw.exe", script=r"C:\qa\app.py",
                 log=stage / "app.log", environ={"HOME": r"C:\qa\home"}, argv=["--x"])
    (command,) = ssh.commands
    assert "schtasks /create /tn 'ql-app'" in command and "schtasks /run" in command
    launch = json.loads((stage / "ql-app.json").read_text())
    assert launch["environ"] == {"HOME": r"C:\qa\home"} and launch["argv"] == ["--x"]
    assert "launch.py" in (stage / "ql-app.xml").read_text(encoding="utf-16")


def test_run_in_session_says_when_the_task_did_not_start(share, monkeypatch):
    guest = _guest(share, windows=True)
    monkeypatch.setattr(guest, "ssh", FakeSSH(lambda c: ("ERROR: Access is denied.", 0)))
    with pytest.raises(GuestError, match="Access is denied"):
        guest.run_in_session(guest.stage(), "t", "pythonw.exe", share / "x.py")
    with pytest.raises(GuestError, match="Windows guest"):
        _guest(share).run_in_session(share, "t", "python", share / "x.py")


def test_launch_runs_the_script_with_its_environment_path_and_log(share, tmp_path):
    """boot/launch.py itself, run here as the task would run it there."""
    stage = _guest(share).stage()
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "helper.py").write_text("WHO = 'staged'\n")
    script = tmp_path / "app.py"
    script.write_text("import os, sys, helper\n"
                      "print(helper.WHO, os.environ['QL_X'], sys.argv[1:], os.getcwd())\n")
    settings = {"log": str(stage / "app.log"), "script": str(script),
                "environ": {"QL_X": "set"}, "path": [str(lib)], "cwd": str(tmp_path),
                "argv": ["--flag"]}
    (stage / "launch.json").write_text(json.dumps(settings))
    subprocess.run([sys.executable, "-s", str(_guest(share).boot_script(stage, "launch.py")),
                    str(stage / "launch.json")], check=True)
    assert (stage / "app.log").read_text().strip() == f"staged set ['--flag'] {tmp_path}"


# --- the screen backend ----------------------------------------------------------------

def test_the_backend_runs_the_agent_in_the_guest_and_reads_its_answer(share, monkeypatch):
    """macOS shape: the agent over SSH - here, run locally on the stage."""
    guest = _guest(share)
    stage = guest.stage()
    settings = guest_screens.settings(guest, stage)
    assert settings["terminal_python"] == sys.executable
    guest_screens.configure(settings)

    def run_agent(command, timeout=60):
        agent = guest.boot_script(stage, "screen_agent.py")
        asked = command.rsplit(" ", 1)[1].strip("'")
        return subprocess.run([sys.executable, str(agent), asked],
                              capture_output=True, text=True)

    monkeypatch.setattr(guest_screens._guest, "ssh", run_agent)
    with pytest.raises(ScreenError, match="no operation 'paint'"):
        guest_screens._call({"op": "paint"}, patience=5)
    assert not list((stage / "screens").iterdir()), "the request and answer are cleaned up"


def test_a_terminal_script_is_staged_and_run_with_the_guest_python(share, monkeypatch, tmp_path):
    guest = _guest(share)
    stage = guest.stage()
    guest_screens.configure(guest_screens.settings(guest, stage, terminal_python="/g/python"))
    seen = {}
    monkeypatch.setattr(guest_screens, "_call", lambda request, patience: seen.update(request))
    script = tmp_path / "deploy.py"
    script.write_text("print('x')\n")
    guest_screens.open_terminal(["/host/python", str(script)], "deploy", 5)
    assert seen["command"] == ["/g/python", str(stage / "scripts" / "deploy.py")]
    assert (stage / "scripts" / "deploy.py").exists()


def test_a_booted_windows_guest_is_waited_for_until_its_desktop_has_settled(share, monkeypatch):
    """A powered-off snapshot boots: SSH answers before the automatic sign-in
    has made the desktop, and then its startup programs run."""
    guest = _guest(share, windows=True, vmx="/v.vmx", snapshot="s")
    answers = iter(["-1", "-1", "4", "16"])
    ssh = FakeSSH(lambda c: (next(answers) + "\n", 0))
    monkeypatch.setattr(guest, "ssh", ssh)
    slept = []
    monkeypatch.setattr(guests.time, "sleep", slept.append)
    guests.VMwareMachine(guest)._wait_for_the_desktop(settle=15)
    assert len(ssh.commands) == 4 and "explorer" in ssh.commands[0]
    assert slept == [3.0, 3.0, 11]


def test_no_desktop_is_an_error_that_names_automatic_sign_in(share, monkeypatch):
    guest = _guest(share, windows=True, vmx="/v.vmx", snapshot="s")
    monkeypatch.setattr(guest, "ssh", FakeSSH(lambda c: ("-1\n", 0)))
    clock = iter(range(0, 1000, 50))
    monkeypatch.setattr(guests.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(guests.time, "sleep", lambda s: None)
    with pytest.raises(GuestError, match="automatic sign-in"):
        guests.VMwareMachine(guest, patience=120)._wait_for_the_desktop()


def test_machine_follows_the_settings(share):
    assert isinstance(_guest(share, tart="base").machine(), guests.TartMachine)
    assert isinstance(_guest(share, vmx="/v.vmx", snapshot="s").machine(), guests.VMwareMachine)
    with _guest(share).machine():
        pass


# --- Linux, and a container --------------------------------------------------------

def test_the_system_is_asked_once_and_linux_is_not_windows(share, monkeypatch):
    for answer, platform in (("Linux", "linux"), ("Darwin", "darwin"), ("", "win32")):
        guest = Guest("qa-test", share, str(share), {"python": "python3"})
        fake = FakeSSH(lambda command, a=answer: (a + "\n", 0))
        monkeypatch.setattr(guest, "ssh", fake)
        assert guest.platform == platform and guest.platform == platform
        assert guest.windows == (platform == "win32")
        assert fake.commands == ["uname -s"]


def test_a_docker_guest_runs_its_commands_through_docker_exec(share):
    guest = _guest(share, docker="python:3.13-slim")
    assert isinstance(guest.machine(), guests.DockerMachine)
    with pytest.raises(GuestError, match="not up"):
        guest.argv("true")
    guest.hostname = "ql-qa-test-1"
    assert guest.argv("echo hi") == ["docker", "exec", "ql-qa-test-1", "sh", "-c", "echo hi"]
    with pytest.raises(GuestError, match="no SSH tunnels"):
        guest.forward(8000)


def test_the_container_mounts_the_share_and_is_removed_after(share, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "id\n", "")

    monkeypatch.setattr(guests.subprocess, "run", run)
    guest = _guest(share, docker="python:3.13-slim")
    with guest.machine() as machine:
        assert guest.hostname == machine.name
        started = calls[0]
        assert started[:2] == ["docker", "run"] and f"{share}:{share}" in started
        assert started[started.index("--entrypoint") + 1] == "sleep"
    assert calls[-1] == ["docker", "rm", "-f", machine.name]
    assert guest.hostname is None


# --- the suite runner ---------------------------------------------------------------

class LocalGuest(Guest):
    """A POSIX guest that is this machine: its shell commands run here."""

    def argv(self, command):
        return ["sh", "-c", command]


def test_run_pytest_runs_the_suite_in_the_guest_and_keeps_its_log_and_junit(share, tmp_path):
    from quality_loop.guest import suite
    guest = LocalGuest("qa-local", share, str(share), {"python": sys.executable})
    guest._system = "Linux"
    stage = guest.stage("ql-suite-")
    tree = stage / "tree"
    tree.mkdir()
    (tree / "test_here.py").write_text(
        "import os\n"
        "def test_sees_the_guest():\n"
        "    assert os.environ['QUALITY_LOOP_IN_GUEST'] == 'qa-local'\n"
        "    assert os.environ['EXTRA'] == 'yes'\n", encoding="utf-8")
    results = tmp_path / "results"
    code = suite.run_pytest(guest, stage, sys.executable, ["-q", "test_here.py"],
                            cwd=guest.path(tree), results=results, environ={"EXTRA": "yes"})
    assert code == 0
    assert "1 passed" in (results / "pytest.log").read_text()
    assert "testcase" in (results / "junit.xml").read_text()


def test_run_pytest_answers_3_when_the_runner_never_reports(share, tmp_path):
    from quality_loop.guest import suite

    class Silent(LocalGuest):
        def argv(self, command):
            return ["sh", "-c", "echo gone"]

    guest = Silent("qa-local", share, str(share), {"python": sys.executable})
    guest._system = "Darwin"
    stage = guest.stage("ql-suite-")
    assert suite.run_pytest(guest, stage, sys.executable, [], cwd=str(stage),
                            results=tmp_path / "r") == 3
    assert "gone" in (tmp_path / "r" / "pytest.log").read_text()
