"""The operator's session is narrow, two-phased, and cannot touch the room."""

import json
import pathlib

import pytest

from quality_loop import operator


@pytest.fixture
def op(tmp_path):
    room = tmp_path / "rooms" / "11_f1"
    room.mkdir(parents=True)
    (room / "TASK.md").write_text("# The task\n\nMake F1 do nothing.\n")
    manifest_dir = tmp_path / "private"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text("{}")
    return operator.Operator(
        room=room, directory=tmp_path / "rooms" / "11_f1.operator",
        scenario=tmp_path / "scenarios" / "11_f1.md", checkout=tmp_path / "checkout",
        evidence_help="replay presses keys through the product's engine.",
        manifest=manifest_dir / "manifest.json", python="/venv/python", claude="claude")


def _value(command, flag):
    return command[command.index(flag) + 1]


def test_the_operator_has_no_shell_and_only_quality_loop_s_server(op):
    command = op.command(1, "go")
    assert command[:2] == ["claude", "--restricted"]
    assert _value(command, "--tools") == "Read,Glob,Grep,Write,Edit", "no Bash"
    servers = json.loads(_value(command, "--mcp-config"))["mcpServers"]
    assert list(servers) == ["quality-loop"], "never the product's own"
    assert servers["quality-loop"]["args"] == ["-m", "quality_loop.mcp"]
    assert servers["quality-loop"]["env"]["QUALITY_LOOP_MANIFEST"] == str(op.manifest)
    assert "--strict-mcp-config" in command
    allow = json.loads(_value(command, "--settings"))["permissions"]["allow"]
    assert not [rule for rule in allow if rule.startswith("Bash")]
    assert "Write" not in allow and "Edit" not in allow
    assert "mcp__quality-loop" in allow
    writes = [rule for rule in allow if rule.startswith(("Write(", "Edit("))]
    assert writes == [f"Edit(/{op.directory.resolve().as_posix()}/**)",
                      f"Edit(/{(op.room.resolve() / 'REPORT.md').as_posix()})"]
    assert all(rule.startswith("Edit(//") for rule in writes), "absolute: //"
    assert _value(command, "--permission-mode") == "dontAsk"


def test_a_windows_path_is_spelled_the_way_permission_rules_want(monkeypatch):
    class Resolved:
        def __init__(self, *_):
            pass

        def resolve(self):
            return self

        def as_posix(self):
            return "C:/Users/me/rooms/r"

    monkeypatch.setattr(operator.pathlib, "Path", Resolved)
    assert operator.absolute("ignored") == "//c/Users/me/rooms/r"


def test_the_two_phases_are_one_session(op):
    first, second = op.command(1, "a"), op.command(2, "b")
    assert _value(first, "--session-id") == op.session_id
    assert _value(second, "--resume") == op.session_id
    assert "--session-id" not in second and "--no-session-persistence" not in first


def test_the_messages_name_the_paths_and_tools_and_never_the_must_list(op):
    one = op.phase_one_message("mac")
    assert str(operator.INSTRUCTIONS) in one and str(op.scenario) in one
    assert "screen_open" in one
    two = op.phase_two_message()
    assert "`evidence` tool" in two and "--help" in two
    assert str(op.room / "REPORT.md") in two


def test_the_operator_s_git_stops_at_the_rooms(op):
    assert op.environment()["GIT_CEILING_DIRECTORIES"]


def _fake_agent(monkeypatch, effect):
    class Agent:
        def __init__(self, command, **kwargs):
            self.command = command
            effect(command, kwargs)
            self.stdout = iter([json.dumps({"type": "result", "num_turns": 3}) + "\n"])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def wait(self):
            return 0

    monkeypatch.setattr(operator.subprocess, "Popen", Agent)


def test_phase_one_that_leaves_the_room_alone_passes_and_is_logged(op, monkeypatch):
    seen = {}
    _fake_agent(monkeypatch, lambda command, kwargs: seen.update(kwargs))
    op.phase_one("mac", say=lambda _: None)
    assert seen["cwd"] == op.directory and seen["stdin"] is operator.subprocess.DEVNULL
    assert (op.directory / "phase1.jsonl").exists()


@pytest.mark.parametrize("touch", [
    lambda room: (room / "TASK.md").write_text("# The task\n\nMake F1 do nothing. Hint: lambda.\n"),
    lambda room: (room / "NOTES.md").write_text("a note for the room\n"),
    lambda room: (room / "TASK.md").unlink(),
])
def test_phase_one_that_touches_the_room_cancels_it(op, monkeypatch, touch):
    _fake_agent(monkeypatch, lambda command, kwargs: touch(op.room))
    with pytest.raises(operator.OperatorError, match="cancelled"):
        op.phase_one("mac", say=lambda _: None)


def test_the_instructions_say_what_a_loop_reads(op):
    text = operator.INSTRUCTIONS.read_text()
    for needed in ("**Id:**", "**Where it would be fixed:**", "**How a fix is confirmed:**",
                   "critical", "out of scope", "TASK.md"):
        assert needed in text
