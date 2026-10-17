"""Screens open by name only, close only what was opened, on either OS.

The OS-driving halves are tested by what they would run; the live test opens
real windows and runs only when asked (QUALITY_LOOP_LIVE=1), on the OS it
drives.
"""

import json
import os
import sys

import pytest

from quality_loop import __main__ as cli
from quality_loop import screens
from quality_loop.screens import Page, Terminal, _mac, _windows


class FakeOS:
    def __init__(self):
        self.calls = []

    def open_page(self, url, title, patience):
        self.calls.append(("page", url, title))
        return 101

    def open_terminal(self, command, title, patience):
        self.calls.append(("terminal", command, title))
        return 202

    def close(self, kind, handle):
        self.calls.append(("close", kind, handle))


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "deploy.py").write_text("print('deploying')\n")
    path = screens.write_manifest(
        tmp_path / "manifest.json",
        {"approval-queue": Page("dialog.html", title="Approval queue"),
         "deploy": Terminal("deploy.py", title="deploy - acme")},
        fixtures=fixtures, origin="http://127.0.0.1:5000", python="/venv/python",
        state=tmp_path / "operator")
    monkeypatch.setenv(screens.MANIFEST, str(path))
    return tmp_path


def test_a_page_opens_at_its_served_address_and_is_recorded(manifest):
    fake = FakeOS()
    record = screens.open_screen("approval-queue", os_backend=fake)
    assert fake.calls == [("page", "http://127.0.0.1:5000/dialog.html", "Approval queue")]
    assert record["id"] == "approval-queue-1" and record["handle"] == 101
    saved = json.loads((manifest / "operator" / "screens.json").read_text())
    assert [r["id"] for r in saved] == ["approval-queue-1"]


def test_a_terminal_script_runs_from_a_copy_outside_the_fixtures(manifest):
    fake = FakeOS()
    screens.open_screen("deploy", os_backend=fake)
    _kind, command, title = fake.calls[0]
    assert command[0] == "/venv/python" and command[1].endswith("deploy.py")
    assert str(manifest / "fixtures") not in command[1], "a copy, not the fixture"
    assert title == "deploy - acme"


def test_only_declared_names_open(manifest):
    with pytest.raises(screens.ScreenError, match="declares: approval-queue, deploy"):
        screens.open_screen("/etc/passwd", os_backend=FakeOS())


def test_only_what_was_opened_closes(manifest):
    fake = FakeOS()
    screens.open_screen("approval-queue", os_backend=fake)
    screens.open_screen("deploy", os_backend=fake)
    with pytest.raises(screens.ScreenError, match="was not opened here"):
        screens.close_screen("someone-elses-window", os_backend=fake)
    screens.close_screen("approval-queue-1", os_backend=fake)
    assert fake.calls[-1] == ("close", "page", 101)
    assert screens.close_all(manifest / "operator", os_backend=fake) == ["deploy-2"]
    assert fake.calls[-1] == ("close", "terminal", 202)
    assert screens.close_all(manifest / "operator", os_backend=fake) == []


def test_the_command_line_answers_json_and_refuses_in_one_line(manifest, capsys):
    assert cli.main(["screen", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "approval-queue": {"kind": "page", "title": "Approval queue"},
        "deploy": {"kind": "terminal", "title": "deploy - acme"}}
    assert cli.main(["screen", "close", "nothing-1"]) == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_without_a_manifest_nothing_opens(monkeypatch):
    monkeypatch.delenv(screens.MANIFEST, raising=False)
    with pytest.raises(screens.ScreenError, match="the runner sets it"):
        screens.names()


def test_the_macos_scripts_quote_what_they_are_given():
    page = _mac.page_script('http://127.0.0.1:1/a"b.html')
    assert 'set URL of front document to "http://127.0.0.1:1/a\\"b.html"' in page
    assert "return id of front window" in page
    terminal = _mac.terminal_script(["/venv/python", "/tmp/it's.py"], 'deploy "acme"')
    assert "'/tmp/it'\\\\''s.py'" in terminal
    assert 'set custom title of t to "deploy \\"acme\\""' in terminal


def test_the_windows_commands():
    assert _windows.page_command("http://127.0.0.1:1/q.html") == [
        "cmd", "/c", "start", "", "msedge", "--new-window", "http://127.0.0.1:1/q.html"]
    assert _windows.terminal_command(["py.exe", "d.py"], "deploy - acme") == [
        "wt.exe", "-w", "new", "--title", "deploy - acme",
        "--suppressApplicationTitle", "py.exe", "d.py"]


def test_on_windows_only_a_new_window_with_the_title_counts():
    """A window of the operator's that happens to carry the title is not it."""
    shown = [{1: "deploy - acme (theirs)"},
             {1: "deploy - acme (theirs)", 2: "something else"},
             {1: "deploy - acme (theirs)", 2: "something else", 3: "deploy - acme"}]
    listing = iter(shown).__next__
    launched = []
    handle = _windows._launch_and_find(["wt.exe"], "deploy - acme", 5,
                                       listing=listing,
                                       run=lambda *a, **k: launched.append(a))
    assert handle == 3 and launched


@pytest.mark.skipif(os.environ.get("QUALITY_LOOP_LIVE") != "1",
                    reason="opens real windows; QUALITY_LOOP_LIVE=1 to run")
def test_live_a_page_opens_and_closes(tmp_path, monkeypatch):
    from quality_loop.pages import Pages

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "live.html").write_text("<title>quality-loop live check</title>ok")
    with Pages(fixtures) as served:
        path = screens.write_manifest(
            tmp_path / "manifest.json",
            {"live": Page("live.html", title="quality-loop live check")},
            fixtures=fixtures, origin=served.origin, python=sys.executable,
            state=tmp_path / "operator")
        monkeypatch.setenv(screens.MANIFEST, str(path))
        record = screens.open_screen("live")
        screens.close_screen(record["id"])


@pytest.mark.skipif(os.environ.get("QUALITY_LOOP_LIVE") != "1",
                    reason="opens real windows; QUALITY_LOOP_LIVE=1 to run")
def test_live_a_terminal_opens_with_its_title_and_closes(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "hello.py").write_text("print('quality-loop live check')\n")
    path = screens.write_manifest(
        tmp_path / "manifest.json",
        {"hello": Terminal("hello.py", title="quality-loop live terminal")},
        fixtures=fixtures, origin="", python=sys.executable, state=tmp_path / "operator")
    monkeypatch.setenv(screens.MANIFEST, str(path))
    record = screens.open_screen("hello")
    screens.close_screen(record["id"])
