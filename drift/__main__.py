"""Entry point: python -m drift <check|snapshot|review|map|triage|auto|approve|migrate> [options]."""

from __future__ import annotations

import sys

USAGE = "usage: python -m drift {check,snapshot,review,map,triage,auto,approve,migrate} [options]   (add -h after the command for help)"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "check":
        from .check import main as run
    elif cmd == "snapshot":
        from .snapshot import main as run
    elif cmd == "review":
        from .review import main as run
    elif cmd == "map":
        from .mapgen import main as run
    elif cmd == "triage":
        from .triage import main as run
    elif cmd == "auto":
        from .auto import main as run
    elif cmd == "approve":
        from .approve import main as run
    elif cmd == "migrate":
        from .migrate import main as run
    else:
        print(USAGE, file=sys.stderr)
        return 2
    return run(rest)


if __name__ == "__main__":
    sys.exit(main())
