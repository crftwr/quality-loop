"""A run: for each scenario, a room, its operator, and a report.

    build the room (TASK.md is the scenario's Prompt, verbatim)
    stand fixtures in for the operator's files
    serve the fixture pages, write the screen manifest
    operator phase 1 - puts the screen up; the room must come out unchanged
    the room's session
    collect evidence, put the operator's files back
    audit the transcript
    operator phase 2 - writes REPORT.md
    close any screen still open
    ...
    FINDINGS.md and findings.json, concatenated from the reports

There is no verdict. A room that could not be measured - a cancelled phase 1,
an isolation breach, a lost product or model - still gets a report, written
here as a harness problem, so the human reading the findings sees it.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import pathlib
import shutil
import signal
import sys
import tempfile

from quality_loop import (audit, operator, pages, report, room, scenario, screens,
                          transcript)


class RunnerError(Exception):
    """A room the runner will not start."""


def refuse_a_reachable_marker(marker: pathlib.Path, built: pathlib.Path,
                              add_dirs: list[pathlib.Path]) -> None:
    """The operator's set-aside files must be out of the room's reach.

    The first run of the toy put them inside the one directory the room could
    write to. The room saw a second style.txt beside the fixture and ignored
    it. A room that read it would have measured the harness, and one that
    wrote to it could have touched the operator's own file.
    """
    marker = pathlib.Path(marker).resolve()
    for reach in [built, *add_dirs]:
        reach = pathlib.Path(reach).resolve()
        if marker == reach or reach in marker.parents:
            raise RunnerError(
                f"the stand-in keeps the operator's files in {marker}, inside {reach}, "
                f"which the room can reach - put the marker outside it")


def _cancelled(case, what: str, problem_id: str, evidence: str) -> str:
    return (f"# Report: {case.title}\n\nThis room could not be measured.\n\n"
            f"### [critical] {what}\n- **Id:** `{problem_id}`\n- **Kind:** harness\n"
            f"- **Evidence:** {evidence}\n- **Where it would be fixed:** the runner\n"
            f"- **How a fix is confirmed:** the room runs and is reported on\n")


def run(adapter, names: list[str] | None = None, model: str | None = None,
        operator_model: str | None = None, say=print) -> pathlib.Path:
    """Run every scenario ``names`` picks, and return FINDINGS.md's path."""
    sys.stdout.reconfigure(line_buffering=True)
    # SIGTERM unwinds like Ctrl-C, so the stand-in puts the operator's files
    # back instead of dying with them set aside.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    cases = scenario.load(adapter.scenarios, names)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    parent = adapter.rooms / f"{adapter.version}-{stamp}"
    parent.mkdir(parents=True)
    say(f"rooms:   {parent}")
    reports: list[tuple[str, str, str]] = []
    bundle = adapter.bundle()
    try:
        with adapter.product():
            for case, variant in adapter.runs(cases):
                label = case.name + (f".{variant}" if variant else "")
                say(f"\n== {label}: {case.title}")
                reports.append((label, case.title, _one(
                    adapter, case, variant, parent / label, bundle, model,
                    operator_model, say)))
    except KeyboardInterrupt:
        say("\n  interrupted - the room in progress was collected and the "
            "operator's files put back")
    findings = report.write_findings(parent, reports)
    say(f"\n  findings: {findings}")
    return findings


def _one(adapter, case, variant, here: pathlib.Path, bundle, model, operator_model,
         say) -> str:
    built = room.build(here, prompt=case.prompt, rules=adapter.rules(), bundle=bundle,
                       skill_name=adapter.skill_name, rooms=adapter.rooms,
                       checkout=adapter.checkout)
    evidence = built / "evidence"
    evidence.mkdir()
    private = pathlib.Path(tempfile.mkdtemp(prefix="quality-loop-private-"))
    directory = here.with_name(here.name + ".operator")
    session = adapter.session(built)
    if model:
        session.model = model
    stand_in = adapter.stand_in(case, variant, built)
    if stand_in is not None:
        refuse_a_reachable_marker(stand_in.marker, built, session.add_dirs)
    stand_in = stand_in or contextlib.nullcontext()
    served = pages.Pages(adapter.fixtures) if adapter.fixtures else contextlib.nullcontext()
    op = None
    try:
        with stand_in, served as site:
            manifest = screens.write_manifest(
                private / "manifest.json", adapter.screens,
                fixtures=adapter.fixtures or adapter.checkout,
                origin=site.origin if site else "", python=adapter.python,
                state=directory, evidence=adapter.evidence)
            op = operator.Operator(
                room=built, directory=directory, scenario=case.path,
                checkout=adapter.checkout,
                evidence_help=adapter.evidence_help, manifest=manifest,
                python=adapter.python, model=operator_model)
            say("  operator: phase 1 - the screen")
            op.phase_one(sys.platform, say=say)
            say("  room:    running")
            ran = session.run(built, alive=adapter.alive, say=say)
            if site:
                site.write(evidence / "screen-events.jsonl")
        (evidence / "run.json").write_text(json.dumps(
            {"scenario": case.name, "variant": variant, "platform": sys.platform,
             "exit_code": ran.exit_code, "product_lost": ran.product_lost,
             "model_lost": transcript.lost_the_model(ran.transcript)}, indent=2),
            encoding="utf-8")
        breaches, refused = audit.audit(built, adapter.policy(built))
        (evidence / "audit.json").write_text(json.dumps(
            {"breaches": breaches, "refused": refused}, indent=2), encoding="utf-8")
        for line in breaches:
            say(f"  BREACH: {line}")
        say("  operator: phase 2 - the report")
        written = op.phase_two(say=say)
        text = written.read_text(encoding="utf-8") if written.exists() else ""
        if breaches:
            text = _cancelled(case, "The room broke isolation; nothing it did is evidence",
                              "isolation-breach", "; ".join(breaches)) + "\n" + text
        if ran.product_lost or transcript.lost_the_model(ran.transcript):
            what = "the product" if ran.product_lost else "the model's API"
            text = _cancelled(case, f"{what} stopped answering during the run",
                              "lost-" + ("product" if ran.product_lost else "model"),
                              "run.json") + "\n" + text
        return text
    except operator.OperatorError as error:
        say(f"  CANCELLED: {error}")
        return _cancelled(case, "Operator phase 1 changed the room", "phase-one-touched-room",
                          str(error))
    finally:
        closed = screens.close_all(directory) if directory.exists() else []
        if closed:
            say(f"  closed:  {', '.join(closed)} (left open by the operator)")
        shutil.rmtree(private, ignore_errors=True)
