"""quality-loop's own tools, as a small MCP server: ``python -m quality_loop.mcp``.

The operator has no shell. Claude Code lets a read-only command through
whatever the allow list says, so a compound ``cd; ls; cat ...`` ran on the
first real operator - and ``cat`` reads anywhere on the machine, which the
file tools' confinement does not. So the operator's only way to act is these
four tools:

- ``screen_list``, ``screen_open(name)``, ``screen_close(id)`` - the
  declared screens, as `quality_loop.screens` puts them up;
- ``evidence(tool, args)`` - one of the product's declared evidence
  commands, run with ``args`` as a list and no shell, so nothing can be piped,
  redirected or chained. What the arguments mean is the evidence command's
  own business, and an adapter declares only commands that read.

When the manifest declares apps, six more drive them (`quality_loop.drive`):
``app_list``, ``app_start(name)``, ``app_keys(id, keys, intent)``,
``app_screen(id)``, ``app_events(id)`` and ``app_stop(id)``. The operator gets
them for its live check; a room gets them - and only them - when the product
is human-facing and its UI is the surface under test. Every step is recorded
where the manifest says, outside the reach of whoever is driving.

Everything comes from the manifest the runner wrote (``QUALITY_LOOP_MANIFEST``),
and the tool list follows it: screens and evidence only when it declares
them, apps only when it declares some.
The protocol is the least of MCP that Claude Code needs - initialize,
tools/list, tools/call, ping - as newline-delimited JSON-RPC on stdio, with
nothing outside the standard library.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import signal
import subprocess
import sys

import quality_loop
from quality_loop import screens

PROTOCOL = "2025-06-18"

#: Ceiling on what one evidence call hands back, in characters.
MAX_OUTPUT = 20_000

#: How long one evidence command may take.
EVIDENCE_TIMEOUT = 120


def _manifest() -> dict:
    return json.loads(pathlib.Path(os.environ[screens.MANIFEST]).read_text(encoding="utf-8"))


KEY_ITEM = {"anyOf": [
    {"type": "string"},
    {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    {"type": "object", "properties": {"pause": {"type": "number"}}, "required": ["pause"]}]}


def app_tools(manifest: dict) -> list[dict]:
    """The tools that drive the declared apps."""
    apps = manifest.get("apps") or {}
    ident = {"id": {"type": "string", "description": "What app_start answered."}}
    return [
        {"name": "app_list",
         "description": "The apps that can be started: name, kind (tui: a terminal app "
                        "read as text; gui: a desktop app read by screenshot).",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "app_start",
         "description": "Start a declared app and answer its first screen and an id.",
         "inputSchema": {"type": "object", "properties": {
             "name": {"type": "string", "enum": sorted(apps)},
             "intent": {"type": "string", "description": "Why you are starting it."}},
             "required": ["name"]}},
        {"name": "app_keys",
         "description": "Send keys to a running app, wait until its screen settles, and "
                        "answer the screen afterwards and any event-log lines since the "
                        "last step. Keys are written like \"Ctrl-Shift-G\", \"Alt-Left\", "
                        "\"F5\", \"Enter\", \"Esc\", \"a\"; text as {\"text\": \"...\"}; a "
                        "pause as {\"pause\": 0.5}. Modifiers: Ctrl, Shift, Alt, Cmd. "
                        "intent is required: what you expect this step to do.",
         "inputSchema": {"type": "object", "properties": {
             **ident, "keys": {"type": "array", "items": KEY_ITEM},
             "intent": {"type": "string"}},
             "required": ["id", "keys", "intent"]}},
        {"name": "app_screen",
         "description": "The app's screen now: text for a terminal app, an image for a "
                        "desktop app.",
         "inputSchema": {"type": "object", "properties": ident, "required": ["id"]}},
        {"name": "app_events",
         "description": "The app's own event log, when it writes one: what it showed, "
                        "said, raised and launched, as facts.",
         "inputSchema": {"type": "object", "properties": ident, "required": ["id"]}},
        {"name": "app_stop",
         "description": "Quit a running app.",
         "inputSchema": {"type": "object", "properties": ident, "required": ["id"]}},
    ]


def tools(manifest: dict) -> list[dict]:
    """The tool list, with the declared names in the schemas."""
    found = []
    if "screens" in manifest:
        found += _screen_tools(manifest)
    if "evidence" in manifest:
        found += _evidence_tools(manifest)
    if manifest.get("apps"):
        found += app_tools(manifest)
    return found


def _screen_tools(manifest: dict) -> list[dict]:
    return [
        {"name": "screen_list",
         "description": "The screens the product declares: name, kind and window title.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "screen_open",
         "description": "Open a declared screen and wait until its window is up. "
                        "Answers the id to close it with.",
         "inputSchema": {"type": "object", "properties": {
             "name": {"type": "string", "enum": sorted(manifest.get("screens", {}))}},
             "required": ["name"]}},
        {"name": "screen_close",
         "description": "Close a screen screen_open opened, by its id.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                         "required": ["id"]}},
    ]


def _evidence_tools(manifest: dict) -> list[dict]:
    evidence = manifest.get("evidence", {})
    listing = "\n".join(f"- {name}: {entry.get('help', '')}"
                        for name, entry in evidence.items()) or "(none declared)"
    return [
        {"name": "evidence",
         "description": "Run one of the product's evidence commands with the given "
                        "arguments and answer what it printed. Run it with "
                        "args [\"--help\"] first. Declared:\n" + listing,
         "inputSchema": {"type": "object", "properties": {
             "tool": {"type": "string", "enum": sorted(evidence)},
             "args": {"type": "array", "items": {"type": "string"}}},
             "required": ["tool", "args"]}},
    ]


class ToolError(Exception):
    pass


_driver = None


def driver(manifest: dict):
    """The apps this server drives, started on the first call that needs them."""
    global _driver
    if _driver is None:
        from quality_loop import drive
        _driver = drive.Driver(manifest.get("apps") or {}, pathlib.Path(manifest["record"]))
    return _driver


def _app_answer(answer) -> list[dict]:
    """A drive answer as content: the image inline, everything else as JSON."""
    if isinstance(answer, dict) and answer.get("image"):
        path = pathlib.Path(answer["image"])
        shown = {k: v for k, v in answer.items() if k != "image"}
        return [{"type": "text", "text": json.dumps(shown, indent=2, ensure_ascii=False)},
                {"type": "image", "mimeType": "image/png",
                 "data": base64.b64encode(path.read_bytes()).decode("ascii")}]
    return [{"type": "text", "text": json.dumps(answer, indent=2, ensure_ascii=False)}]


def call_app(name: str, arguments: dict, manifest: dict) -> list[dict]:
    from quality_loop import drive
    if not manifest.get("apps"):
        raise ToolError("no apps are declared")
    try:
        apps = driver(manifest)
        if name == "app_list":
            return _app_answer(apps.list())
        if name == "app_start":
            return _app_answer(apps.start(str(arguments.get("name", "")),
                                          str(arguments.get("intent", ""))))
        ident = str(arguments.get("id", ""))
        if name == "app_keys":
            return _app_answer(apps.keys(ident, arguments.get("keys", []),
                                         str(arguments.get("intent", ""))))
        if name == "app_screen":
            return _app_answer(apps.screen(ident))
        if name == "app_events":
            return _app_answer(apps.events(ident))
        if name == "app_stop":
            return _app_answer(apps.stop(ident))
    except drive.DriveError as error:
        raise ToolError(str(error)) from None
    raise ToolError(f"no tool {name!r}")


def call(name: str, arguments: dict, manifest: dict):
    """One tool call's answer - text, or content parts - or a ToolError."""
    if name.startswith("app_"):
        return call_app(name, arguments, manifest)
    if name.startswith("screen_") and "screens" not in manifest:
        raise ToolError(f"no tool {name!r}")
    try:
        if name == "screen_list":
            return json.dumps({n: {"kind": e["kind"], "title": e["title"]}
                               for n, e in manifest.get("screens", {}).items()}, indent=2)
        if name == "screen_open":
            return json.dumps(screens.open_screen(str(arguments.get("name", ""))), indent=2)
        if name == "screen_close":
            return json.dumps(screens.close_screen(str(arguments.get("id", ""))), indent=2)
    except screens.ScreenError as error:
        raise ToolError(str(error)) from None
    if name == "evidence":
        return _evidence(arguments, manifest)
    raise ToolError(f"no tool {name!r}")


