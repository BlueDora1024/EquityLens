"""Deprecated command-line compatibility entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from stock_toolbox.cli import main as _toolbox_main


def main(argv: Sequence[str] | None = None) -> int:
    print(
        "rs-radar-cli is deprecated; use stock-toolbox instead.",
        file=sys.stderr,
    )
    return _toolbox_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
