"""Tests for address + owner-name normalization.

These functions are load-bearing for portfolio aggregation; bugs silently
miscount, so we lean toward more cases than feels strictly necessary.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from normalize import normalize_address, normalize_owner


# --- normalize_owner -----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("ACME PROPERTIES LLC", "acme properties llc"),
    ("Acme Properties, L.L.C.", "acme properties llc"),
    ("ACME PROPERTIES, L L C", "acme properties llc"),
    ("ACME PROPERTIES LIMITED LIABILITY COMPANY", "acme properties llc"),
    ("Acme Properties Limited Liability Co", "acme properties llc"),
    ("Smith Holdings INC.", "smith holdings inc"),
    ("Smith Holdings INCORPORATED", "smith holdings inc"),
    ("Big Realty Corporation", "big realty corp"),
    ("Big Realty CORP.", "big realty corp"),
    ("Hertel Avenue Company", "hertel avenue co"),
    ("Buffalo Municipal Housing Authority", "buffalo municipal housing authority"),
    ("JOHN SMITH", "john smith"),
    ("  John   Smith  ", "john smith"),
    ("Jones & Sons LLC", "jones sons llc"),
    ("OWNER OF RECORD", "owner of record"),
    ("Smith Family Trust", "smith family trust"),
    ("Smith Family Trustee", "smith family trust"),
    ("", ""),
    (None, ""),
    ("Hochul Holdings, L.P.", "hochul holdings lp"),
])
def test_normalize_owner(raw, expected):
    assert normalize_owner(raw) == expected


def test_normalize_owner_idempotent():
    """Normalizing twice should equal normalizing once."""
    once = normalize_owner("ACME Properties, L.L.C.")
    twice = normalize_owner(once)
    assert once == twice


# --- normalize_address ---------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("123 Main Street", "123 MAIN ST"),
    ("123 MAIN ST", "123 MAIN ST"),
    ("123 main street", "123 MAIN ST"),
    ("123 N Main Street", "123 N MAIN ST"),
    ("123 North Main Street", "123 N MAIN ST"),
    ("123 N. MAIN ST.", "123 N MAIN ST"),
    ("456 Elmwood Avenue", "456 ELMWOOD AVE"),
    ("789 Hertel Ave", "789 HERTEL AVE"),
    ("100 Niagara Falls Boulevard", "100 NIAGARA FALLS BLVD"),
    ("12 Delaware Park", "12 DELAWARE PARK"),
    ("123 Main St, Apt 4B", "123 MAIN ST"),
    ("123 Main St #4B", "123 MAIN ST"),
    ("", ""),
    (None, ""),
])
def test_normalize_address(raw, expected):
    assert normalize_address(raw) == expected


def test_normalize_address_idempotent():
    once = normalize_address("123 North Main Street, Apt 4B")
    twice = normalize_address(once)
    assert once == twice