def _evidence(arguments: dict, manifest: dict) -> str:
    declared = manifest.get("evidence", {})
    tool = arguments.get("tool")
    if tool not in declared:
        raise ToolError(f"no evidence tool {tool!r}; declared: "
                        + (", ".join(sorted(declared)) or "none"))
    args = arguments.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ToolError("args must be a list of strings")
    try:
        done = subprocess.run([*declared[tool]["argv"], *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=EVIDENCE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ToolError(f"{tool} did not finish within {EVIDENCE_TIMEOUT}s") from None
    said = done.stdout + (f"\n[stderr]\n{done.stderr}" if done.stderr.strip() else "")
    if len(said) > MAX_OUTPUT:
        said = said[:MAX_OUTPUT] + f"\n... {len(said) - MAX_OUTPUT} more characters"
    if done.returncode != 0:
        raise ToolError(f"{tool} exited {done.returncode}\n{said}")
    return said


def handle(message: dict, manifest: dict) -> dict | None:
    """The reply to one JSON-RPC message, or None for a notification."""
    if "id" not in message:
        return None
    method, ident = message.get("method"), message["id"]
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion") or PROTOCOL
        result = {"protocolVersion": asked, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "quality-loop", "version": quality_loop.__version__}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools(manifest)}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            answer, failed = call(params.get("name", ""), params.get("arguments") or {},
                                  manifest), False
        except ToolError as error:
            answer, failed = str(error), True
        content = answer if isinstance(answer, list) else [{"type": "text", "text": answer}]
        result = {"content": content, "isError": failed}
    else:
        return {"jsonrpc": "2.0", "id": ident,
                "error": {"code": -32601, "message": f"no method {method!r}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def main() -> int:
    manifest = _manifest()
    # The session ending closes stdin; a terminated one may not. Either way
    # the apps this server started go with it, never left running.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and (reply := handle(message, manifest)) is not None:
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if _driver is not None:
            _driver.stop_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
