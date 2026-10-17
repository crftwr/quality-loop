"""The toy's evidence tool: what the room's greeting says, against the style.

    python evidence.py greeting <room>
"""

import argparse
import json
import pathlib
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="evidence.py")
    commands = parser.add_subparsers(dest="command", required=True)
    greeting = commands.add_parser("greeting", help="the greeting the room left, "
                                   "and whether it is in the house style")
    greeting.add_argument("room")
    args = parser.parse_args(argv)
    evidence = pathlib.Path(args.room) / "evidence"
    style = (evidence / "before" / "style.txt").read_text().strip()
    after = evidence / "after" / "style.txt"
    made = evidence / "out" / "greeting.txt"
    text = made.read_text(encoding="utf-8") if made.exists() else None
    expected = "Hello, DANA!\n" if style == "uppercase" else "Hello, Dana!\n"
    print(json.dumps({
        "style": style,
        "style_unchanged": after.exists() and after.read_text().strip() == style,
        "greeting": text,
        "matches_style": text is not None and text.rstrip("\n") == expected.rstrip("\n"),
        "expected": expected,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
