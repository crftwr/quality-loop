"""Key notation, and what a key is as bytes on a terminal.

One notation for both backends, in Keyhac's style: modifiers joined to the key
with ``-``, as ``Ctrl-Shift-G``, ``Alt-Left``, ``F5``, ``Enter``, ``a``. A
letter names the key, not what it types: ``G`` and ``g`` are the same key,
and a capital is ``Shift-G`` (or the text ``{"text": "G"}``).
Text goes in as ``{"text": "..."}``, which the OS backends inject as Unicode
(unaffected by the keyboard layout and the IME) and the terminal backend
writes as UTF-8. A pause is ``{"pause": 0.5}``.

Modifiers: ``Ctrl`` (``Control``), ``Shift``, ``Alt`` (``Option``, ``Opt``)
and ``Cmd`` (``Command``, ``Win``, ``Super``, ``Meta``).
"""

from __future__ import annotations

import dataclasses

MODIFIERS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt",
             "option": "alt", "opt": "alt", "cmd": "cmd", "command": "cmd",
             "win": "cmd", "super": "cmd", "meta": "cmd"}

#: Named keys, by the spelling used in a key, lowercased -> the canonical name.
NAMED = {"enter": "Enter", "return": "Enter", "tab": "Tab", "esc": "Esc",
         "escape": "Esc", "space": "Space", "backspace": "Backspace", "bs": "Backspace",
         "delete": "Delete", "del": "Delete", "up": "Up", "down": "Down",
         "left": "Left", "right": "Right", "home": "Home", "end": "End",
         "pageup": "PageUp", "pgup": "PageUp", "pagedown": "PageDown",
         "pgdn": "PageDown", "insert": "Insert", "ins": "Insert",
         **{f"f{n}": f"F{n}" for n in range(1, 25)}}


class KeysError(ValueError):
    """A key that cannot be read or cannot be sent this way."""


@dataclasses.dataclass(frozen=True)
class Key:
    """One key with its modifiers. ``name`` is a NAMED value or one character."""
    name: str
    mods: frozenset = frozenset()

    def __str__(self) -> str:
        order = [m for m in ("ctrl", "alt", "shift", "cmd") if m in self.mods]
        return "-".join([m.capitalize() for m in order] + [self.name])


@dataclasses.dataclass(frozen=True)
class Text:
    text: str


@dataclasses.dataclass(frozen=True)
class Pause:
    seconds: float


def parse(token: str) -> Key:
    """``"Ctrl-Shift-G"`` -> Key("G", {"ctrl", "shift"})."""
    if not isinstance(token, str) or not token:
        raise KeysError(f"not a key: {token!r}")
    parts = token.split("-")
    # A trailing "-" is the minus key itself: "Ctrl--" splits to [..., "", ""].
    if token.endswith("-") and len(parts) >= 2 and parts[-1] == "":
        parts = parts[:-2] + ["-"]
    *mods, name = parts
    found = set()
    for mod in mods:
        canonical = MODIFIERS.get(mod.lower())
        if canonical is None:
            raise KeysError(f"{token!r}: {mod!r} is not a modifier "
                            f"({', '.join(sorted(set(MODIFIERS.values())))})")
        found.add(canonical)
    if len(name) == 1:
        return Key(name, frozenset(found))
    canonical = NAMED.get(name.lower())
    if canonical is None:
        raise KeysError(f"{token!r}: no key named {name!r}")
    return Key(canonical, frozenset(found))


def sequence(items) -> list[Key | Text | Pause]:
    """A list of keys, ``{"text": ...}`` and ``{"pause": ...}``, read."""
    if isinstance(items, (str, dict)):
        items = [items]
    if not isinstance(items, list):
        raise KeysError("keys must be a list")
    found: list[Key | Text | Pause] = []
    for item in items:
        if isinstance(item, str):
            found.append(parse(item))
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            found.append(Text(item["text"]))
        elif isinstance(item, dict) and isinstance(item.get("pause"), (int, float)):
            found.append(Pause(min(float(item["pause"]), 30.0)))
        else:
            raise KeysError(f"not a key, {{\"text\": ...}} or {{\"pause\": ...}}: {item!r}")
    return found


def describe(items: list[Key | Text | Pause]) -> list:
    """The sequence as it is recorded: keys by name, text and pauses as given."""
    shown = []
    for item in items:
        if isinstance(item, Key):
            shown.append(str(item))
        elif isinstance(item, Text):
            shown.append({"text": item.text})
        else:
            shown.append({"pause": item.seconds})
    return shown


# --- a terminal --------------------------------------------------------------------

_CSI_TILDE = {"Insert": 2, "Delete": 3, "PageUp": 5, "PageDown": 6,
              "F5": 15, "F6": 17, "F7": 18, "F8": 19, "F9": 20, "F10": 21,
              "F11": 23, "F12": 24}
_CSI_LETTER = {"Up": "A", "Down": "B", "Right": "C", "Left": "D", "Home": "H", "End": "F"}
_SS3 = {"F1": "P", "F2": "Q", "F3": "R", "F4": "S"}


def terminal_bytes(key: Key) -> bytes:
    """What an xterm sends for ``key``.

    A terminal cannot tell Ctrl-Shift-G from Ctrl-G, and has no Cmd at all:
    the former is sent as Ctrl-G, the latter refused, so a step that a
    terminal app could never have received is not recorded as sent.
    """
    mods = set(key.mods)
    if "cmd" in mods:
        raise KeysError(f"{key}: a terminal has no Cmd key")
    name = key.name
    # xterm's modifier parameter for cursor and function keys.
    param = 1 + ("shift" in mods) + 2 * ("alt" in mods) + 4 * ("ctrl" in mods)
    if name in _CSI_LETTER:
        letter = _CSI_LETTER[name]
        return (f"\x1b[1;{param}{letter}" if param > 1 else f"\x1b[{letter}").encode()
    if name in _CSI_TILDE:
        number = _CSI_TILDE[name]
        return (f"\x1b[{number};{param}~" if param > 1 else f"\x1b[{number}~").encode()
    if name in _SS3:
        letter = _SS3[name]
        return (f"\x1b[1;{param}{letter}" if param > 1 else f"\x1bO{letter}").encode()
    if name.startswith("F") and name[1:].isdigit():
        raise KeysError(f"{key}: a terminal sends no {name}")
    prefix = b"\x1b" if "alt" in mods else b""
    if name == "Tab" and "shift" in mods:
        return b"\x1b[Z"
    simple = {"Enter": b"\r", "Tab": b"\t", "Esc": b"\x1b", "Backspace": b"\x7f",
              "Space": b" "}
    if name in simple:
        if "ctrl" in mods and name == "Space":
            return prefix + b"\x00"
        return prefix + simple[name]
    char = name
    if "ctrl" in mods:
        upper = char.upper()
        if "@" <= upper <= "_":
            return prefix + bytes([ord(upper) - 64])
        if char == "?":
            return prefix + b"\x7f"
        raise KeysError(f"{key}: a terminal has no Ctrl with {char!r}")
    char = char.upper() if "shift" in mods else char.lower()
    return prefix + char.encode("utf-8")
