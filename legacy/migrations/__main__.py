"""Module entry point for ``python -m legacy.migrations``."""

from __future__ import annotations

import sys

from legacy.migrations import main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "migrate":
        del sys.argv[1]
    raise SystemExit(main())
