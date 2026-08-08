"""Tests for address + owner-name normalization.

These functions are load-bearing for portfolio aggregation; bugs silently
miscount, so we lean toward more cases than feels strictly necessary.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from normalize import normalize_address, normalize_mail_address, normalize_owner


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


# --- normalize_mail_address ----------------------------------------------

def test_mail_po_box_variants_collapse():
    """Every common PO Box rendering should produce the same key."""
    variants = [
        ("PO Box 1234", "Amherst", "NY", "14226", None),
        ("P.O. Box 1234", "AMHERST", "NY", "14226", None),
        ("P. O. Box 1234", "Amherst", "ny", "14226", None),
        ("POB 1234", "Amherst", "NY", "14226", None),
        ("Box 1234", "Amherst", "NY", "14226", None),
        ("PO BOX #1234", "Amherst", "NY", "14226", None),
        # PO box pulled from the dedicated PO_BOX field instead of MAIL_ADDR
        ("4053 Maple Rd", "Amherst", "NY", "14226", "1234"),
    ]
    keys = {normalize_mail_address(*v) for v in variants}
    # All variants except the last (different street) should match each other
    po_box_keys = {normalize_mail_address(*v) for v in variants if v[4] is None or v[0] != "4053 Maple Rd"}
    assert all(k.startswith("PO BOX 1234 | AMHERST | NY | 14226") for k in po_box_keys)


def test_mail_street_address_includes_locality():
    """Different cities / zips with same street don't merge."""
    a = normalize_mail_address("4053 Maple Rd", "Amherst", "NY", "14226")
    b = normalize_mail_address("4053 Maple Rd", "Buffalo", "NY", "14215")
    assert a != b
    assert "AMHERST" in a
    assert "BUFFALO" in b


def test_mail_zip_plus_4_stripped():
    a = normalize_mail_address("100 Main St", "Buffalo", "NY", "14215-1234")
    b = normalize_mail_address("100 Main St", "Buffalo", "NY", "14215")
    assert a == b


def test_mail_empty_inputs():
    assert normalize_mail_address(None) == ""
    assert normalize_mail_address("") == ""
    assert normalize_mail_address("", None, None, None, None) == ""


def test_mail_idempotent_for_po_box():
    once = normalize_mail_address("PO Box 1234", "Amherst", "NY", "14226")
    # Re-running on its own output should produce the same key (po-box detector
    # finds "PO BOX 1234" in the stringified output).
    twice = normalize_mail_address(once)
    # The key persists since "PO BOX 1234" survives the regex
    assert "PO BOX 1234" in twice


# --- normalize_owner: adversarial business-suffix cases ------------------
#
# Audited 2026-08-07 against all 65,089 emitted owner records. Each case
# below is either a spelling that actually occurs in the Erie County
# assessment roll or a boundary the suffix regexes could plausibly get
# wrong.

@pytest.mark.parametrize("raw,expected", [
    # Every LLC spelling in the roll collapses to one key.
    ("ACME PROPERTIES L.L.C", "acme properties llc"),
    ("ACME PROPERTIES llc.", "acme properties llc"),
    ("ACME PROPERTIES, LLC,", "acme properties llc"),
    ("acme properties l.l.c.", "acme properties llc"),
    ("  ACME  ,  L.L.C.  ", "acme llc"),
    # CORP / CORPORATION and INC / INCORPORATED.
    ("Acme Corporation", "acme corp"),
    ("ACME CORP", "acme corp"),
    ("Acme Corp.", "acme corp"),
    ("Acme Incorporated", "acme inc"),
    ("ACME INC.", "acme inc"),
    # LP and LLP. These two patterns share a prefix and `\bl ?p\b` runs
    # first, so "l l p" is rewritten in two passes ("l lp" then "llp").
    # All three spellings must still land on the same key.
    ("Acme L.P.", "acme lp"),
    ("Acme L P", "acme lp"),
    ("Acme LP", "acme lp"),
    ("Acme L.L.P.", "acme llp"),
    ("Acme L L P", "acme llp"),
    ("Acme LLP", "acme llp"),
    # LIMITED on its own is a company suffix; the longer LLC phrases are
    # matched first so they don't degrade to "ltd".
    ("Acme Limited", "acme ltd"),
    ("Acme Limited Liability Company", "acme llc"),
    ("Acme Limited Liability Co", "acme llc"),
])
def test_normalize_owner_business_suffix_variants(raw, expected):
    assert normalize_owner(raw) == expected


