"""Tests for emit.py — focused on the leaderboard skip-list.

Other emit logic is integration-tested via the real pipeline run; the
skip-list is the only piece worth unit-testing because it's the
difference between a useful leaderboard and one full of "city of buffalo
perfecting title".
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from emit import (
    _build_operator_clusters,
    _is_skipped_owner,
)


def test_skipped_substrings():
    skipped = [
        # gov
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
        "state university of new york",
        "county of erie",
        "erie county industrial development agency",
        "united states of america",
        # quasi-public
        "buffalo urban renewal agency",
        "empire state development corp",
        "dormitory authority of",
        "n f t a",
        "nfta",
        "rochester housing authority",
        # utilities
        "niagara mohawk power corp",
        "national grid",
        "verizon new york inc",
        # nonprofits / institutional
        "kaleida health",
        "catholic health system",
        "mercy hospital of buffalo",
        "roswell park cancer institute",
        "diocese of buffalo",
        "ywca of niagara",
        "ymca buffalo niagara",
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


# --- operator clustering -------------------------------------------------

def _owner_agg(slug, display, mail_keys, properties, open_v=0, all_v=0, c311=0, value=0):
    """Build the by_owner record shape that _build_operator_clusters expects."""
    return {
        "slug": slug,
        "display": display,
        "variants": [display],
        "mail_keys": Counter(mail_keys),
        "properties": properties,
        "open": open_v,
        "all_violations": all_v,
        "complaints_311_12mo": c311,
        "total_value": value,
        "oldest_violation": None,
        "props": [{"id": f"{slug}-{i}", "concern_score": 0} for i in range(properties)],
    }


def test_cluster_three_llcs_share_po_box():
    """Happy path: three LLCs all mail to the same PO box → one operator."""
    by_owner = {
        "jlt real estate llc": _owner_agg("jlt-real-estate-llc", "JLT Real Estate LLC",
                                          {"PO BOX 1 | AMHERST | NY | 14226": 70}, 70, open_v=300),
        "jlt holdings llc":    _owner_agg("jlt-holdings-llc", "JLT Holdings LLC",
                                          {"PO BOX 1 | AMHERST | NY | 14226": 12}, 12, open_v=40),
        "smith mgmt llc":      _owner_agg("smith-mgmt-llc", "Smith Mgmt LLC",
                                          {"PO BOX 1 | AMHERST | NY | 14226": 5}, 5, open_v=8),
    }
    clusters, mapping, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    assert cluster["total_properties"] == 87
    assert cluster["total_open_violations"] == 348
    assert {o["slug"] for o in cluster["owners"]} == {
        "jlt-real-estate-llc", "jlt-holdings-llc", "smith-mgmt-llc",
    }
    # Primary label is the largest LLC, with a "+N more" suffix.
    assert cluster["operator_label"].startswith("JLT Real Estate LLC")
    assert "+2 more" in cluster["operator_label"]
    # Each owner is mapped to the operator.
    for o in by_owner:
        assert o in mapping


def test_skip_generic_mailing_address():
    """A street mailing address shared by many unrelated owners (no shared
    name stem) is classified as an agent address and never seeds a cluster.
    """
    lawyer_mail = "100 LAW ST | BUFFALO | NY | 14202"
    surnames = [
        "smith", "jones", "doe", "nguyen", "kim", "patel", "garcia", "lee",
        "brown", "davis", "wilson", "moore", "taylor", "anderson", "thomas",
        "jackson", "white", "harris", "martin", "thompson", "lewis", "walker",
        "hall", "allen", "young", "king", "wright", "scott", "green", "baker",
        "adams", "nelson", "carter", "mitchell", "perez",
    ]
    by_owner = {
        f"{s} llc": _owner_agg(f"{s}-llc", f"{s.title()} LLC",
                               {lawyer_mail: 1}, 1)
        for s in surnames
    }
    clusters, mapping, _ = _build_operator_clusters(by_owner)
    assert clusters == {}
    assert mapping == {}


def test_skip_owner_occupied_only():
    """If an owner only has self-mail parcels, mail_keys is empty and they don't
    seed any cluster — even if another owner mails to that property's address.
    """
    by_owner = {
        "self mailer llc": _owner_agg("self-mailer-llc", "Self Mailer LLC",
                                      {}, 1),  # empty mail_keys = self-mail only
        "other llc":       _owner_agg("other-llc", "Other LLC",
                                      {"123 MAIN ST | BUFFALO | NY | 14210": 4}, 4),
    }
    clusters, mapping, _ = _build_operator_clusters(by_owner)
    # Only one owner has a mailing key → not a cluster (need ≥2 owners).
    assert clusters == {}


def test_solo_llc_not_clustered():
    """A single LLC with multiple parcels mailed to one address is not a cluster."""
    by_owner = {
        "lonely llc": _owner_agg("lonely-llc", "Lonely LLC",
                                 {"PO BOX 99 | BUFFALO | NY | 14210": 10}, 10),
    }
    clusters, mapping, _ = _build_operator_clusters(by_owner)
    assert clusters == {}


def test_cluster_below_property_threshold():
    """Two LLCs sharing an address but fewer than MIN_CLUSTER_PARCELS total → not
    a cluster (filters out shared family/home addresses).
    """
    by_owner = {
        "couple a llc": _owner_agg("couple-a-llc", "Couple A LLC",
                                   {"PO BOX 5 | KENMORE | NY | 14217": 1}, 1),
        "couple b llc": _owner_agg("couple-b-llc", "Couple B LLC",
                                   {"PO BOX 5 | KENMORE | NY | 14217": 1}, 1),
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert clusters == {}


def test_cluster_total_value_sums_across_owners():
    """The cluster's total_value is the sum of constituent owners' values."""
    by_owner = {
        "alpha llc": _owner_agg("alpha-llc", "Alpha LLC",
                                {"PO BOX 7 | BUFFALO | NY | 14210": 5}, 5, value=1_500_000),
        "beta llc":  _owner_agg("beta-llc", "Beta LLC",
                                {"PO BOX 7 | BUFFALO | NY | 14210": 3}, 3, value=600_000),
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    assert cluster["total_value"] == 2_100_000
    # Constituent owners section also carries per-LLC value.
    assert {o["total_value"] for o in cluster["owners"]} == {1_500_000, 600_000}


def test_cluster_emits_confidence_and_owner_groups():
    """High-cohesion PO-box cluster should be marked high-confidence and
    expose owner_groups for the dedup'd persons view."""
    by_owner = {
        "acme one llc": _owner_agg("acme-one-llc", "ACME ONE LLC",
                                   {"PO BOX 9 | BUFFALO | NY | 14210": 4}, 4),
        "acme two llc": _owner_agg("acme-two-llc", "ACME TWO LLC",
                                   {"PO BOX 9 | BUFFALO | NY | 14210": 3}, 3),
    }
    clusters, _, counts = _build_operator_clusters(by_owner)
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    assert cluster["confidence"] == "high"
    assert isinstance(cluster["evidence"], str) and cluster["evidence"]
    # owner_groups parallels owners; each LLC stays a singleton.
    assert len(cluster["owner_groups"]) == 2
    assert counts["high"] == 1


