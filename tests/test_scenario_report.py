"""Scenarios are read as written, and reports are read the way a loop needs."""

import json

import pytest

from quality_loop import report, scenario

SCENARIO = """\
+++
title = "Stop F1 doing anything in VS Code"
edits_config = true
configs = ["template", "short"]
+++

## Prompt

I keep hitting F1 by accident in VS Code.
Make F1 do nothing in VS Code - everywhere else it should stay as it is.

## Screen

None.

## Must

- With VS Code focused, F1 does nothing.

```text
## Not a heading - inside a fence
```

## Must not

- Bind F1 in the global table.
"""


def _file(tmp_path, text, name="11_f1_off_in_vscode.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_scenario_is_read_as_written(tmp_path):
    found = scenario.parse(_file(tmp_path, SCENARIO))
    assert found.title == "Stop F1 doing anything in VS Code"
    assert found.number == 11 and found.name == "11_f1_off_in_vscode"
    assert found.meta["configs"] == ["template", "short"] and found.meta["edits_config"]
    assert found.prompt == ("I keep hitting F1 by accident in VS Code.\n"
                            "Make F1 do nothing in VS Code - everywhere else it "
                            "should stay as it is.\n")
    assert list(found.sections) == ["Prompt", "Screen", "Must", "Must not"]
    assert "## Not a heading" in found.section("Must"), "fenced text is not a heading"
    assert found.section("Nope") == ""


def test_crlf_files_read_the_same(tmp_path):
    found = scenario.parse(_file(tmp_path, SCENARIO.replace("\n", "\r\n")))
    assert "\r" not in found.prompt


@pytest.mark.parametrize("broken,said", [
    (SCENARIO.replace("+++\ntitle", "title", 1), "front matter"),
    (SCENARIO.replace('title = "Stop F1 doing anything in VS Code"\n', ""), "no title"),
    (SCENARIO.replace("## Prompt", "## Prelude"), "no Prompt"),
    (SCENARIO.replace("edits_config = true", "edits_config = "), "front matter"),
])
def test_a_scenario_that_cannot_run_says_why(tmp_path, broken, said):
    with pytest.raises(scenario.ScenarioError, match=said):
        scenario.parse(_file(tmp_path, broken))


def test_a_must_line_in_the_prompt_is_refused(tmp_path):
    """The scoring key reaching the room, by a copy-paste one line too long."""
    leaked = SCENARIO.replace(
        "everywhere else it should stay as it is.\n",
        "everywhere else it should stay as it is.\n"
        "- With VS Code focused, F1 does nothing.\n")
    with pytest.raises(scenario.ScenarioError, match="scoring key"):
        scenario.parse(_file(tmp_path, leaked))


def test_scenarios_are_picked_by_number_or_name(tmp_path):
    _file(tmp_path, SCENARIO, "11_f1_off_in_vscode.md")
    _file(tmp_path, SCENARIO, "04_approve_queue.md")
    _file(tmp_path, "notes", "README.md")
    assert [s.name for s in scenario.load(tmp_path)] == [
        "04_approve_queue", "11_f1_off_in_vscode"]
    assert [s.number for s in scenario.load(tmp_path, ["11", "approve_queue"])] == [11, 4]
    with pytest.raises(scenario.ScenarioError, match="no scenario"):
        scenario.load(tmp_path, ["99"])


REPORT = """\
# Report

### [high] F1 binding misses Fn+F1 on macOS
- **Id:** `fn-f1-not-bound`
- **Kind:** Skill gap
- **Must:** "With VS Code focused, F1 does nothing"
- **Evidence:** `replay --app Code --keys Fn-F1` -> consumed: false
- **Where it would be fixed:** references/configuration.md
- **How a fix is confirmed:** re-run; the same replay reports consumed: true

The room bound F1 alone.

### [low] An empty search
- **Id:** `empty-search`
- **Kind:** harness
- **Evidence:** step 12, Grep 'swallow' came back empty

### [urgent] Something without an id
- **Kind:** whatever
"""


def test_a_report_is_read_the_way_a_loop_needs_it():
    problems, malformed = report.parse(REPORT, room="11")
    assert [(p.severity, p.id, p.kind) for p in problems] == [
        ("high", "fn-f1-not-bound", "skill gap"), ("low", "empty-search", "harness"),
        ("urgent", "", "whatever")]
    first = problems[0]
    assert first.where == "references/configuration.md"
    assert first.confirm.startswith("re-run") and first.detail == "The room bound F1 alone."
    assert any("severity 'urgent'" in m for m in malformed)
    assert any("kind 'whatever'" in m for m in malformed)
    assert any("no id" in m for m in malformed) and any("no evidence" in m for m in malformed)


def test_a_field_continued_as_a_nested_list_is_kept():
    problems, malformed = report.parse(
        "### [medium] Defaults pasted in\n"
        "- **Id:** `extend-default`\n"
        "- **Kind:** product\n"
        "- **Evidence:**\n"
        "  - 66 new lines in a 14-line file\n"
        "  - config.md says to copy the defaults\n"
        "- **Where it would be fixed:** config.md\n"
        "\n"
        "  An indented paragraph after a blank line is free text.\n")
    assert not malformed
    assert problems[0].evidence == ("- 66 new lines in a 14-line file\n"
                                    "- config.md says to copy the defaults")
    assert problems[0].where == "config.md"
    assert "indented paragraph" in problems[0].detail


def test_findings_concatenate_and_count_most_severe_first(tmp_path):
    path = report.write_findings(tmp_path, [
        ("11_f1", "F1 off", REPORT),
        ("12_emacs", "Emacs keys", "### [critical] Rewrote the config\n"
                                   "- **Id:** `rewrote`\n- **Evidence:** 4 of 400 lines kept\n"),
        ("13_cx", "Ctrl-X", ""),
    ])
    text = path.read_text()
    assert "3 room(s): 1 critical, 1 high, 0 medium, 1 low" in text
    assert text.index("| critical | 12_emacs") < text.index("| high | 11_f1")
    assert "(no report - the operator wrote nothing)" in text
    assert "**malformed report**" in text
    machine = json.loads((tmp_path / "findings.json").read_text())
    assert [p["id"] for p in machine][:2] == ["rewrote", "fn-f1-not-bound"]
