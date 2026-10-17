"""The parts of a run that must hold whatever the product: the room, the
session's flags, the audit, the transcript reader, the stand-in and the pages.

Ported from the two harnesses this package replaces - Keyhac's and XeFM's
clean rooms - so each fix either of them paid for is kept here once.
"""

import json
import os
import pathlib
import subprocess
import urllib.request
import zipfile

import pytest

from quality_loop import audit, pages, room, session, standin, transcript


def _write(path, events):
    path.write_text("\n".join(json.dumps(e) if not isinstance(e, str) else e
                              for e in events), encoding="utf-8")
    return path


INIT = {"type": "system", "subtype": "init", "tools": ["Read"], "slash_commands": [],
        "mcp_servers": [{"name": "product", "status": "connected"}]}


# --- transcript ------------------------------------------------------------------

def test_the_reader_survives_every_shape_a_real_transcript_has(tmp_path):
    """A refusal can arrive as a system event whose message is a string; it
    crashed every real room of the first XeFM harness."""
    path = _write(tmp_path / "t.jsonl", [
        "not json at all",
        '["a list, not an object"]',
        {"type": "system", "subtype": "notice", "message": "Permission denied"},
        {"type": "user", "message": {"content": "a string, not parts"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/x"}},
            "a stray string part"]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "a", "is_error": True,
             "content": [{"type": "text", "text": "refused"}]}]}},
        {"type": "result", "result": "done"},
    ])
    calls = transcript.tool_calls(path)
    assert [(c.name, c.result, c.is_error, c.answered) for c in calls] == [
        ("Read", "refused", True, True)]
    assert transcript.final_reply(path) == "done"


def test_the_init_event_is_found_wherever_it_is(tmp_path):
    path = _write(tmp_path / "t.jsonl", [{"type": "rate_limit_event"}, INIT])
    assert transcript.init_event(path) == INIT


def test_a_session_that_lost_the_model_is_known(tmp_path):
    """A machine woke from sleep with no network, and the run looked ordinary."""
    lost = _write(tmp_path / "lost.jsonl", [
        {"type": "assistant", "error": "server_error", "message": {"content": [
            {"type": "text", "text": "API Error: Can't reach the API server"}]}},
        {"type": "result", "subtype": "success", "is_error": True}])
    fine = _write(tmp_path / "fine.jsonl", [
        {"type": "result", "subtype": "success", "is_error": False}])
    assert transcript.lost_the_model(lost) and not transcript.lost_the_model(fine)


# --- room ------------------------------------------------------------------------

@pytest.fixture
def bundle(tmp_path):
    path = tmp_path / "product-skill.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SKILL.md", "---\nname: product\n---\n")
    return path


def test_a_room_holds_the_bundle_the_rules_and_the_prompt_and_nothing_else(tmp_path, bundle):
    built = room.build(tmp_path / "rooms" / "r", prompt="  Do the thing.\n",
                       rules="# rules\n", bundle=bundle, skill_name="product",
                       rooms=tmp_path / "rooms")
    assert sorted(p.name for p in built.iterdir()) == [
        "CLAUDE.md", "QUESTIONS.md", "RULES.md", "TASK.md", "skills"]
    assert (built / "skills" / "product" / "SKILL.md").exists()
    assert (built / "TASK.md").read_text() == "# The task\n\nDo the thing.\n"
    assert audit.CANARY_PHRASE in (built / "CLAUDE.md").read_text()


def test_a_bundle_directory_goes_in_without_its_bytecode(tmp_path):
    source = tmp_path / "skill"
    (source / "__pycache__").mkdir(parents=True)
    (source / "SKILL.md").write_text("x")
    (source / "__pycache__" / "a.pyc").write_bytes(b"\0")
    built = room.build(tmp_path / "rooms" / "r", prompt="p", rules="r", bundle=source,
                       skill_name="s", rooms=tmp_path / "rooms")
    assert [p.name for p in (built / "skills" / "s").iterdir()] == ["SKILL.md"]


