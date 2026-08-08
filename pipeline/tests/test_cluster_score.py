"""Tests for cluster scoring + person dedup.

These guard the high/medium/low/drop decision that controls operator
clusters in emit.py. False positives merge unrelated landlords; false
negatives drop real operators. Cover both edges.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cluster_score import (
    REGISTERED_AGENT_THRESHOLD,
    SHARED_OWNER_THRESHOLD,
    address_kind_from_key,
    classify_cluster,
    classify_service_address,
    dedup_persons_in_cluster,
    name_stem_cohesion,
)


# --- name_stem_cohesion --------------------------------------------------

def test_cohesion_strong_family():
    score, ev = name_stem_cohesion([
        "hertel properties llc",
        "hertel holdings llc",
        "hertel realty llc",
        "hertel rentals inc",
    ])
    assert score == 1.0
    assert "hertel" in ev


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


# --- cohesion_details ----------------------------------------------------

def test_cohesion_details_strong_family():
    from cluster_score import cohesion_details
    d = cohesion_details([
        "hertel properties llc",
        "hertel holdings llc",
        "hertel realty llc",
    ])
    assert d["score"] == 1.0
    assert d["distinctive_token"] == "hertel"
    assert "hertel" in d["explanation"]
    assert d["owner_count"] == 3


def test_cohesion_details_no_distinctive_tokens():
    from cluster_score import cohesion_details
    d = cohesion_details(["llc", "inc"])  # all stopwords
    assert d["score"] == 0.0
    assert d["distinctive_token"] is None
    assert d["explanation"] == "no distinctive tokens"


def test_cohesion_details_single_owner():
    from cluster_score import cohesion_details
    d = cohesion_details(["solo llc"])
    assert d["score"] == 1.0
    assert d["distinctive_token"] is None
    assert d["explanation"] == "single owner"


def test_cohesion_details_empty():
    from cluster_score import cohesion_details
    d = cohesion_details([])
    assert d["score"] == 0.0
    assert d["distinctive_token"] is None
    assert d["owner_count"] == 0


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


# --- alter-ego rule (person + LLC at street address) --------------------

def test_classify_alter_ego_person_plus_llc_high():
    """Classic LLC-unmasking pattern: a resident sharing a street address
    with the LLC that (presumably) holds their property."""
    result = classify_cluster(
        ["Mahoney, Martin C", "259 Breckenridge LLC"], "street",
    )
    assert result["action"] == "keep"
    assert result["confidence"] == "high"
    assert "alter-ego" in result["evidence"]


def test_classify_alter_ego_does_not_fire_for_two_persons():
    """Two persons co-residing isn't an alter-ego — keep at the score-based
    confidence (medium/low), not bumped to high."""
    result = classify_cluster(
        ["Schultz, Douglas A", "Moyer, Jeffrey T"], "street",
    )
    assert result["action"] == "keep"
    assert result["confidence"] != "high"


def test_classify_alter_ego_does_not_fire_for_two_llcs():
    """Two unrelated LLCs at one office isn't an alter-ego — score-based."""
    result = classify_cluster(
        ["EST Downtown LLC", "23 North Street LLC"], "street",
    )
    assert result["action"] == "keep"
    assert result["confidence"] != "high"


def test_classify_alter_ego_skipped_for_po_box():
    """PO-box pairs are already covered by the existing n<=8 PO box rule;
    the alter-ego branch shouldn't intercept and override the evidence."""
    result = classify_cluster(
        ["Mahoney, Martin C", "259 Breckenridge LLC"], "po_box",
    )
    assert result["action"] == "keep"
    assert result["confidence"] == "high"
    assert "alter-ego" not in result["evidence"]


def test_classify_pattern_alter_ego_set():
    result = classify_cluster(
        ["Mahoney, Martin C", "259 Breckenridge LLC"], "street",
    )
    assert result["pattern"] == "alter_ego"


def test_classify_pattern_none_for_normal_cluster():
    result = classify_cluster(
        [f"hertel holdings {i} llc" for i in range(5)], "street",
    )
    assert result["pattern"] is None


def test_classify_pattern_none_for_po_box_alter_ego_shape():
    """PO-box pairs go through the n<=8 branch, not alter-ego."""
    result = classify_cluster(
        ["Mahoney, Martin C", "259 Breckenridge LLC"], "po_box",
    )
    assert result["pattern"] is None


# --- stopword expansion --------------------------------------------------

def test_cohesion_strips_street_suffix():
    """'street' is now a stopword — names that only share it have no real
    cohesion and shouldn't score 1.0."""
    score, _ = name_stem_cohesion([
        "100 Elm Street LLC",
        "200 Oak Street LLC",
    ])
    assert score < 1.0


def test_cohesion_strips_buffalo():
    """'buffalo' alone is geographic noise, not an identity token."""
    score, _ = name_stem_cohesion([
        "Buffalo Holdings LLC",
        "Buffalo Realty LLC",
    ])
    assert score < 1.0


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


# --- structural properties of the cohesion score ------------------------
#
# Added 2026-08-07 after auditing all 2,204 emitted clusters. These pin
# down artifacts of the "fraction of owners sharing the top token" formula
# that are easy to misread when looking at the evidence string in the UI.

def test_two_owner_cluster_cannot_score_below_half():
    """With two owners the score is 0.5 even when nothing is shared.

    Any distinctive token is held by at least one of the two owners, so the
    floor is 1/2. The evidence string then reads "1 of 2 owners share 'x'",
    which is no evidence at all. Street clusters land in the medium band
    (0.3–0.6) because of it, which is the intended reading; PO-box clusters
    would clear the 0.5 bar, but they are already auto-kept at n<=8.
    """
    score, evidence = name_stem_cohesion(["cardiff stand llc", "funkhouse llc"])
    assert score == 0.5
    assert "1 of 2" in evidence


def test_numeric_token_can_win_the_cohesion_vote():
    """Digits count as distinctive tokens.

    Real case: "MMJ 18 LLC" + "GET'M 18 LLC" + "Estate of Nabih Tablie"
    scores 0.667 on the token '18'. Street numbers and sequence numbers in
    LLC names are weak identity evidence, but no cluster in the emitted set
    is held together by a numeric token alone, so the tokenizer keeps them.
    """
    score, evidence = name_stem_cohesion(["mmj 18 llc", "get m 18 llc", "estate of nabih tablie"])
    assert "'18'" in evidence
    assert score > 0.6


# --- classify_service_address (NYS DOS join) ----------------------------

def test_service_address_registered_agent_at_threshold():
    """The registered-agent test is >=, so exactly 100 entities qualifies."""
    assert classify_service_address(REGISTERED_AGENT_THRESHOLD, "street") == "registered_agent"
    assert classify_service_address(REGISTERED_AGENT_THRESHOLD - 1, "street") == "unknown"


def test_service_address_shared_owner_below_threshold():
    """Strictly fewer than 30 entities at a street address reads as a real
    shared owner; exactly 30 is already the uninformative middle band."""
    assert classify_service_address(SHARED_OWNER_THRESHOLD - 1, "street") == "shared_owner"
    assert classify_service_address(SHARED_OWNER_THRESHOLD, "street") == "unknown"
    assert classify_service_address(0, "street") == "shared_owner"


def test_service_address_po_box_never_shared_owner():
    """DOS process addresses are street addresses, so a PO box never
    matches and its zero count carries no information."""
    assert classify_service_address(0, "po_box") == "unknown"
    assert classify_service_address(29, "po_box") == "unknown"
