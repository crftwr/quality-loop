"""A stand-in for `claude`, enough for the runner's path end to end.

It answers as a room session, or as an operator in each phase, with the
stream-json events the runner reads. ``FAKE_TRACE`` collects when each room
session started and ended, so a test can see rooms overlap.
"""

import json
import os
import pathlib
import sys
import time

args = sys.argv[1:]
message = args[args.index("-p") + 1] if "-p" in args else ""


def emit(event):
    print(json.dumps(event), flush=True)


def trace(what):
    if os.environ.get("FAKE_TRACE"):
        with open(os.environ["FAKE_TRACE"], "a") as out:
            out.write(f"{time.time()} {what} {pathlib.Path.cwd().name}\n")


if message.startswith("Read RULES.md"):
    trace("start")
    emit({"type": "system", "subtype": "init", "tools": ["Read"], "slash_commands": [],
          "mcp_servers": []})
    emit({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "1", "name": "Read",
         "input": {"file_path": str(pathlib.Path.cwd() / "TASK.md")}}]}})
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0.2")))
    emit({"type": "result", "result": "done", "num_turns": 2, "duration_ms": 200,
          "total_cost_usd": 0.01})
    trace("end")
elif message.startswith("Phase 2"):
    room = pathlib.Path(message.split("Room: ", 1)[1].split("\n", 1)[0].strip())
    ident = os.environ.get("FAKE_ID", "greeting-wrong-case") + "-" + room.name.split("_")[0]
    (room / "REPORT.md").write_text(
        f"# Report: x\n\nWhat happened.\n\n### [medium] Something {room.name}\n"
        f"- **Id:** `{ident}`\n- **Kind:** skill gap\n- **Evidence:** transcript step 1\n"
        f"- **Where it would be fixed:** SKILL.md\n- **How a fix is confirmed:** re-run\n")
    emit({"type": "result", "result": "reported", "total_cost_usd": 0.002})
else:
    emit({"type": "result", "result": "ok", "total_cost_usd": 0.001})
