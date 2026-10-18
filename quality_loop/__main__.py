"""``python -m quality_loop``: the same as the ``quality-loop`` command.

See `quality_loop.cli`. The operator's ``screen`` subcommand is one of them:
everything it takes is a name from the manifest the runner wrote.
"""

from quality_loop.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
