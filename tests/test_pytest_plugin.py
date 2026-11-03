"""The desktop and host_only marks, run in a pytest of their own."""

import os
import subprocess
import sys


SUITE = """
import pytest

def test_plain():
    pass

@pytest.mark.desktop
def test_on_the_desktop():
    pass

@pytest.mark.host_only
def test_of_the_tooling():
    pass
"""


def _run(tmp_path, *args, guest=None):
    (tmp_path / "test_marks.py").write_text(SUITE, encoding="utf-8")
    environ = {k: v for k, v in os.environ.items() if k != "QUALITY_LOOP_IN_GUEST"}
    if guest:
        environ["QUALITY_LOOP_IN_GUEST"] = guest
    said = subprocess.run([sys.executable, "-m", "pytest", "-p", "quality_loop.pytest_plugin",
                           "-p", "no:cacheprovider", "--strict-markers", "-rs", "-v",
                           *args, "test_marks.py"],
                          cwd=tmp_path, capture_output=True, text=True, env=environ)
    return said.returncode, said.stdout + said.stderr


def _outcomes(out):
    return {name: outcome for name in ("plain", "on_the_desktop", "of_the_tooling")
            for line in out.splitlines() if f"test_{name} " in line
            for outcome in ("PASSED", "SKIPPED") if outcome in line}


def test_on_the_host_desktop_tests_wait_for_a_vm(tmp_path):
    code, out = _run(tmp_path)
    assert code == 0, out
    assert _outcomes(out) == {"plain": "PASSED", "on_the_desktop": "SKIPPED",
                              "of_the_tooling": "PASSED"}
    assert "run it in a VM" in out


def test_in_a_guest_with_desktop_the_tooling_tests_are_skipped(tmp_path):
    code, out = _run(tmp_path, "--desktop", guest="qa-mac")
    assert code == 0, out
    assert _outcomes(out) == {"plain": "PASSED", "on_the_desktop": "PASSED",
                              "of_the_tooling": "SKIPPED"}
    assert "this is the guest qa-mac" in out


def test_host_only_runs_just_the_tooling_tests(tmp_path):
    code, out = _run(tmp_path, "--host-only")
    assert code == 0, out
    assert _outcomes(out) == {"of_the_tooling": "PASSED"}
    assert "2 deselected" in out


def test_host_only_is_refused_in_a_guest(tmp_path):
    code, out = _run(tmp_path, "--host-only", guest="qa-win")
    assert code != 0 and "--host-only in a guest" in out
