"""End-to-end pipeline entry point: fetch -> join -> emit.

Run with:  python run.py
Skip fetch (use cached raw/) with:  python run.py --no-fetch
"""

from __future__ import annotations

import argparse
import sys
import time

from emit import emit
from fetch import fetch_all
from join import join_all


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-fetch", action="store_true",
                   help="Skip raw downloads, use cached files in raw/")
    args = p.parse_args()

    t0 = time.time()
    if not args.no_fetch:
        print("=== FETCH ===", file=sys.stderr)
        fetch_all()
    else:
        print("=== FETCH (skipped) ===", file=sys.stderr)

    print("\n=== JOIN ===", file=sys.stderr)
    joined = join_all()

    print("\n=== EMIT ===", file=sys.stderr)
    emit(joined)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