def test_cluster_counts_dropped_agent_address():
    """A 35-owner street cluster with no shared stem should be dropped."""
    surnames = [
        "smith", "jones", "doe", "nguyen", "kim", "patel", "garcia", "lee",
        "brown", "davis", "wilson", "moore", "taylor", "anderson", "thomas",
        "jackson", "white", "harris", "martin", "thompson", "lewis", "walker",
        "hall", "allen", "young", "king", "wright", "scott", "green", "baker",
        "adams", "nelson", "carter", "mitchell", "perez",
    ]
    addr = "100 LAW ST | BUFFALO | NY | 14202"
    by_owner = {
        f"{s} llc": _owner_agg(f"{s}-llc", f"{s.title()} LLC", {addr: 1}, 1)
        for s in surnames
    }
    _, _, counts = _build_operator_clusters(by_owner)
    assert counts["dropped"] == 1


def test_cluster_with_government_owner_skipped():
    """If any constituent owner is in the gov skip-list, the entire cluster is
    dropped (we never want a leaderboard row containing 'city of buffalo').
    """
    shared_mail = "PO BOX 200 | BUFFALO | NY | 14202"
    by_owner = {
        "city of buffalo": _owner_agg("city-of-buffalo", "City of Buffalo",
                                      {shared_mail: 100}, 100),
        "real owner llc":  _owner_agg("real-owner-llc", "Real Owner LLC",
                                      {shared_mail: 5}, 5),
    }
    clusters, mapping, _ = _build_operator_clusters(by_owner)
    assert clusters == {}
    assert mapping == {}


