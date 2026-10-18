"""Driving an app: the key notation, a terminal app in a pty, and the record."""

import json
import os
import sys
import textwrap

import pytest

from quality_loop import drive, mcp
from quality_loop.drive import keys

posix_only = pytest.mark.skipif(os.name == "nt", reason="the pty backend is POSIX only")


# --- notation --------------------------------------------------------------------

def test_keys_are_read_in_keyhac_s_notation():
    assert keys.parse("Ctrl-Shift-G") == keys.Key("G", frozenset({"ctrl", "shift"}))
    assert keys.parse("option-left") == keys.Key("Left", frozenset({"alt"}))
    assert keys.parse("Ctrl--") == keys.Key("-", frozenset({"ctrl"}))
    assert keys.parse("-") == keys.Key("-")
    assert str(keys.parse("shift-ctrl-f5")) == "Ctrl-Shift-F5"
    with pytest.raises(keys.KeysError):
        keys.parse("Hyper-A")
    with pytest.raises(keys.KeysError):
        keys.parse("Ctrl-Banana")


def test_a_sequence_takes_text_and_pauses():
    found = keys.sequence(["Ctrl-G", {"text": "trip"}, {"pause": 0.1}, "Enter"])
    assert keys.describe(found) == ["Ctrl-G", {"text": "trip"}, {"pause": 0.1}, "Enter"]
    with pytest.raises(keys.KeysError):
        keys.sequence([{"click": 1}])


def test_a_terminal_gets_what_an_xterm_sends():
    as_bytes = lambda token: keys.terminal_bytes(keys.parse(token))  # noqa: E731
    assert as_bytes("Ctrl-C") == b"\x03"
    assert as_bytes("Ctrl-Shift-G") == b"\x07", "a terminal cannot tell it from Ctrl-G"
    assert as_bytes("Alt-x") == b"\x1bx"
    assert as_bytes("Up") == b"\x1b[A"
    assert as_bytes("Ctrl-Right") == b"\x1b[1;5C"
    assert as_bytes("F1") == b"\x1bOP" and as_bytes("F5") == b"\x1b[15~"
    assert as_bytes("Shift-Tab") == b"\x1b[Z"
    assert as_bytes("Enter") == b"\r" and as_bytes("Backspace") == b"\x7f"
    assert as_bytes("Shift-a") == b"A" and as_bytes("G") == b"g"
    with pytest.raises(keys.KeysError):
        as_bytes("Cmd-S")


# --- a terminal app --------------------------------------------------------------

APP = textwrap.dedent('''
    import json, os, sys, termios, tty
    events = os.environ.get("QUALITY_LOOP_EVENTS")
    def event(**fact):
        if events:
            with open(events, "a") as out:
                out.write(json.dumps(fact) + "\\n")
    tty.setraw(sys.stdin.fileno())
    sys.stdout.write("\\x1b[2J\\x1b[Hlist> ")
    sys.stdout.flush()
    typed = ""
    while True:
        ch = os.read(0, 1).decode()
        if ch == "\\x11":
            event(kind="quit")
            break
        if ch == "\\r":
            event(kind="added", item=typed)
            sys.stdout.write("\\r\\nadded " + typed + "\\r\\nlist> ")
            typed = ""
        else:
            typed += ch
            sys.stdout.write(ch)
        sys.stdout.flush()
''')


@pytest.fixture
def app_file(tmp_path):
    path = tmp_path / "listapp.py"
    path.write_text(APP)
    return path


@posix_only
def test_a_terminal_app_is_driven_and_every_step_recorded(tmp_path, app_file):
    pytest.importorskip("pyte")
    apps = drive.manifest_entries(
        {"lister": drive.TerminalApp([sys.executable, str(app_file)], rows=10, cols=40)})
    driver = drive.Driver(apps, tmp_path / "record")
    started = driver.start("lister", "open it")
    assert started["screen"].startswith("list>")
    with pytest.raises(drive.DriveError, match="intent"):
        driver.keys(started["id"], ["a"], "")
    after = driver.keys(started["id"], [{"text": "milk"}, "Enter"], "add milk to the list")
    assert "added milk" in after["screen"]
    assert after["events"] == [{"kind": "added", "item": "milk"}]
    silent = driver.keys(started["id"], [{"pause": 0.0}], "a step the app does not answer")
    assert silent["settled"]
    driver.keys(started["id"], ["Ctrl-Q"], "quit")
    driver.stop_all()
    steps = [json.loads(line) for line in
             (tmp_path / "record" / "steps.jsonl").read_text().splitlines()]
    assert [s["action"] for s in steps] == ["start", "keys", "keys", "keys", "stop"]
    assert steps[2]["waited"] >= 0.35, "quiet is counted from the key, not from before it"
    assert steps[1]["keys"] == [{"text": "milk"}, "Enter"]
    assert steps[1]["intent"] == "add milk to the list"
    assert steps[0]["size"] == [10, 40]
    assert "added milk" in (tmp_path / "record" / steps[1]["screen_file"]).read_text()


def test_unknown_apps_and_ids_are_refused(tmp_path):
    driver = drive.Driver({}, tmp_path / "record")
    with pytest.raises(drive.DriveError, match="no app"):
        driver.start("nothing")
    with pytest.raises(drive.DriveError, match="no running app"):
        driver.keys("nothing-1", ["a"], "why")