def test_a_room_inside_the_checkout_but_not_under_rooms_is_refused(tmp_path, bundle):
    checkout = tmp_path / "checkout"
    with pytest.raises(room.RoomError, match="inside the checkout"):
        room.build(checkout / "src" / "r", prompt="p", rules="r", bundle=bundle,
                   skill_name="s", rooms=checkout / "cleanroom", checkout=checkout)
    room.build(checkout / "cleanroom" / "r", prompt="p", rules="r", bundle=bundle,
               skill_name="s", rooms=checkout / "cleanroom", checkout=checkout)


def test_a_room_that_is_not_empty_is_refused(tmp_path, bundle):
    (tmp_path / "rooms" / "r").mkdir(parents=True)
    (tmp_path / "rooms" / "r" / "left.txt").write_text("x")
    with pytest.raises(room.RoomError, match="not empty"):
        room.build(tmp_path / "rooms" / "r", prompt="p", rules="r", bundle=bundle,
                   skill_name="s", rooms=tmp_path / "rooms")


# --- session ---------------------------------------------------------------------

def _session(**extra):
    return session.Session(allow=["Read", "mcp__product"], claude="claude",
                           mcp_servers={"product": {"command": "bridge"}}, **extra)


def test_the_session_is_restricted_and_refuses_what_is_not_granted():
    command = _session().command()
    assert command[:2] == ["claude", "--restricted"]
    assert "--strict-mcp-config" in command and "--no-session-persistence" in command
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert command[command.index("-p") + 1] == session.PROMPT
    assert "bypassPermissions" not in " ".join(command)
    assert json.loads(command[command.index("--settings") + 1]) == {
        "permissions": {"allow": ["Read", "mcp__product"]}}
    assert "--tools" not in command, "no --tools: --restricted's default, no Bash"
    narrowed = _session(tools=["Read", "Bash"]).command()
    assert narrowed[narrowed.index("--tools") + 1] == "Read,Bash"


