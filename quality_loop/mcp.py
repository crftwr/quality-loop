"""The operator's tools, as a small MCP server: ``python -m quality_loop.mcp``.

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

Everything comes from the manifest the runner wrote (``QUALITY_LOOP_MANIFEST``).
The protocol is the least of MCP that Claude Code needs - initialize,
tools/list, tools/call, ping - as newline-delimited JSON-RPC on stdio, with
nothing outside the standard library.
"""

from __future__ import annotations

import json
import os
import pathlib
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


def tools(manifest: dict) -> list[dict]:
    """The tool list, with the declared names in the schemas."""
    evidence = manifest.get("evidence", {})
    listing = "\n".join(f"- {name}: {entry.get('help', '')}"
                        for name, entry in evidence.items()) or "(none declared)"
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


def call(name: str, arguments: dict, manifest: dict) -> str:
    """One tool call's answer, or a ToolError saying what was wrong."""
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
            text, failed = call(params.get("name", ""), params.get("arguments") or {},
                                manifest), False
        except ToolError as error:
            text, failed = str(error), True
        result = {"content": [{"type": "text", "text": text}], "isError": failed}
    else:
        return {"jsonrpc": "2.0", "id": ident,
                "error": {"code": -32601, "message": f"no method {method!r}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def main() -> int:
    manifest = _manifest()
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and (reply := handle(message, manifest)) is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
