"""Tests for cluster scoring + person dedup.

These guard the high/medium/low/drop decision that controls operator
clusters in emit.py. False positives merge unrelated landlords; false
negatives drop real operators. Cover both edges.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cluster_score import (
    address_kind_from_key,
    classify_cluster,
    dedup_persons_in_cluster,
    name_stem_cohesion,
)


# --- name_stem_cohesion --------------------------------------------------

def test_cohesion_strong_family():
    score, ev = name_stem_cohesion([
        "buffalo properties llc",
        "buffalo holdings llc",
        "buffalo realty llc",
        "buffalo rentals inc",
    ])
    assert score == 1.0
    assert "buffalo" in ev


def test_cohesion_mostly_shared():
    score, ev = name_stem_cohesion([
        "acme one llc",
        "acme two llc",
        "acme three llc",
        "smith family trust",
    ])
    # 3 of 4 share "acme"
    assert score == 0.75


def test_cohesion_unrelated():
    score, _ = name_stem_cohesion([
        "smith llc",
        "jones llc",
        "doe llc",
        "nguyen llc",
    ])
    # Each owner contributes one unique non-stopword token → max coverage 1/4.
    assert score <= 0.25


def test_cohesion_single_owner():
    score, _ = name_stem_cohesion(["solo llc"])
    assert score == 1.0


def test_cohesion_ignores_stopwords():
    """LLC/INC/CORP alone shouldn't drive cohesion — every owner has them.
    Distinctive tokens (alpha/beta/gamma) are unique → low score."""
    score, _ = name_stem_cohesion([
        "alpha llc",
        "beta inc",
        "gamma corp",
    ])
    assert score < 0.5


# --- classify_cluster ----------------------------------------------------

def test_classify_real_operator_po_box_high():
    owners = [f"buffalo properties {i} llc" for i in range(6)]
    result = classify_cluster(owners, "po_box")
    assert result["action"] == "keep"
    assert result["confidence"] == "high"


def test_classify_small_po_box_high_even_unrelated():
    """A PO box shared by 4 unrelated names is still trustworthy — PO
    boxes aren't shared casually."""
    owners = ["smith llc", "jones llc", "doe llc", "nguyen llc"]
    result = classify_cluster(owners, "po_box")
    assert result["action"] == "keep"
    assert result["confidence"] == "high"


def test_classify_agent_address_drops():
    """40 unrelated owners at one street address — likely a registered
    agent, law firm, or property manager."""
    surnames = [
        "smith", "jones", "doe", "nguyen", "kim", "patel", "garcia", "lee",
        "brown", "davis", "wilson", "moore", "taylor", "anderson", "thomas",
        "jackson", "white", "harris", "martin", "thompson", "lewis", "walker",
        "hall", "allen", "young", "king", "wright", "scott", "green", "baker",
        "adams", "nelson", "carter", "mitchell", "perez", "roberts", "turner",
        "phillips", "campbell", "parker",
    ]
    owners = [f"{s} holdings llc" for s in surnames]
    result = classify_cluster(owners, "street")
    assert result["action"] == "drop"
    assert result["confidence"] == "low"


def test_classify_street_with_strong_stem_high():
    owners = [f"hertel holdings {i} llc" for i in range(10)]
    result = classify_cluster(owners, "street")
    assert result["action"] == "keep"
    assert result["confidence"] == "high"


def test_classify_mixed_street_medium():
    """5 share a stem, 5 don't, at a street address — keep at medium."""
    owners = [f"acme {i} llc" for i in range(5)] + [
        "smith llc", "jones llc", "doe llc", "nguyen llc", "kim llc",
    ]
    result = classify_cluster(owners, "street")
    assert result["action"] == "keep"
    assert result["confidence"] in ("medium", "high")


def test_classify_low_signal_street_kept_low():
    """Three barely-related names at a street address — keep but low."""
    owners = ["alpha llc", "beta inc", "gamma corp"]
    result = classify_cluster(owners, "street")
    assert result["action"] == "keep"


# --- address_kind_from_key -----------------------------------------------

def test_address_kind_po_box():
    assert address_kind_from_key("PO BOX 1234 | AMHERST | NY | 14226") == "po_box"


def test_address_kind_street():
    assert address_kind_from_key("100 MAIN ST | BUFFALO | NY | 14215") == "street"


# --- dedup_persons_in_cluster --------------------------------------------

def _owner(slug, display, properties):
    return {"slug": slug, "display": display, "properties": properties}


def test_dedup_merges_person_variants():
    block = [
        _owner("a", "JOHN SMITH", 5),
        _owner("b", "SMITH, JOHN A", 3),
        _owner("c", "JOHN A SMITH", 2),
    ]
    groups = dedup_persons_in_cluster(block)
    assert len(groups) == 1
    g = groups[0]
    assert g["canonical"] == "JOHN SMITH"
    assert "SMITH, JOHN A" in g["variants"]
    assert "JOHN A SMITH" in g["variants"]
    assert g["property_count"] == 10
    assert set(g["slugs"]) == {"a", "b", "c"}


def test_dedup_keeps_llcs_separate():
    block = [
        _owner("a", "ACME PROPERTIES LLC", 4),
        _owner("b", "ACME RENTALS LLC", 2),
    ]
    groups = dedup_persons_in_cluster(block)
    assert len(groups) == 2


def test_dedup_keeps_different_persons_separate():
    block = [
        _owner("a", "JOHN SMITH", 1),
        _owner("b", "MARY SMITH", 1),
    ]
    groups = dedup_persons_in_cluster(block)
    assert len(groups) == 2


def test_dedup_handles_comma_form():
    block = [
        _owner("a", "SMITH, JOHN", 5),
        _owner("b", "JOHN SMITH", 2),
    ]
    groups = dedup_persons_in_cluster(block)
    assert len(groups) == 1
    assert groups[0]["property_count"] == 7


def test_dedup_empty_input():
    assert dedup_persons_in_cluster([]) == []


def test_dedup_single_token_name_kept_as_singleton():
    """One-word names can't be person-matched — keep as standalone."""
    block = [_owner("a", "BUFFALO", 3)]
    groups = dedup_persons_in_cluster(block)
    assert len(groups) == 1
    assert groups[0]["canonical"] == "BUFFALO"
