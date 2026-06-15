#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main():
    run(["scripts/fetch_market.py"])
    run(["scripts/build_dist.py"])


if __name__ == "__main__":
    main()