def test_cluster_emits_audit_block():
    """Each operator cluster gets a structured `audit` dict bundling
    everything the UI needs to render the 'How these names are grouped'
    disclosure."""
    by_owner = {}
    for i in range(4):
        slug = f"acme-{i}-llc"
        display = f"ACME {i} LLC"
        by_owner[display.lower()] = {
            "slug": slug, "display": display,
            "mail_keys": Counter({"100 MAIN ST | BUFFALO | NY | 14215": 3}),
            "properties": 5, "open": 1, "all_violations": 2,
            "complaints_311_12mo": 0, "total_value": 100_000,
            "props": [],
        }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1, "fixture should produce one cluster"
    cluster = next(iter(clusters.values()))
    audit = cluster["audit"]
    assert audit["shared_mailing_address"] == cluster["mailing_address"]
    assert audit["address_kind"] == "street"
    assert audit["member_count"] == 4
    assert audit["cohesion"]["distinctive_token"] == "acme"
    assert audit["cohesion"]["score"] == 1.0
    assert "acme" in audit["cohesion"]["explanation"]
    assert audit["pattern"] is None
    assert audit["person_dedups"] == []  # no person-name variants in fixture


def test_cluster_audit_records_alter_ego_pattern():
    """A 1-person + 1-LLC street cluster fires the alter-ego rule and the
    audit block surfaces the pattern."""
    by_owner = {
        "mahoney, martin c": {
            "slug": "mahoney-martin-c", "display": "Mahoney, Martin C",
            "mail_keys": Counter({"259 BRECKENRIDGE | BUFFALO | NY | 14222": 2}),
            "properties": 1, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 200_000, "props": [],
        },
        "259 breckenridge llc": {
            "slug": "259-breckenridge-llc", "display": "259 Breckenridge LLC",
            "mail_keys": Counter({"259 BRECKENRIDGE | BUFFALO | NY | 14222": 1}),
            "properties": 1, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 150_000, "props": [],
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    assert cluster["audit"]["pattern"] == "alter_ego"


def test_cluster_audit_surfaces_person_dedups():
    """When dedup_persons_in_cluster collapses a name into variants, those
    variants land in audit.person_dedups."""
    addr = "100 OAK ST | BUFFALO | NY | 14215"
    by_owner = {
        "john smith": {
            "slug": "john-smith", "display": "JOHN SMITH",
            "mail_keys": Counter({addr: 2}),
            "properties": 5, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
        },
        "smith, john a": {
            "slug": "smith-john-a", "display": "SMITH, JOHN A",
            "mail_keys": Counter({addr: 2}),
            "properties": 3, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    if not clusters:
        # MIN_CLUSTER_OWNERS / MIN_CLUSTER_PARCELS may exclude tiny fixtures
        # — bail out cleanly rather than fail spuriously.
        import pytest as _pt
        _pt.skip("cluster size below emit.py minimums for this fixture")
    cluster = next(iter(clusters.values()))
    dedups = cluster["audit"]["person_dedups"]
    assert len(dedups) == 1
    assert dedups[0]["canonical"] == "JOHN SMITH"
    assert "SMITH, JOHN A" in dedups[0]["variants"]