def test_key_remappers_are_noticed():
    assert drive.remappers(["Finder", "keyhac", "Karabiner_Grabber"]) == [
        "karabiner_grabber", "keyhac"]
    assert drive.remappers(["AutoHotkey64.exe"]) == ["autohotkey"]
    assert drive.remappers(["bash"]) == []


# --- the MCP server --------------------------------------------------------------

def test_the_tool_list_follows_the_manifest():
    names = lambda m: [t["name"] for t in mcp.tools(m)]  # noqa: E731
    operator = {"screens": {}, "evidence": {}}
    assert names(operator) == ["screen_list", "screen_open", "screen_close", "evidence"]
    with_apps = {**operator, "apps": {"x": {"kind": "tui"}}, "record": "/r"}
    assert names(with_apps)[-6:] == ["app_list", "app_start", "app_keys", "app_screen",
                                     "app_events", "app_stop"]
    room = {"apps": {"x": {"kind": "tui"}}, "record": "/r"}
    assert all(n.startswith("app_") for n in names(room)), "a room gets the apps only"
    with pytest.raises(mcp.ToolError):
        mcp.call("screen_list", {}, room)


def test_an_image_answer_is_sent_inline(tmp_path):
    image = tmp_path / "001-x.png"
    image.write_bytes(b"\x89PNG fake")
    content = mcp._app_answer({"step": 1, "image": str(image), "screen_file": image.name})
    assert content[0]["type"] == "text" and "image" not in json.loads(content[0]["text"])
    assert content[1]["type"] == "image" and content[1]["mimeType"] == "image/png"


def test_a_png_is_written_without_an_image_library(tmp_path):
    from quality_loop.drive import _windows
    import zlib
    data = _windows.png(2, 1, [b"\xff\x00\x00\x00\xff\x00"])
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and b"IHDR" in data and data.endswith(
        b"IEND\xaeB`\x82")
    start = data.index(b"IDAT") + 4
    length = int.from_bytes(data[start - 8:start - 4], "big")
    assert zlib.decompress(data[start:start + length]) == b"\x00\xff\x00\x00\x00\xff\x00"


def test_windows_key_events_hold_modifiers_around_the_key():
    from quality_loop.drive import _windows

    class INPUT:  # a stand-in for the ctypes structure
        def __init__(self, type):
            self.type = type
            self.u = type_ = __import__("types").SimpleNamespace()
            type_.ki = __import__("types").SimpleNamespace(wVk=0, wScan=0, dwFlags=0)

    events = _windows.events_for(keys.parse("Ctrl-Shift-Left"), INPUT, lambda c: -1)
    order = [(e.u.ki.wVk, bool(e.u.ki.dwFlags & _windows.KEYEVENTF_KEYUP)) for e in events]
    assert order == [(0x11, False), (0x10, False), (0x25, False), (0x25, True),
                     (0x10, True), (0x11, True)]
    assert events[2].u.ki.dwFlags & _windows.KEYEVENTF_EXTENDEDKEY
    text = _windows.events_for(keys.Text("é"), INPUT, lambda c: -1)
    assert [(e.u.ki.wScan, e.u.ki.dwFlags) for e in text] == [
        (0xE9, _windows.KEYEVENTF_UNICODE),
        (0xE9, _windows.KEYEVENTF_UNICODE | _windows.KEYEVENTF_KEYUP)]
    shifted = _windows.events_for(keys.parse("!"), INPUT, lambda c: 0x0131)
    assert [e.u.ki.wVk for e in shifted][:2] == [0x10, 0x31]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS key codes")
def test_mac_key_codes():
    from quality_loop.drive import _mac
    assert _mac.keycode(keys.parse("Cmd-S")) == (1, _mac.FLAGS["cmd"])
    assert _mac.keycode(keys.parse("Shift-G")) == (5, _mac.FLAGS["shift"])
    assert _mac.keycode(keys.parse("G")) == (5, 0), "a letter names the key"
    assert _mac.keycode(keys.parse("F1"))[0] == 122


@posix_only
def test_a_lone_esc_is_not_glued_to_the_next_key(tmp_path):
    """Esc then Ctrl-T, sent 20ms apart, reached XeFM as Alt-Ctrl-T."""
    pytest.importorskip("pyte")
    from quality_loop.drive import terminal
    script = tmp_path / "gaps.py"
    script.write_text(textwrap.dedent('''
        import os, sys, time, tty
        tty.setraw(0)
        last, out = time.monotonic(), []
        while len(out) < 2:
            data = os.read(0, 16)
            now = time.monotonic()
            out.append((data.hex(), round(now - last, 2)))
            last = now
        sys.stdout.write(repr(out) + "\\r\\n")
        sys.stdout.flush()
        time.sleep(5)
    '''))
    app = terminal.PtyApp([sys.executable, str(script)], rows=5, cols=60)
    try:
        app.wait_quiet(patience=5)
        app.send(keys.sequence(["Esc", "Ctrl-T"]))
        app.wait_quiet(patience=5)
        seen = eval(app.text().strip().splitlines()[-1])
    finally:
        app.stop()
    assert [hex_ for hex_, _gap in seen] == ["1b", "14"], "two reads, not one ESC+key burst"
    assert seen[1][1] >= terminal.ESC_SETTLE - 0.05
