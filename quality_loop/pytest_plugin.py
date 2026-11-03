"""Two marks for where a product's test may run, shared by Keyhac and XeFM.

Load it from the product's pytest configuration (``-p
quality_loop.pytest_plugin`` in ``addopts``); quality-loop does not register
it for every pytest that happens to have it installed.

- ``desktop`` - the test takes the foreground, opens, moves or resizes
  windows, sends real keys or mouse events, or changes the clipboard, the
  trash or the input source. It gets in the way of whatever the person at the
  machine is doing, and what they do gets in the way of it, so it is skipped
  unless pytest is given ``--desktop`` - which a run in a VM is. A test that
  only reads the OS stays unmarked.
- ``host_only`` - the test is of the product's host-side tooling: what stages
  a guest, what reviews a release. It needs the developer's checkout (git,
  the packages as installed there), and means nothing in a guest, where it
  is skipped (:data:`quality_loop.guest.IN_GUEST` is set there).
  ``--host-only`` runs these and nothing else, which is the host's share of a
  release's tests once the suite itself runs in the guests.
"""

from __future__ import annotations

import os

import pytest

from quality_loop.guest import IN_GUEST


def pytest_addoption(parser):
    group = parser.getgroup("quality-loop")
    group.addoption("--desktop", action="store_true",
                    help="also run the tests marked desktop, which take focus, move windows, "
                         "send input or change the clipboard - for a VM")
    group.addoption("--host-only", action="store_true",
                    help="run only the tests marked host_only (the host-side tooling)")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "desktop: touches the live desktop (focus, windows, input, clipboard, "
                   "trash); runs only with --desktop, which is for a VM")
    config.addinivalue_line(
        "markers", "host_only: tests the host-side tooling; skipped in a guest")


def pytest_collection_modifyitems(config, items):
    guest = os.environ.get(IN_GUEST)
    if config.getoption("--host-only"):
        if guest:
            raise pytest.UsageError(f"--host-only in a guest ({guest}): the host_only tests "
                                    "are the ones a guest skips")
        kept = [item for item in items if "host_only" in item.keywords]
        config.hook.pytest_deselected(items=[item for item in items if item not in kept])
        items[:] = kept
    desktop = config.getoption("--desktop")
    skip_desktop = pytest.mark.skip(reason="touches the live desktop: run it in a VM, "
                                           "or pass --desktop")
    skip_host = pytest.mark.skip(reason=f"tests the host's tooling; this is the guest {guest}")
    for item in items:
        if "desktop" in item.keywords and not desktop:
            item.add_marker(skip_desktop)
        if "host_only" in item.keywords and guest:
            item.add_marker(skip_host)
