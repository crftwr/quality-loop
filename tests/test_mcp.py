"""The operator's MCP server: four tools, names only, no shell."""

import json
import subprocess
import sys

import pytest

from quality_loop import mcp, screens
from quality_loop.screens import Page


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    probe = tmp_path / "probe.py"
    probe.write_text("import sys, json; print(json.dumps(sys.argv[1:]))\n")
    path = screens.write_manifest(
        tmp_path / "manifest.json", {"queue": Page("q.html", title="Queue")},
        fixtures=tmp_path, origin="http://127.0.0.1:1", python=sys.executable,
        state=tmp_path / "operator",
        evidence={"probe": {"argv": [sys.executable, str(probe)], "help": "echoes"}})
    monkeypatch.setenv(screens.MANIFEST, str(path))
    return json.loads(path.read_text())


def _call(manifest, name, arguments):
    reply = mcp.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}}, manifest)
    result = reply["result"]
    return result["content"][0]["text"], result["isError"]


def test_the_handshake_and_the_four_tools(manifest):
    hello = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-03-26"}}, manifest)
    assert hello["result"]["protocolVersion"] == "2025-03-26"
    assert hello["result"]["serverInfo"]["name"] == "quality-loop"
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"},
                      manifest) is None
    listed = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, manifest)
    tools = {t["name"]: t for t in listed["result"]["tools"]}
    assert sorted(tools) == ["evidence", "screen_close", "screen_list", "screen_open"]
    assert tools["screen_open"]["inputSchema"]["properties"]["name"]["enum"] == ["queue"]
    assert tools["evidence"]["inputSchema"]["properties"]["tool"]["enum"] == ["probe"]
    unknown = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"}, manifest)
    assert unknown["error"]["code"] == -32601


def test_evidence_runs_the_declared_command_with_args_and_no_shell(manifest):
    text, failed = _call(manifest, "evidence",
                         {"tool": "probe", "args": ["greeting", "a; rm -rf / | cat"]})
    assert not failed
    assert json.loads(text) == ["greeting", "a; rm -rf / | cat"], "one argument, verbatim"


@pytest.mark.parametrize("arguments,said", [
    ({"tool": "sh", "args": ["-c", "ls"]}, "no evidence tool 'sh'"),
    ({"tool": "probe", "args": "--help"}, "list of strings"),
    ({"tool": "probe", "args": [1]}, "list of strings"),
])
def test_evidence_refuses_what_was_not_declared(manifest, arguments, said):
    text, failed = _call(manifest, "evidence", arguments)
    assert failed and said in text


def test_screens_are_by_name_only(manifest):
    text, failed = _call(manifest, "screen_open", {"name": "/Applications/Terminal.app"})
    assert failed and "declares: queue" in text
    text, failed = _call(manifest, "screen_list", {})
    assert json.loads(text) == {"queue": {"kind": "page", "title": "Queue"}}


def test_it_speaks_json_lines_on_stdio(manifest, tmp_path):
    import os
    lines = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]) + "\n"
    done = subprocess.run([sys.executable, "-m", "quality_loop.mcp"], input=lines,
                          capture_output=True, text=True, env=dict(os.environ), timeout=30)
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
