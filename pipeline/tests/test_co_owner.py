"""Tests for co-owner parsing and link-noise suppression.

The co_owner module turns raw ADD_OWNER strings into stable keys so the
same human appearing under slightly different spellings on different
parcels collapses to one identity, and decides which co-owners are too
common to use as a cross-cluster link signal.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from co_owner import parse_co_owner, MAX_OPERATORS_PER_CO_OWNER, suppress_common_names


# --- parse_co_owner ------------------------------------------------------

def test_parse_comma_form():
    parsed = parse_co_owner("Smith, John A")
    assert parsed is not None
    assert parsed["key"] == frozenset({"SMITH", "JOHN"})
    assert parsed["display"] == "Smith, John A"


def test_parse_natural_order():
    parsed = parse_co_owner("John Smith")
    assert parsed is not None
    assert parsed["key"] == frozenset({"SMITH", "JOHN"})


def test_parse_normalizes_case_and_punctuation():
    """Same human in different spellings collapses to one key."""
    a = parse_co_owner("Smith, John A")
    b = parse_co_owner("SMITH, JOHN")
    c = parse_co_owner("John A Smith")
    assert a["key"] == b["key"] == c["key"]


def test_parse_skips_llc_like_values():
    """A business entity in ADD_OWNER is not a person — we don't key it."""
    assert parse_co_owner("Smith Holdings LLC") is None
    assert parse_co_owner("ACME PROPERTIES INC") is None


def test_parse_skips_single_token_garbage():
    """A one-token name (or empty string) can't be person-matched safely."""
    assert parse_co_owner("Kelley") is None
    assert parse_co_owner("") is None
    assert parse_co_owner("   ") is None


def test_parse_handles_hyphenated_lastname():
    """A hyphenated last name keeps as a single token."""
    parsed = parse_co_owner("Jackson-Molenda, Karen")
    assert parsed is not None
    # First+last set; first token of last_part = "Jackson-Molenda"
    # _person_signature splits on whitespace, so the hyphen stays.
    assert "KAREN" in parsed["key"]


# --- suppress_common_names ----------------------------------------------

def test_suppress_filters_common_names():
    """A co-owner key appearing in many distinct operators is suppressed
    from the cross-cluster link surface."""
    rare_key = frozenset({"DOE", "JANE"})
    common_key = frozenset({"SMITH", "JOHN"})
    index = {
        rare_key: ["op-a", "op-b"],
        common_key: [f"op-{i}" for i in range(MAX_OPERATORS_PER_CO_OWNER + 1)],
    }
    filtered = suppress_common_names(index)
    assert rare_key in filtered
    assert common_key not in filtered


def test_suppress_keeps_at_threshold():
    """At exactly MAX_OPERATORS_PER_CO_OWNER appearances, still considered link-worthy."""
    key = frozenset({"DOE", "JANE"})
    index = {key: [f"op-{i}" for i in range(MAX_OPERATORS_PER_CO_OWNER)]}
    filtered = suppress_common_names(index)
    assert key in filtered
