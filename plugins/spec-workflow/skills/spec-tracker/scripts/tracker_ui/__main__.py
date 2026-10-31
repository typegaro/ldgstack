"""Run the dashboard: `python3 -m tracker_ui --root <project> [--port N] [--host H]`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .server import main


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="tracker_ui", description="Read-only spec-workflow dashboard")
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    parser.add_argument("--port", type=int, default=8733)
    parser.add_argument("--host", default="127.0.0.1")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse()
    try:
        main(Path(arguments.root).resolve(), arguments.port, arguments.host)
    except KeyboardInterrupt:
        sys.exit(0)
