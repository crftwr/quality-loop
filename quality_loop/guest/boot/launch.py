"""A product's script in a Windows guest's desktop session, with no console.

Not run on the host. `quality_loop.guest.Guest.launch` has a scheduled task
run this with the image's pythonw.exe, the path of a JSON file as its one
argument. A batch file would do the same with less code, but cmd.exe opens a
console - on Windows 11 a Windows Terminal window - on the desktop the room
looks at, and an app that hands the foreground back would hand it to that.

What the batch file did is done here instead, from the JSON: the environment,
the search path in front of the interpreter's own, the working directory, and
stdout and stderr into the log. Then the script runs as __main__.
"""

import json
import os
import runpy
import site
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    settings = json.load(f)

# pythonw has no stdout or stderr: the log is both.
log = open(settings["log"], "w", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log

os.environ.update(settings.get("environ") or {})
if site.USER_SITE in sys.path:
    sys.path.remove(site.USER_SITE)
sys.path[0:0] = settings.get("path") or []
if settings.get("cwd"):
    os.chdir(settings["cwd"])
sys.argv = [settings["script"], *settings.get("argv", [])]

runpy.run_path(settings["script"], run_name="__main__")
