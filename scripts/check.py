#!/usr/bin/env python3
"""Local release checks; pass Python executable paths to test a version matrix."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(command):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    for interpreter in sys.argv[1:] or [sys.executable]:
        run([interpreter, "--version"])
        run([interpreter, "-m", "unittest", "discover", "-s", "tests", "-v"])
    node = shutil.which("node")
    if node:
        for source in ("static/core.js", "static/board.js", "static/hub.js", "static/network.js"):
            run([node, "--check", source])
        run([node, "tests/test_frontend.cjs"])
    else:
        print("Frontend checks NOT RUN: install Node.js for release validation.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
