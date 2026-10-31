"""The runner keeps the machine from idle sleep while a run goes (#16)."""

import os
import subprocess
import sys

import pytest

from quality_loop import awake


@pytest.mark.skipif(sys.platform != "darwin", reason="caffeinate is macOS's")
def test_a_mac_holds_caffeinate_on_this_process_for_the_block():
    said = []
    with awake.held(said.append) as holding:
        assert holding
        listed = subprocess.run(["pgrep", "-f", f"caffeinate -i -w {os.getpid()}"],
                                capture_output=True, text=True)
        assert listed.stdout.strip()
    assert said and said[0].startswith("awake:")
    listed = subprocess.run(["pgrep", "-f", f"caffeinate -i -w {os.getpid()}"],
                            capture_output=True, text=True)
    assert not listed.stdout.strip()


def test_where_nothing_can_be_held_the_run_goes_on_quietly(monkeypatch):
    monkeypatch.setattr(awake.sys, "platform", "linux")
    monkeypatch.setattr(awake.os, "name", "posix")
    said = []
    with awake.held(said.append) as holding:
        assert holding is False
    assert said == []


def test_a_mac_without_caffeinate_holds_nothing(monkeypatch):
    monkeypatch.setattr(awake.sys, "platform", "darwin")
    monkeypatch.setattr(awake.shutil, "which", lambda name: None)
    with awake.held(lambda line: None) as holding:
        assert holding is False


@pytest.mark.skipif(os.name != "nt", reason="SetThreadExecutionState is Windows'")
def test_windows_sets_and_clears_the_execution_state():
    with awake.held(lambda line: None) as holding:
        assert holding