def test_git_in_a_room_finds_no_repository(tmp_path):
    """The room may be inside a checkout; with the ceiling, git stops at it."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    inside = tmp_path / "rooms" / "r"
    inside.mkdir(parents=True)
    asked = subprocess.run(["git", "log", "-1"], cwd=inside, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL,
                           env=_session().environment(inside))
    assert asked.returncode != 0 and audit.NOT_A_REPOSITORY in asked.stderr


def test_the_session_starts_with_stdin_closed_and_the_ceiling_set(tmp_path, monkeypatch):
    started = {}

    class Fake:
        stdout = iter([json.dumps({"type": "result", "num_turns": 1}) + "\n"])

        def __init__(self, command, **kwargs):
            started.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def poll(self):
            return 0

        def wait(self):
            return 0

    monkeypatch.setattr(session.subprocess, "Popen", Fake)
    monkeypatch.setattr(session.tempfile, "gettempdir", lambda: str(tmp_path))
    inside = tmp_path / "rooms" / "r"
    inside.mkdir(parents=True)
    run = _session(env={"SHELL": "/bin/bash"}).run(inside, say=lambda _: None)
    assert started["stdin"] is subprocess.DEVNULL
    assert started["env"]["GIT_CEILING_DIRECTORIES"] == str(inside.resolve().parent)
    assert started["env"]["SHELL"] == "/bin/bash"
    assert run.exit_code == 0 and run.transcript.exists(), "moved into the room"


@pytest.mark.parametrize("shell", ["posix", "powershell"])
def test_the_printed_command_carries_every_flag_and_the_ceiling(tmp_path, shell):
    printed = _session().printable(tmp_path / "r", shell)
    assert "--restricted" in printed and "--strict-mcp-config" in printed
    assert "GIT_CEILING_DIRECTORIES" in printed
    assert ("$env:GIT_CEILING_DIRECTORIES" in printed) == (shell == "powershell")


# --- audit -----------------------------------------------------------------------

def _audited(tmp_path, calls, results=(), init=INIT, reply="done", **policy):
    checkout = tmp_path / "checkout"
    inside = checkout / "cleanroom" / "r"
    inside.mkdir(parents=True)
    events = [init, {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": str(n), "name": name,
         "input": given(checkout, inside) if callable(given) else given}
        for n, (name, given) in enumerate(calls)]}}]
    for n, text, error in results:
        events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": str(n), "content": text,
             "is_error": error}]}})
    events.append({"type": "result", "result": reply})
    _write(inside / "transcript.jsonl", events)
    return audit.audit(inside, audit.Policy(checkout=checkout, **policy))


def test_the_checkout_in_either_spelling_is_a_breach_and_the_room_is_not(tmp_path):
    breaches, refused = _audited(tmp_path, [
        ("Read", lambda c, r: {"file_path": str(c / "src" / "core.py")}),
        ("Glob", lambda c, r: {"path": str(c / "examples").replace("/", "\\")}),
        ("Read", lambda c, r: {"file_path": str(r / "skills" / "s" / "SKILL.md")}),
    ])
    assert any("core.py" in b for b in breaches)
    assert any("examples" in b for b in breaches)
    assert not any("SKILL.md" in b for b in breaches) and refused == []


def test_a_refused_reach_is_reported_and_does_not_disqualify(tmp_path):
    breaches, refused = _audited(
        tmp_path, [("Read", lambda c, r: {"file_path": str(c / "src" / "core.py")})],
        results=[(0, "outside the working directories", True)])
    assert breaches == [] and any("core.py" in r for r in refused)


@pytest.mark.parametrize("answer,breach", [
    ("fatal: not a git repository (or any of the parent directories): .git", False),
    ("2384065 Merge pull request #195", True),
])
def test_every_git_call_is_reported(tmp_path, answer, breach):
    breaches, refused = _audited(
        tmp_path, [("Bash", {"command": "cat RULES.md; /usr/bin/git log --oneline"}),
                   ("Bash", {"command": "echo digit"})],
        results=[(0, answer, False)], bash=True)
    ran = [line for line in (breaches if breach else refused) if "ran git" in line]
    assert len(ran) == 1
    assert not [line for line in (refused if breach else breaches) if "ran git" in line]


def test_forbidden_paths_and_other_authors_work(tmp_path):
    breaches, _ = _audited(tmp_path, [
        ("Read", {"file_path": "/x/site-packages/product/core.py"}),
        ("Read", {"file_path": "/home/me/.product/extensions/theirs.py"}),
    ], forbidden={"site-packages/product": "the installed package"},
        foreign={"theirs.py"})
    assert any("installed package" in b for b in breaches)
    assert any("another author" in b for b in breaches)


def test_what_the_init_event_and_the_reply_give_away(tmp_path):
    init = {"type": "system", "subtype": "init", "tools": ["Read", "Bash"],
            "slash_commands": ["product-cleanroom"],
            "mcp_servers": [{"name": "product", "status": "failed"}]}
    breaches, _ = _audited(tmp_path, [], init=init,
                           reply="The room was opened without `--restricted`.",
                           servers=("product",),
                           leaked_skill=lambda c: c.startswith("product"))
    text = " ".join(breaches)
    assert "had Bash" in text and "own skills" in text
    assert "was failed" in text and "canary" in text


# --- stand-in --------------------------------------------------------------------

@pytest.fixture
def machine(tmp_path):
    home = tmp_path / "home"
    (home / "extensions").mkdir(parents=True)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (home / "config.py").write_text("# the operator's own\n")
    (home / "config.py.bak-20260101").write_text("# an old backup\n")
    (home / "endpoint.json").write_text("{}")
    (home / "extensions" / "theirs.py").write_text("# someone else's\n")
    (desktop / "notes.txt").write_text("mine\n")
    (tmp_path / "input.csv").write_text("id\n")
    return home, desktop


def _stand_in(tmp_path, home, desktop, reloads):
    return standin.StandIn(
        home=home, marker=home / "quality-loop-stand-in",
        fixtures={"config.py": "# the fixture\n"}, evidence=tmp_path / "room" / "evidence",
        backups="config.py.bak-*",
        watch=[standin.Watch(home / "extensions", "extensions"),
               standin.Watch(desktop, "desktop"),
               standin.Watch(home, "home", skip=("endpoint.json",))],
        staged=[(tmp_path / "input.csv", desktop / "input.csv")],
        on_change=lambda: reloads.append(1))


def test_the_operator_s_files_come_back_and_everything_new_is_collected(tmp_path, machine):
    home, desktop = machine
    reloads = []
    with pytest.raises(KeyboardInterrupt):
        with _stand_in(tmp_path, home, desktop, reloads):
            assert (home / "config.py").read_text() == "# the fixture\n"
            (home / "extensions" / "act.py").write_text("x = 1\n")
            (home / "extensions" / "helpers").mkdir()
            (home / "config.py.bak-20991231").write_text("# the fixture\n")
            (home / "config.py.bak-20260101").unlink()          # pruned by the product
            (home / "endpoint.json.tmp").write_text("{}")      # the product's own
            (desktop / "report.txt").write_text("done\n")
            (home / "config.py").write_text("# the fixture\n# edited\n")
            raise KeyboardInterrupt
    assert (home / "config.py").read_text() == "# the operator's own\n"
    assert (home / "config.py.bak-20260101").exists(), "a pruned backup came back"
    assert not (home / "quality-loop-stand-in").exists()
    assert sorted(p.name for p in (home / "extensions").iterdir()) == ["theirs.py"]
    assert sorted(p.name for p in desktop.iterdir()) == ["notes.txt"]
    assert (home / "endpoint.json.tmp").exists(), "the product's own file was left alone"
    evidence = tmp_path / "room" / "evidence"
    assert sorted(p.name for p in (evidence / "extensions").iterdir()) == ["act.py", "helpers"]
    assert sorted(p.name for p in (evidence / "desktop").iterdir()) == [
        "input.csv", "report.txt"]
    assert [p.name for p in (evidence / "home").iterdir()] == ["config.py.bak-20991231"]
    assert (evidence / "after" / "config.py").read_text().endswith("# edited\n")
    assert (evidence / "before" / "config.py").read_text() == "# the fixture\n"
    assert len(reloads) == 2


def test_a_marker_left_behind_refuses_the_next_run_until_restored(tmp_path, machine):
    home, desktop = machine
    marker = home / "quality-loop-stand-in"
    marker.mkdir()
    os.replace(home / "config.py", marker / "config.py")
    (home / "config.py").write_text("# the fixture, left in place\n")
    with pytest.raises(standin.StandInError, match="restore"):
        _stand_in(tmp_path, home, desktop, []).__enter__()
    standin.restore(marker, home, ["config.py"])
    assert (home / "config.py").read_text() == "# the operator's own\n"
    assert (home / "config.py.quality-loop-fixture").exists()
    assert not marker.exists()


def test_a_staged_file_never_overwrites_the_operator_s(tmp_path, machine):
    home, desktop = machine
    (desktop / "input.csv").write_text("theirs\n")
    with pytest.raises(standin.StandInError, match="already exists"):
        _stand_in(tmp_path, home, desktop, []).__enter__()
    assert (desktop / "input.csv").read_text() == "theirs\n"
    assert (home / "config.py").read_text() == "# the operator's own\n"


# --- pages -----------------------------------------------------------------------

def test_the_pages_are_served_and_what_is_done_on_them_is_recorded(tmp_path):
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "page.html").write_text("<title>Queue</title>")
    with pages.Pages(tmp_path / "fixtures") as served:
        with urllib.request.urlopen(served.url("page.html")) as reply:
            assert b"Queue" in reply.read()
        request = urllib.request.Request(
            served.url("event"), data=json.dumps({"what": "approve"}).encode(),
            method="POST")
        with urllib.request.urlopen(request) as reply:
            assert reply.status == 204
        served.write(tmp_path / "events.jsonl")
    assert served.events == [{"what": "approve"}]
    assert "file://" not in served.origin and served.origin.startswith("http://127.0.0.1:")


def test_a_marker_the_room_can_reach_is_refused(tmp_path):
    from quality_loop import runner
    home, built = tmp_path / "home", tmp_path / "rooms" / "r"
    with pytest.raises(runner.RunnerError, match="can reach"):
        runner.refuse_a_reachable_marker(home / "stand-in", built, [home])
    with pytest.raises(runner.RunnerError, match="can reach"):
        runner.refuse_a_reachable_marker(built / "stand-in", built, [])
    runner.refuse_a_reachable_marker(tmp_path / "aside" / "stand-in", built, [home])
