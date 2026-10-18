"""Synthetic keys, the frontmost window and screenshots on macOS.

Keys are posted with `CGEventPost` through ctypes; text goes in with
`CGEventKeyboardSetUnicodeString`, so neither the layout (JIS or US) nor an
input method changes what arrives. Windows are found and raised, and the
frontmost one read, through System Events. Screenshots are `screencapture`
of the window's rectangle.

What it needs, granted to the application the run is started from (Terminal,
VS Code): Accessibility, to post keys and to read other apps' windows; and
Screen Recording, for screenshots.
"""

from __future__ import annotations

import ctypes
import pathlib
import subprocess
import time

from quality_loop.drive import keys as keynames


class DesktopError(Exception):
    pass


#: kVK_ANSI_* and the named keys: what the key is, not what it types.
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38,
    "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "`": 50,
    "Enter": 36, "Tab": 48, "Space": 49, "Backspace": 51, "Esc": 53, "Delete": 117,
    "Insert": 114, "Home": 115, "End": 119, "PageUp": 116, "PageDown": 121,
    "Left": 123, "Right": 124, "Down": 125, "Up": 126,
    "F1": 122, "F2": 120, "F3": 99, "F4": 118, "F5": 96, "F6": 97, "F7": 98, "F8": 100,
    "F9": 101, "F10": 109, "F11": 103, "F12": 111, "F13": 105, "F14": 107, "F15": 113,
    "F16": 106, "F17": 64, "F18": 79, "F19": 80, "F20": 90,
}

FLAGS = {"shift": 0x20000, "ctrl": 0x40000, "alt": 0x80000, "cmd": 0x100000}


def _quartz():
    cg = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    cg.CGEventSetFlags.restype = None
    cg.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                   ctypes.POINTER(ctypes.c_uint16)]
    cg.CGEventKeyboardSetUnicodeString.restype = None
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cg.CGEventPost.restype = None
    cg.CFRelease.argtypes = [ctypes.c_void_p]
    cg.CFRelease.restype = None
    cg.AXIsProcessTrusted.argtypes = []
    cg.AXIsProcessTrusted.restype = ctypes.c_bool
    try:
        cg.CGPreflightScreenCaptureAccess.argtypes = []
        cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    except AttributeError:
        pass
    return cg


def _post(cg, code: int, flags: int, down: bool, text: str | None = None) -> None:
    event = cg.CGEventCreateKeyboardEvent(None, code, down)
    if not event:
        raise DesktopError("CGEventCreateKeyboardEvent failed - is Accessibility granted?")
    try:
        cg.CGEventSetFlags(event, flags)
        if text is not None:
            units = text.encode("utf-16-le")
            buffer = (ctypes.c_uint16 * (len(units) // 2)).from_buffer_copy(units)
            cg.CGEventKeyboardSetUnicodeString(event, len(units) // 2, buffer)
        cg.CGEventPost(0, event)  # kCGHIDEventTap
    finally:
        cg.CFRelease(event)


def keycode(key: keynames.Key) -> tuple[int, int]:
    """``(virtual keycode, flags)`` for a key, on a US ANSI layout's codes."""
    name = key.name
    flags = sum(FLAGS[m] for m in key.mods)
    if len(name) == 1:
        name = name.lower()
    if name not in KEYCODES:
        raise DesktopError(f"{key}: no key code for {key.name!r} - send it as text")
    return KEYCODES[name], flags


def send(items: list) -> None:
    cg = _quartz()
    for item in items:
        if isinstance(item, keynames.Pause):
            time.sleep(item.seconds)
            continue
        if isinstance(item, keynames.Text):
            # Twenty UTF-16 units per event is what the call is documented to take.
            text = item.text
            while text:
                chunk, text = text[:20], text[20:]
                _post(cg, 0, 0, True, chunk)
                _post(cg, 0, 0, False, chunk)
                time.sleep(0.01)
            continue
        if len(item.name) == 1 and not item.mods and item.name.lower() not in KEYCODES:
            _post(cg, 0, 0, True, item.name)
            _post(cg, 0, 0, False, item.name)
            continue
        code, flags = keycode(item)
        _post(cg, code, flags, True)
        _post(cg, code, flags, False)
        time.sleep(0.02)


def _osascript(script: str) -> str:
    done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                          check=False)
    if done.returncode != 0:
        raise DesktopError(done.stderr.strip() or "osascript failed")
    return done.stdout.rstrip("\n")


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def windows() -> list[tuple[str, str]]:
    """``(process, window title)`` of every window of every visible process."""
    said = _osascript('''set out to ""
tell application "System Events"
    repeat with p in (every process whose background only is false)
        try
            repeat with w in (every window of p)
                set out to out & (name of p) & tab & (name of w) & linefeed
            end repeat
        end try
    end repeat
end tell
return out''')
    found = []
    for line in said.splitlines():
        process, _tab, title = line.partition("\t")
        found.append((process, title))
    return found


def frontmost() -> tuple[str, str]:
    """``(process, title of its front window)``."""
    said = _osascript('''tell application "System Events"
    set p to first process whose frontmost is true
    set n to name of p
    try
        set t to name of front window of p
    on error
        set t to ""
    end try
    return n & linefeed & t
end tell''')
    process, _nl, title = said.partition("\n")
    return process, title


def find(title: str) -> str | None:
    """The process owning a window whose title contains ``title``."""
    for process, shown in windows():
        if title in shown:
            return process
    return None


def raise_window(process: str, title: str) -> None:
    _osascript(f'''tell application "System Events" to tell process {_q(process)}
    set frontmost to true
    try
        perform action "AXRaise" of (first window whose name contains {_q(title)})
    end try
end tell''')


def bounds(process: str, title: str) -> tuple[int, int, int, int]:
    said = _osascript(f'''tell application "System Events" to tell process {_q(process)}
    set w to first window whose name contains {_q(title)}
    set {{x, y}} to position of w
    set {{a, b}} to size of w
    return (x as text) & "," & (y as text) & "," & (a as text) & "," & (b as text)
end tell''')
    x, y, w, h = (int(float(v)) for v in said.split(","))
    return x, y, w, h


def screenshot(process: str, title: str, path: pathlib.Path) -> pathlib.Path:
    x, y, w, h = bounds(process, title)
    done = subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(path)],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0 or not path.exists():
        raise DesktopError(f"screencapture failed: {done.stderr.strip()} - is Screen "
                           f"Recording granted?")
    return path


def permissions() -> dict:
    """What this process has been granted, as far as it can be asked."""
    cg = _quartz()
    granted = {"accessibility": bool(cg.AXIsProcessTrusted())}
    if hasattr(cg, "CGPreflightScreenCaptureAccess"):
        granted["screen_recording"] = bool(cg.CGPreflightScreenCaptureAccess())
    return granted


def processes() -> list[str]:
    done = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True,
                          check=False)
    return [pathlib.PurePosixPath(line.strip()).name for line in done.stdout.splitlines()
            if line.strip()]
