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


def test_cohesion_details_tie_broken_alphabetically():
    """Tied tokens must not depend on set-iteration order.

    "Zoll, Sean" / "Zoll Sean P" give zoll and sean the same owner count and
    the same length, so only the tie-break separates them. It used to fall
    through to Counter insertion order — seeded by a per-process string hash —
    and the emitted evidence string changed between otherwise identical runs.
    """
    from cluster_score import cohesion_details
    d = cohesion_details(["Zoll, Sean", "Zoll Sean P"])
    assert d["distinctive_token"] == "sean"
    assert d["explanation"] == "2 of 2 owners share 'sean'"


def test_cohesion_details_tie_break_independent_of_input_order():
    from cluster_score import cohesion_details
    forward = cohesion_details(["Zoll, Sean", "Zoll Sean P"])
    reverse = cohesion_details(["Zoll Sean P", "Zoll, Sean"])
    assert forward["distinctive_token"] == reverse["distinctive_token"]


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


# --- organization names are not persons ---------------------------------
#
# _LLC_MARKER_RE only recognizes the abbreviated legal forms, so the long
# spellings ("Corporation", "Incorporated", "Company") and suffix-less
# organization names used to fall through to _person_signature. Real cases
# from the 2026-05-10 emit; see FINDINGS.md 2026-08-07.

def test_dedup_does_not_merge_two_organizations_by_first_and_last_token():
    """Real false merge: two different subsidized buildings became one owner.

    "St Clare Apartments" and "St Patrick Village Apartments" both reduce to
    {ST, APARTMENTS} under the old signature and were merged inside the
    yw-wny-housing-developmen cluster.
    """
    groups = dedup_persons_in_cluster([
        _owner("st-clare-apartments", "St Clare Apartments", 1),
        _owner("st-patrick-village-apartments", "St Patrick Village Apartments", 1),
    ])
    assert len(groups) == 2
    assert all(g["variants"] == [] for g in groups)


def test_dedup_does_not_merge_two_associates_partnerships():
    """"SRK 2020 Elmwood Associates" and "SRK 770 Elmwood Associates" are
    separate partnerships for separate buildings; both keyed {SRK,
    ASSOCIATES}."""
    groups = dedup_persons_in_cluster([
        _owner("srk-2020-elmwood-associates", "SRK 2020 Elmwood Associates", 1),
        _owner("srk-770-elmwood-associates", "SRK 770 Elmwood Associates", 1),
    ])
    assert len(groups) == 2


def test_classify_alter_ego_does_not_fire_for_long_form_corporation():
    """Real false promotion: a pair of company name variants read as
    person + LLC because "Corporation" is not in _LLC_MARKER_RE.

    "Acme Bearings Corporation" + "Acme Bearing Corp" is one company under
    two spellings, not a resident unmasking their LLC.
    """
    verdict = classify_cluster(
        ["Acme Bearings Corporation", "Acme Bearing Corp"], "street"
    )
    assert verdict["pattern"] is None
    # Still kept and still high — the names themselves are cohesive.
    assert verdict["confidence"] == "high"


def test_classify_alter_ego_survives_for_a_real_person():
    """The rule must keep firing on the signal the site exists to surface."""
    verdict = classify_cluster(["Aurum Apartments LLC", "Michaels Paul"], "street")
    assert verdict["pattern"] == "alter_ego"
    assert verdict["confidence"] == "high"


# --- trailing middle initials -------------------------------------------

def test_dedup_merges_last_name_first_form_with_trailing_initial():
    """Real false split: "Adkins, Cassandra" and "Adkins Cassandra C" are
    one person, shown as two owners of the adkins-cassandra cluster.

    Without a comma the old signature took the last token as the surname,
    found a one-character initial, and gave up entirely.
    """
    groups = dedup_persons_in_cluster([
        _owner("adkins-cassandra", "Adkins, Cassandra", 2),
        _owner("adkins-cassandra-c", "Adkins Cassandra C", 1),
    ])
    assert len(groups) == 1
    assert groups[0]["variants"] == ["Adkins Cassandra C"]
    assert groups[0]["property_count"] == 3


def test_dedup_merges_two_spaced_forms_differing_only_by_initial():
    """"Ashley Patricia E" / "Ashley Patricia", both without a comma."""
    groups = dedup_persons_in_cluster([
        _owner("ashley-patricia-e", "Ashley Patricia E", 2),
        _owner("ashley-patricia", "Ashley Patricia", 1),
    ])
    assert len(groups) == 1


def test_dedup_still_separates_different_surnames_with_initials():
    groups = dedup_persons_in_cluster([
        _owner("adkins-cassandra-c", "Adkins Cassandra C", 1),
        _owner("brown-cassandra-c", "Brown Cassandra C", 1),
    ])
    assert len(groups) == 2


def test_person_signature_keeps_two_token_names_intact():
    """The strip must never eat a name down below first + last."""
    groups = dedup_persons_in_cluster([
        _owner("li-x", "Li X", 1),
        _owner("li-wei", "Li Wei", 1),
    ])
    # "Li X" has a one-character token as its surname and stays unkeyable.
    assert len(groups) == 2


# --- PO-box auto-trust needs an actual business --------------------------

def test_classify_po_box_of_only_persons_is_not_auto_high():
    """Real false merge: three unrelated people at PO BOX 90417, Rochester,
    published as one high-confidence operator (al-wuhaib-najat-bader-e-h).

    A high-numbered out-of-area box holding only natural persons with no
    shared surname is a mail drop or an escrow servicer's lockbox, not a
    landlord. The cluster is still kept — they do share an address — but at
    medium, and the evidence no longer claims they are LLCs.
    """
    owners = ["Al-Wuhaib, Najat Bader E H", "Alhadah, Abdulrahman M A A S",
              "Allen Corrie Lee"]
    result = classify_cluster(owners, "po_box")
    assert result["action"] == "keep"
    assert result["confidence"] == "medium"
    assert "PO box" not in result["evidence"]


def test_classify_po_box_with_one_business_still_auto_high():
    """A person plus their LLCs at a small box is the normal, trusted shape."""
    owners = ["Brown Adrien W", "Days Park Properties LLC", "20 Wadsworth LLC"]
    result = classify_cluster(owners, "po_box")
    assert result["confidence"] == "high"
    assert result["evidence"] == "3 LLCs sharing one PO box"
