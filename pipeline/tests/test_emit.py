"""Tests for emit.py — focused on the leaderboard skip-list.

Other emit logic is integration-tested via the real pipeline run; the
skip-list is the only piece worth unit-testing because it's the
difference between a useful leaderboard and one full of "city of buffalo
perfecting title".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from emit import _is_skipped_owner


def test_skipped_substrings():
    skipped = [
        "city of buffalo perfecting title",
        "city of buffalo",
        "city buffalo perfecting",
        "city buffalo",
        "city of bflo",
        "city bflo holdings",
        "buffalo municipal housing authority",
        "buffalo public schools",
        "buffalo board of education",
        "state of new york",
        "state new york dept transportation",
        "county of erie",
        "erie county industrial development agency",
        "united states of america",
    ]
    for s in skipped:
        assert _is_skipped_owner(s), f"should be skipped: {s!r}"


def test_skipped_exact_placeholders():
    for s in ["owner of record", "unknown", ""]:
        assert _is_skipped_owner(s), f"should be skipped: {s!r}"


def test_kept_private_owners():
    kept = [
        "inct holdings llc",
        "jlt real estate llc",
        "smith family trust",
        "john smith",
        "84 group inc",
        "acme properties llc",
    ]
    for s in kept:
        assert not _is_skipped_owner(s), f"should NOT be skipped: {s!r}"
