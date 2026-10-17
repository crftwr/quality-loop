"""The operator agent's command line: ``python -m quality_loop screen ...``.

    python -m quality_loop screen list
    python -m quality_loop screen open approval-queue
    python -m quality_loop screen close approval-queue-1

Everything it takes is a name from the manifest the runner wrote. Answers are
JSON on stdout, errors one line on stderr with exit status 1.
"""

from __future__ import annotations

import argparse
import json
import sys

from quality_loop import screens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality-loop")
    commands = parser.add_subparsers(dest="command", required=True)
    screen = commands.add_parser("screen", help="put up or take down a declared screen")
    actions = screen.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="the screens the adapter declares")
    opening = actions.add_parser("open", help="open one, and wait for its window")
    opening.add_argument("name")
    closing = actions.add_parser("close", help="close one that `open` recorded")
    closing.add_argument("id")
    args = parser.parse_args(argv)

    try:
        if args.action == "list":
            answer = {name: {"kind": e["kind"], "title": e["title"]}
                      for name, e in screens.names().items()}
        elif args.action == "open":
            answer = screens.open_screen(args.name)
        else:
            answer = screens.close_screen(args.id)
    except screens.ScreenError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(answer, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