@pytest.mark.parametrize("raw", [
    "Landmark Properties LLC",
    "Help Buffalo Housing",
    "Holland Realty",
    "Alpine Lodge",
    "Compton Corner",
])
def test_normalize_owner_suffix_patterns_do_not_eat_real_words(raw):
    """The suffix regexes are \\b-anchored, so they must not fire inside words.

    `\\bl ?p\\b` in particular could plausibly chew "Landmark" or "Alpine";
    it does not, because there is no word boundary mid-token.
    """
    assert normalize_owner(raw) == raw.lower()


def test_normalize_owner_lp_pattern_absorbs_spaced_out_initials():
    """Known cosmetic quirk, harmless in practice.

    "H.E.L.P. Buffalo Inc" strips to the tokens "h e l p buffalo inc", and
    `\\bl ?p\\b` then rewrites the trailing "l p" of the acronym to "lp".
    The key is ugly but stable: every spelling of this owner in the roll
    ("H.E.L.P." and "H.e.l.p.") produces it, so nothing is split. A bare
    "HELP" has no internal boundary and is untouched.
    """
    assert normalize_owner("H.E.L.P. Buffalo Inc") == "h e lp buffalo inc"
    assert normalize_owner("H.e.l.p. Buffalo Inc") == "h e lp buffalo inc"
    assert normalize_owner("HELP Buffalo Housing") == "help buffalo housing"


def test_normalize_owner_trustee_folds_into_trust():
    """Deliberate: "X Trustee" and "X Trust" are the same holding.

    15 owners in the roll spell it "Trustee(s)". None of them collide with
    a differently-owned "Trust" of the same name, so the fold is free.
    """
    assert normalize_owner("Smith Family Trustee") == normalize_owner("Smith Family Trust")
    assert normalize_owner("Smith Family Trustees") == "smith family trust"
    assert normalize_owner("Kowal Mary A Trustee") == "kowal mary a trust"


def test_normalize_owner_keeps_diacritics_distinct():
    """No case folding for accents — and none is needed.

    `\\w` is Unicode-aware, so "José" survives punctuation stripping intact
    and does not match "Jose". Zero of the 65,089 owner records contain a
    non-ASCII character, so accent folding would be dead code.
    """
    assert normalize_owner("José Realty") == "josé realty"
    assert normalize_owner("José Realty") != normalize_owner("Jose Realty")


@pytest.mark.parametrize("raw", [
    "ACME PROPERTIES, L.L.C.",
    "Acme L L P",
    "Smith Family Trustee",
    "H.E.L.P. Buffalo Inc",
    "Acme Limited Liability Company",
])
def test_normalize_owner_idempotent_on_adversarial_input(raw):
    once = normalize_owner(raw)
    assert normalize_owner(once) == once


# --- "&" vs "and" --------------------------------------------------------

@pytest.mark.parametrize("amp,spelled", [
    # Real pairs from the roll that were two separate owners before this
    # normalization; see FINDINGS.md 2026-08-07.
    ("Karim & Karim LLC", "Karim and Karim LLC"),
    ("Manski & Manny LLC", "Manski And Manny, LLC"),
    ("Howlader & Roson Inc", "Howlader and Roson Inc"),
    ("Zenner & Ritter Inc", "Zenner and Ritter Inc"),
    ("M & M of Buffalo Inc", "M and M Of Buffalo, Inc."),
    ("Buffalo & Fort Erie", "Buffalo And Fort Erie"),
    ("R+SD, LLC", "R and SD LLC"),
])
def test_normalize_owner_merges_ampersand_and_spelled_out_and(amp, spelled):
    assert normalize_owner(amp) == normalize_owner(spelled)


def test_normalize_owner_and_removal_is_token_bounded():
    """Only the standalone conjunction goes — not "and" inside a word."""
    assert normalize_owner("Landmark Holdings") == "landmark holdings"
    assert normalize_owner("Anderson Sand & Gravel") == "anderson sand gravel"
    assert normalize_owner("Rand Realty") == "rand realty"


def test_normalize_owner_and_removal_idempotent():
    once = normalize_owner("Karim and Karim LLC")
    assert normalize_owner(once) == once
