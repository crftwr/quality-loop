"""Screens on Windows: Edge for pages, Windows Terminal for scripts.

A window is recognised the same way as on macOS, by its title: the top-level
windows that appear after the launch are enumerated, and the one whose title
contains the declared one is the screen. Its handle is recorded, and closing
posts WM_CLOSE to that handle and nothing else.

Every ctypes prototype is declared explicitly: on 64-bit Windows the default
c_int restype truncates handles.

Not yet confirmed on a Windows machine: that Windows Terminal keeps the title
with --suppressApplicationTitle, that Edge's window title contains the page
title, and that --new-window gives a window rather than a tab.
"""

from __future__ import annotations

import subprocess
import time

from quality_loop.screens import ScreenError

WM_CLOSE = 0x0010


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    return ctypes, user32, enum_proc


def windows() -> dict[int, str]:
    """``{handle: title}`` of the visible top-level windows."""
    ctypes, user32, enum_proc = _user32()
    found: dict[int, str] = {}

    def each(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            found[int(hwnd)] = buffer.value
        return True

    user32.EnumWindows(enum_proc(each), 0)
    return found


def page_command(url: str) -> list[str]:
    return ["cmd", "/c", "start", "", "msedge", "--new-window", url]


def terminal_command(command: list[str], title: str) -> list[str]:
    return ["wt.exe", "-w", "new", "--title", title, "--suppressApplicationTitle",
            *command]


def _launch_and_find(launch: list[str], title: str, patience: float,
                     listing=windows, run=subprocess.Popen) -> int:
    before = set(listing())
    run(launch, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + patience
    while time.monotonic() < deadline:
        for handle, shown in listing().items():
            if handle not in before and title in shown:
                return handle
        time.sleep(0.5)
    raise ScreenError(f"no new window titled {title!r} appeared within {patience:.0f}s")


def open_page(url: str, title: str, patience: float) -> int:
    return _launch_and_find(page_command(url), title, patience)


def open_terminal(command: list[str], title: str, patience: float) -> int:
    return _launch_and_find(terminal_command(command, title), title, patience)


def close(kind: str, handle: int) -> None:
    _ctypes, user32, _proc = _user32()
    if user32.IsWindow(handle):
        user32.PostMessageW(handle, WM_CLOSE, 0, 0)
