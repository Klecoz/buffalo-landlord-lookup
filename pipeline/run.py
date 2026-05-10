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
from nys_dos import fetch_and_build_index as nys_dos_fetch_and_build_index


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-fetch", action="store_true",
                   help="Skip raw downloads, use cached files in raw/")
    p.add_argument("--force-dos-refresh", action="store_true",
                   help="Force re-fetch of NYS DOS active corporations even if cache is fresh")
    p.add_argument("--no-dos", action="store_true",
                   help="Skip NYS DOS service-address enrichment entirely")
    args = p.parse_args()

    t0 = time.time()
    if not args.no_fetch:
        print("=== FETCH ===", file=sys.stderr)
        fetch_all()
    else:
        print("=== FETCH (skipped) ===", file=sys.stderr)

    # NYS DOS active-corporations index. Cached for 30 days (DOS publishes
    # monthly), so daily runs hit the disk-cache only. The index is used
    # downstream in emit() to label clusters whose mailing address is a
    # registered-agent / filing-service pool rather than a real shared owner.
    agent_address_index: dict[str, int] | None = None
    dos_max_date: str | None = None
    if not args.no_dos:
        print("\n=== NYS DOS ENRICHMENT ===", file=sys.stderr)
        agent_address_index, dos_max_date = nys_dos_fetch_and_build_index(
            force_refresh=args.force_dos_refresh,
        )

    print("\n=== JOIN ===", file=sys.stderr)
    joined = join_all()

    print("\n=== EMIT ===", file=sys.stderr)
    emit(joined, agent_address_index=agent_address_index, dos_max_date=dos_max_date)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
