"""Synthetic keys, the foreground window and screenshots on Windows.

Keys are sent with `SendInput`: shortcuts as virtual keys, text with
KEYEVENTF_UNICODE so the layout and the IME change nothing. Windows are found
with `EnumWindows` by title, as the screens backend finds its own. A
screenshot is the window's rectangle copied off the screen with `BitBlt` and
written as a PNG by hand, since the standard library has no image module.

UIPI: input cannot be sent to a window of an elevated process from one that
is not. Every ctypes prototype is declared: on 64-bit the default c_int
restype truncates handles.

Unit-tested only, pending a run on a Windows machine.
"""

from __future__ import annotations

import pathlib
import struct
import subprocess
import time
import zlib

from quality_loop.drive import keys as keynames


class DesktopError(Exception):
    pass


VK = {"Enter": 0x0D, "Tab": 0x09, "Esc": 0x1B, "Space": 0x20, "Backspace": 0x08,
      "Delete": 0x2E, "Insert": 0x2D, "Home": 0x24, "End": 0x23, "PageUp": 0x21,
      "PageDown": 0x22, "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
      **{f"F{n}": 0x6F + n for n in range(1, 25)}}
MODIFIER_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "cmd": 0x5B}
#: Keys that need KEYEVENTF_EXTENDEDKEY to be told from the numeric keypad's.
EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B}

KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
INPUT_KEYBOARD = 1


def _api():
    import ctypes
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    user32.VkKeyScanW.restype = ctypes.c_short
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                             wintypes.DWORD]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                wintypes.UINT, ctypes.c_void_p,
                                ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    return ctypes, user32, gdi32, INPUT, RECT, BITMAPINFOHEADER


def _key(INPUT, vk: int = 0, scan: int = 0, flags: int = 0):
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki.wVk, event.u.ki.wScan, event.u.ki.dwFlags = vk, scan, flags
    return event


def _vk_events(INPUT, vk: int, up: bool):
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    return _key(INPUT, vk=vk, flags=flags)


def events_for(item, INPUT, scan) -> list:
    """The INPUT records for one key or text. ``scan`` is VkKeyScanW."""
    if isinstance(item, keynames.Text):
        records = []
        for unit in struct.unpack(f"<{len(item.text.encode('utf-16-le')) // 2}H",
                                  item.text.encode("utf-16-le")):
            records += [_key(INPUT, scan=unit, flags=KEYEVENTF_UNICODE),
                        _key(INPUT, scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
        return records
    mods = set(item.mods)
    if item.name in VK:
        vk = VK[item.name]
    else:
        packed = scan(item.name)
        if packed == -1:
            raise DesktopError(f"{item}: no key types {item.name!r} on this layout - "
                               f"send it as text")
        vk = packed & 0xFF
        state = (packed >> 8) & 0xFF
        if state & 1:
            mods.add("shift")
    order = [m for m in ("ctrl", "alt", "shift", "cmd") if m in mods]
    records = [_vk_events(INPUT, MODIFIER_VK[m], False) for m in order]
    records += [_vk_events(INPUT, vk, False), _vk_events(INPUT, vk, True)]
    records += [_vk_events(INPUT, MODIFIER_VK[m], True) for m in reversed(order)]
    return records


def send(items: list) -> None:
    ctypes, user32, _gdi, INPUT, _rect, _bmi = _api()
    for item in items:
        if isinstance(item, keynames.Pause):
            time.sleep(item.seconds)
            continue
        records = events_for(item, INPUT, user32.VkKeyScanW)
        array = (INPUT * len(records))(*records)
        sent = user32.SendInput(len(records), array, ctypes.sizeof(INPUT))
        if sent != len(records):
            raise DesktopError(f"SendInput sent {sent} of {len(records)} events - the "
                               f"window may belong to an elevated process (UIPI)")
        time.sleep(0.02)


def _title(user32, ctypes, hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def find(title: str) -> int | None:
    from quality_loop.screens import _windows as screens
    for handle, shown in screens.windows().items():
        if title in shown:
            return handle
    return None


def frontmost() -> tuple[int, str]:
    ctypes, user32, *_rest = _api()
    hwnd = user32.GetForegroundWindow()
    return int(hwnd or 0), _title(user32, ctypes, hwnd) if hwnd else ""


def raise_window(handle: int) -> None:
    _ctypes, user32, *_rest = _api()
    user32.SetForegroundWindow(handle)


def png(width: int, height: int, rgb_rows: list[bytes]) -> bytes:
    """A truecolour PNG from rows of RGB bytes."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + row for row in rgb_rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def screenshot(handle: int, path: pathlib.Path) -> pathlib.Path:
    ctypes, user32, gdi32, _input, RECT, BITMAPINFOHEADER = _api()
    rect = RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        raise DesktopError("GetWindowRect failed - the window is gone")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    try:
        gdi32.SelectObject(memory, bitmap)
        gdi32.BitBlt(memory, 0, 0, width, height, screen, rect.left, rect.top, 0x00CC0020)
        header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=width,
                                  biHeight=-height, biPlanes=1, biBitCount=32)
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)
    data = buffer.raw
    rows = []
    for y in range(height):
        row = data[y * width * 4:(y + 1) * width * 4]
        rgb = bytearray(width * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]
        rows.append(bytes(rgb))
    path.write_bytes(png(width, height, rows))
    return path


def permissions() -> dict:
    """Windows asks for no permission; UIPI is the limit, and shows on send."""
    return {}


def processes() -> list[str]:
    done = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                          text=True, check=False)
    return [line.split('","')[0].strip('"') for line in done.stdout.splitlines() if line]
