"""Between runs and around them: progress, the queue, comparing findings, the
command line and init. A fake `claude` stands in, so the runner's whole path
runs without a model."""

import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time

import pytest

import quality_loop
from quality_loop import (adapter, audit, cli, compare, config, install, processes,
                          progress, runner, session)

HERE = pathlib.Path(__file__).resolve().parent
posix_only = pytest.mark.skipif(os.name == "nt", reason="the fake claude is a shell script")


# --- a product small enough to run with a fake claude -------------------------------

ADAPTER = '''
import pathlib
from quality_loop import adapter, session

HERE = pathlib.Path(__file__).resolve().parent

class Fake(adapter.Adapter):
    name = "fake"
    version = "1.0"
    checkout = HERE.parent
    rooms = HERE.parent / "rooms"
    scenarios = HERE / "scenarios"
    skill_name = "fake"
    parallel = PARALLEL
    resources = {"desktop": 1}

    def needs(self, case, variant):
        return {"desktop"} if case.meta.get("desktop") else set()

    def bundle(self):
        return HERE / "skill"

    def rules(self):
        return "Use only ./skills.\\n"

    def session(self, room):
        return session.Session(allow=["Read"], max_turns=5)

    def restore(self):
        return ["nothing to restore"]
'''

SCENARIO = '''+++
title = "Scenario {n}"
{extra}
+++

## Prompt

Do thing number {n}, please.

## Must

- The thing is done.
'''


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A checkout with qa/, three scenarios and a fake claude."""
    root = tmp_path / "product"
    qa = root / "qa"
    (qa / "scenarios").mkdir(parents=True)
    (qa / "skill").mkdir()
    (qa / "skill" / "SKILL.md").write_text("# Fake\n")
    for n, extra in ((1, "desktop = true"), (2, ""), (3, "")):
        (qa / "scenarios" / f"0{n}_thing.md").write_text(SCENARIO.format(n=n, extra=extra))
    (qa / "run.py").write_text(ADAPTER.replace("PARALLEL", "1"))
    (qa / "quality-loop.toml").write_text('adapter = "qa/run.py:Fake"\nrooms = "rooms"\n')
    claude = tmp_path / "claude"
    claude.write_text(f"#!/bin/sh\nexec {sys.executable} {HERE / 'fake_claude.py'} \"$@\"\n")
    claude.chmod(0o755)
    monkeypatch.setenv("CLAUDE_BIN", str(claude))
    monkeypatch.setenv("FAKE_TRACE", str(tmp_path / "trace"))
    monkeypatch.chdir(root)
    previous = signal.getsignal(signal.SIGTERM)
    yield root
    signal.signal(signal.SIGTERM, previous)
    sys.modules.pop("run", None)


def _adapter(root, parallel=1):
    (root / "qa" / "run.py").write_text(ADAPTER.replace("PARALLEL", str(parallel)))
    sys.modules.pop("run", None)
    return config.load_adapter(config.find(root))


@posix_only
def test_a_run_writes_its_log_status_and_findings(product):
    findings = runner.run(_adapter(product), ["2"], say=lambda _t: None)
    run = findings.parent
    status = progress.read(run)
    assert status["state"] == "done" and status["findings"] == str(findings)
    assert status["rooms"]["02_thing"]["phase"] == "done"
    assert status["cost_usd"] == pytest.approx(0.01 + 0.001 + 0.002)
    log = (run / "run.log").read_text()
    assert "== 02_thing: Scenario 2" in log and "operator: phase 2" in log
    assert (run / "02_thing.log").exists(), "each room has a log of its own"
    entries = json.loads((run / "findings.json").read_text())
    assert [(e["id"], e["room"], e["run"]) for e in entries] == [
        ("greeting-wrong-case-02", "02_thing", run.name)]
    start = json.loads((run / "02_thing" / "evidence" / "run.json").read_text())
    assert start["product"] == "fake" and start["quality_loop"] == quality_loop.__version__
    assert "commit" in start and start["room_cost_usd"] == 0.01


@posix_only
def test_rooms_run_side_by_side_within_their_resources(product, tmp_path):
    os.environ["FAKE_SLEEP"] = "1.0"
    try:
        findings = runner.run(_adapter(product, parallel=3), None, say=lambda _t: None)
    finally:
        del os.environ["FAKE_SLEEP"]
    spans = {}
    for line in (tmp_path / "trace").read_text().splitlines():
        at, what, room = line.split()
        spans.setdefault(room, {})[what] = float(at)
    assert len(spans) == 3
    rooms = sorted(spans)
    overlapping = sum(1 for a in rooms for b in rooms if a < b
                      and spans[a]["start"] < spans[b]["end"]
                      and spans[b]["start"] < spans[a]["end"])
    assert overlapping >= 1, "rooms ran one after another"
    log = (findings.parent / "run.log").read_text()
    assert "[01_thing] " in log, "side by side, each line says whose it is"
    assert len(json.loads((findings.parent / "findings.json").read_text())) == 3


@posix_only
def test_a_room_that_fails_is_reported_and_the_others_go_on(product, monkeypatch):
    product_adapter = _adapter(product, parallel=2)
    original = product_adapter.session

    def session(room):
        if room.name.startswith("01"):
            raise ValueError("no session for you")
        return original(room)

    monkeypatch.setattr(product_adapter, "session", session)
    findings = runner.run(product_adapter, None, say=lambda _t: None)
    entries = json.loads((findings.parent / "findings.json").read_text())
    by_room = {e["room"]: e["id"] for e in entries}
    assert by_room["01_thing"] == "room-failed"
    assert by_room["02_thing"].startswith("greeting-wrong-case")
    assert progress.read(findings.parent)["state"] == "done"


def test_the_queue_keeps_to_the_limit_and_the_resources():
    class Product(adapter.Adapter):
        resources = {"desktop": 1}

        def needs(self, case, variant):
            return {"desktop"} if variant == "gui" else set()

    live, most, desktop_most = [], [0], [0]
    lock = threading.Lock()

    def work(item):
        with lock:
            live.append(item)
            most[0] = max(most[0], len(live))
            desktop_most[0] = max(desktop_most[0], sum(1 for i in live if i[1] == "gui"))
        time.sleep(0.15)
        with lock:
            live.remove(item)

    items = [(n, "gui") for n in range(3)] + [(n, "") for n in range(3, 7)]
    runner._drive(Product(), items, 3, work, None)
    assert most[0] == 3 and desktop_most[0] == 1


def test_a_failing_room_stops_the_queue_and_is_raised():
    processes.reset()

    started = []

    def work(item):
        started.append(item)
        if item[0] == 1:
            raise RuntimeError("boom")
        time.sleep(0.2)

    with pytest.raises(RuntimeError, match="boom"):
        runner._drive(adapter.Adapter(), [(n, "") for n in range(1, 7)], 2, work, None)
    assert len(started) < 6, "nothing more starts once one has failed"
    processes.reset()


def test_rooms_side_by_side_may_not_share_a_directory_or_reach_a_marker(tmp_path):
    reach = runner.Reach()
    shared = tmp_path / "desktop"
    reach.claim("a", tmp_path / "a", [shared], tmp_path / "marker-a")
    with pytest.raises(runner.RunnerError, match="share"):
        reach.claim("b", tmp_path / "b", [shared / "sub"], None)
    with pytest.raises(runner.RunnerError, match="marker"):
        reach.claim("c", tmp_path / "c", [tmp_path / "marker-a"], None)
    reach.release("a")
    reach.claim("b", tmp_path / "b", [shared], None)


def test_variants_and_known_problems_are_picked_per_room():
    class Product(adapter.Adapter):
        default_variant = "template"

    case = type("Case", (), {"name": "11_f1"})()
    items = [(case, ""), (case, "short"), (case, "grown")]
    assert runner.pick_variants(Product(), items, ["template", "grown"]) == [
        (case, ""), (case, "grown")]
    known = [{"id": "a", "title": "A", "room": "11_f1.short", "status": "fixed"},
             {"id": "b", "title": "B", "room": "12_other"},
             {"id": "c", "title": "C"}]
    assert runner.known_for(known, case, "11_f1.short") == [
        {"id": "a", "title": "A"}, {"id": "c", "title": "C"}], "never a status"


# --- the audit: the run's own records ------------------------------------------------

def test_a_room_reaching_the_run_s_records_or_a_sibling_is_a_breach(tmp_path):
    run = tmp_path / "rooms" / "1.0-20260101-000000"
    room = run / "11_f1"
    room.mkdir(parents=True)
    events = [{"type": "system", "subtype": "init", "tools": ["Read"], "mcp_servers": []}]
    for n, path in enumerate([room / "TASK.md", run / "run.log",
                              run / "11_f1.operator" / "setup.md"]):
        events += [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": str(n), "name": "Read",
             "input": {"file_path": str(path)}}]}},
                   {"type": "user", "message": {"content": [
                       {"type": "tool_result", "tool_use_id": str(n), "content": "x"}]}}]
    (room / "transcript.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    breaches, _refused = audit.audit(room, audit.Policy(
        checkout=tmp_path / "elsewhere", run_directory=run))
    assert len(breaches) == 2 and all("run's own records" in b for b in breaches)
    assert not audit.under("/a/11_f1.operator/x", "/a/11_f1")


# --- progress and watching ---------------------------------------------------------

def test_status_is_written_as_the_run_moves(tmp_path):
    said = []
    status = progress.Progress(tmp_path / "run", product="p", version="1", echo=said.append)
    status.plan([("01_a", "01_a", ""), ("02_b", "02_b", "")])
    status.phase("01_a", "room")
    status.thinking("01_a", 42)
    status.cost("01_a", 0.25)
    status.say("  room:    running", "01_a")
    read = progress.read(tmp_path / "run")
    assert read["rooms"]["01_a"]["phase"] == "room" and read["cost_usd"] == 0.25
    assert read["rooms"]["02_b"]["phase"] == "waiting"
    assert said == ["  room:    running"]
    assert (tmp_path / "run" / "01_a.log").read_text() == "  room:    running\n"
    status.finish("cancelled")
    summary = progress.summary(progress.read(tmp_path / "run"))
    assert "cancelled" in summary and "02_b" in summary


def test_watch_follows_the_log_and_stops_when_the_run_ends(tmp_path):
    rooms = tmp_path / "rooms"
    status = progress.Progress(rooms / "1-20260101-000000", product="p", version="1",
                               echo=None)
    status.plan([("01_a", "01_a", "")])
    status.say("== 01_a: first")
    status.finish("done", rooms / "1-20260101-000000" / "FINDINGS.md")
    seen = []
    cli.watch(rooms / "1-20260101-000000", rooms, interval=0.01, out=seen.append)
    assert "== 01_a: first" in "\n".join(seen) and "done" in "\n".join(seen)


# --- comparing runs ------------------------------------------------------------------

def _run(rooms, name, ids, ran):
    directory = rooms / name
    directory.mkdir(parents=True)
    (directory / "findings.json").write_text(json.dumps(
        [{"id": i, "room": r, "severity": "high", "title": i} for r, i in ids]))
    progress.write_json(directory / "status.json", {"rooms": {
        r: {"phase": "done"} for r in ran}})
    return directory


def test_findings_are_new_still_there_gone_or_back(tmp_path):
    rooms = tmp_path / "rooms"
    _run(rooms, "1.0-20260101-000000", [("11", "flaky")], ["11"])
    _run(rooms, "1.0-20260102-000000", [("11", "stays"), ("11", "goes"), ("12", "unrun")],
         ["11", "12"])
    latest = _run(rooms, "1.0-20260103-000000",
                  [("11", "stays"), ("11", "flaky"), ("11", "fresh")], ["11"])
    result = compare.against_history(latest)
    ids = {k: sorted(e["id"] for e in result[k]) for k in ("new", "still", "gone", "back")}
    assert ids == {"new": ["fresh"], "still": ["stays"], "gone": ["goes"],
                   "back": ["flaky"]}, "12 was not run, so its problem is not gone"
    assert result["since"] == "1.0-20260102-000000"


# --- the command line ---------------------------------------------------------------

def test_settings_are_found_from_inside_the_checkout(product):
    found = config.find(product / "qa" / "scenarios")
    assert found.root == product and found.adapter_spec == "qa/run.py:Fake"
    assert found.rooms() == (product / "rooms").resolve()


def test_check_reports_without_a_run(product, capsys):
    assert cli.main(["check"]) == 0
    assert "ok: 3 scenario(s)" in capsys.readouterr().out
    (product / "qa" / "scenarios" / "04_live.md").write_text(
        SCENARIO.format(n=4, extra="") + "\n## Live check\n\nOpen it.\n")
    assert cli.main(["check"]) == 1
    assert "no apps" in capsys.readouterr().out


@posix_only
def test_a_detached_run_is_followed_to_its_end(product, capsys):
    assert cli.main(["run", "2"]) == 0
    name = capsys.readouterr().out.strip()
    directory = product / "rooms" / name
    deadline = time.time() + 60
    while time.time() < deadline:
        status = progress.read(directory) or {}
        if status.get("state") in ("done", "failed", "cancelled"):
            break
        time.sleep(0.2)
    assert status["state"] == "done", (directory / "run.log").read_text()
    assert cli.main(["status", name]) == 0
    assert "done" in capsys.readouterr().out
    assert cli.main(["findings", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in result["new"]] == ["greeting-wrong-case-02"]


@posix_only
def test_a_detached_run_can_be_cancelled_and_unwinds(product, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "30")
    assert cli.main(["run", "2"]) == 0
    name = capsys.readouterr().out.strip()
    directory = product / "rooms" / name
    deadline = time.time() + 30
    while time.time() < deadline:
        if (progress.read(directory) or {}).get("rooms", {}).get("02_thing", {}).get(
                "phase") == "room":
            break
        time.sleep(0.1)
    assert cli.main(["cancel", name]) == 0
    deadline = time.time() + 30
    while time.time() < deadline:
        if (progress.read(directory) or {}).get("state") == "cancelled":
            break
        time.sleep(0.1)
    status = progress.read(directory)
    assert status["state"] == "cancelled" and (directory / "FINDINGS.md").exists()


def test_restore_asks_the_adapter(product, capsys):
    assert cli.main(["restore"]) == 0
    assert "nothing to restore" in capsys.readouterr().out


# --- init ----------------------------------------------------------------------------

def test_init_installs_the_skill_stamped_and_is_idempotent(tmp_path):
    said = []
    assert install.init(tmp_path, rooms="cleanroom", say=said.append) == 0
    skill = tmp_path / ".claude" / "skills" / "quality-loop" / "SKILL.md"
    text = skill.read_text()
    assert f'quality-loop-version: "{quality_loop.__version__}"' in text
    assert "__QUALITY_LOOP_VERSION__" not in text
    assert (skill.parent / "references" / "setup.md").exists()
    settings = (tmp_path / "qa" / "quality-loop.toml").read_text()
    assert 'rooms = "cleanroom"' in settings and "command = " in settings
    assert "/cleanroom/" in (tmp_path / ".gitignore").read_text()
    before = [p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()]
    assert install.init(tmp_path, say=said.append) == 0
    after = [p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()]
    assert before == after, "a second init changes nothing"


def test_an_upgrade_leaves_a_hand_edited_skill_alone(tmp_path):
    install.init(tmp_path, say=lambda _t: None)
    skill = tmp_path / ".claude" / "skills" / "quality-loop" / "SKILL.md"
    skill.write_text(skill.read_text() + "\nMy own rule.\n")
    said = []
    assert install.init(tmp_path, upgrade=True, say=said.append) == 1
    assert "My own rule." in skill.read_text() and "edited by hand" in said[0]
    assert install.init(tmp_path, upgrade=True, force=True, say=said.append) == 0
    assert "My own rule." not in skill.read_text()


def test_the_command_found_is_relative_inside_the_checkout(tmp_path, monkeypatch):
    # The venv's own layout: Scripts/quality-loop.exe on Windows.
    bin_dir = tmp_path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir(parents=True)
    script = "quality-loop.exe" if os.name == "nt" else "quality-loop"
    (bin_dir / script).write_text("")
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python"))
    monkeypatch.setattr(install.shutil, "which", lambda _name: None)
    assert install.command_for(tmp_path) == (bin_dir / script).relative_to(tmp_path).as_posix()
    assert install.commands_for(tmp_path) == {
        "command": ".venv/bin/quality-loop",
        "command_windows": ".venv/Scripts/quality-loop.exe"}


def test_the_conductor_skill_counts_as_a_leaked_scoring_key(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({"type": "system", "subtype": "init", "tools": [],
                                      "slash_commands": ["quality-loop"],
                                      "mcp_servers": []}))
    policy = audit.Policy(checkout=tmp_path, leaked_skill=lambda c: "quality-loop" in c)
    assert audit.isolation_held(transcript, policy)
