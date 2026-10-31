# Running the app in a VM

A run swaps the user's files, opens windows and sends keys. On the person's
own machine they have to stay present and keep their hands off. In a VM the
product's app runs on the guest's desktop instead, from a clean image every
run, and the host's desktop and the apps the person uses are left alone.

Only the app moves. The room, the operator, the evidence and the rooms
directory stay on the host, and the run reaches the app the way it reaches a
local one. `quality_loop.guest` is the shared part; the adapter keeps what is
its product's own: what it stages, how its app starts and stops, and how its
endpoint is reached.

## The image

One image per OS serves every kind of testing a product does in a VM -
automated tests, hand checks and quality-loop runs - kept as small as it can
be:

- the OS and its plumbing: SSH, a test user signed in to the desktop, a
  folder shared with the host;
- **a Python runtime**, named in the settings (`python`);
- on macOS, whatever has to hold a permission grant (Accessibility, Input
  Monitoring, Automation): a grant belongs to an app's signature, so code that
  needs it runs inside that app.

Nothing that is under test is in it. The product's working tree, and the
other packages its makers build, are staged every run. Third-party packages
are installed every run into a fresh venv in the guest
([`Guest.venv`](#the-venv)), so they always match the working tree's
requirements.

## Settings

Per machine, outside every repository - they name this machine's VMs, paths
and Keychain items, never a secret itself - in
`~/.config/quality-loop/guests.toml` (`QUALITY_LOOP_GUESTS` moves it), one
table per SSH host alias:

```toml
[qa-mac]
share = "~/.cache/qa-guest=/Volumes/My Shared Files/qa"
python = "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
tart = "qa-base"                     # cloned per run, deleted after
visible = true                       # show the clone in a window

[qa-win]
share = "~/mnt/qa-win=C:\\qa"
python = "C:\\Python314\\python.exe"
vmx = "~/Virtual Machines.localized/QA.vmwarevm/QA.vmx"
snapshot = "QA-2026-10-30"           # reverted to before the run
vm_password = "keychain:qa-win-vm"   # the VM's encryption password
smb = "//qa@192.168.54.128/qa"       # remounted on the share's host side
smb_password = "keychain:qa-win-smb"
```

- **`share`** is `<host side>=<guest side>`: the same folder as each sees it.
- The alias's address, user and key are in `~/.ssh/config`.
- **`keychain:<service>`** is read from the login Keychain when a run needs
  it.
- Without `tart` or `vmx`, the guest is used as it is, already running.

`Guest.from_environment("PRODUCT_QA_GUEST")` returns the guest an environment
variable names, or None for a local run.

## The machine

`guest.machine()` is a context manager for the run:

- **Tart**: clone the base, run it with the share as `--dir`, wait for SSH,
  and delete the clone afterwards.
- **VMware Fusion**: revert to the snapshot, start it headless, remount the
  SMB share, wait for the guest's clock, and stop it afterwards. A snapshot
  taken while the VM ran comes back running and signed in, in seconds.

Learnt on Fusion with a vTPM-encrypted Windows 11 VM: `vmrun` cannot
linked-clone it, nor snapshot it while it runs. Take a running-state snapshot
in the Fusion app, after `vmrun suspend` - a VM started headless does not show
in the app.

## The stage

`guest.stage()` makes a directory on the share, carrying what runs in the
guest on quality-loop's behalf (`<stage>/ql`). The adapter copies its own
files beside it. `guest.path(p)` turns a host path on the share into the
guest's.

## The venv

`guest.venv(stage, requirements)` makes a venv on the guest's own disk from
the image's Python, installs the requirements, and returns its interpreter as
the guest names it. The revert after the run throws it away. pip's download
cache is on the share (`<host side>/.pip-cache`), so the next run downloads
only what changed. List only third-party packages: what the product's makers
build is staged.

## Starting the app

- **Windows:** `guest.launch(stage, task, pythonw, script=..., log=...,
  environ=..., path=..., cwd=..., argv=...)` runs a script as `__main__` in
  the signed-in user's desktop session, from a scheduled task, with no
  console window: a window opened from SSH lands where nobody sees it.
  `guest.forget_task(task)` removes the task.
- **macOS:** start the app with `open` over SSH, which reaches the desktop
  session.

A port the app opens in the guest is the host's through `guest.forward(port)`;
`guest.reverse(port)` is the other way.

## Screens

The operator's screens go up in the guest when the adapter returns
`quality_loop.guest.screens` as its screen backend:

```python
from quality_loop.guest import screens as guest_screens

def screen_backend(self):
    return {"path": guest_screens.__file__,
            "settings": guest_screens.settings(self.guest, self.stage)}

def platform(self):
    return self.guest.platform
```

Each operation runs quality-loop's own OS backend in the guest. A page is
served on the host's 127.0.0.1 and reached from the guest through a reverse
tunnel on the same port; `quality_loop.guest.end_tunnels(stage)` ends them at
the run's end. A terminal screen's script is copied to the stage and run with
the image's Python (`terminal_python` to choose another).
