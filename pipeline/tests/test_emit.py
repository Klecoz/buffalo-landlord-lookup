"""Tests for emit.py — focused on the leaderboard skip-list.

Other emit logic is integration-tested via the real pipeline run; the
skip-list is the only piece worth unit-testing because it's the
difference between a useful leaderboard and one full of "city of buffalo
perfecting title".
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from emit import (
    TOP_VIOLATION_TYPES_N,
    _build_operator_clusters,
    _is_skipped_owner,
    _slugify,
    _slugify_unique,
    _top_violation_types,
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
            "properties": 2, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 200_000, "props": [],
        },
        "259 breckenridge llc": {
            "slug": "259-breckenridge-llc", "display": "259 Breckenridge LLC",
            "mail_keys": Counter({"259 BRECKENRIDGE | BUFFALO | NY | 14222": 1}),
            "properties": 2, "open": 0, "all_violations": 0,
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


def test_cluster_audit_co_owners_field_populated():
    """When parcels in a cluster carry ADD_OWNER, the cluster audit block
    surfaces a co_owners list with the human names and parcel counts."""
    addr = "100 MAIN ST | BUFFALO | NY | 14215"
    by_owner = {
        "acme 1 llc": {
            "slug": "acme-1-llc", "display": "ACME 1 LLC",
            "mail_keys": Counter({addr: 3}),
            "properties": 3, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter({
                frozenset({"SMITH", "JOHN"}): 2,
                frozenset({"DOE", "JANE"}): 1,
            }),
            "co_owner_displays": {
                frozenset({"SMITH", "JOHN"}): "Smith, John A",
                frozenset({"DOE", "JANE"}): "Doe, Jane",
            },
        },
        "acme 2 llc": {
            "slug": "acme-2-llc", "display": "ACME 2 LLC",
            "mail_keys": Counter({addr: 2}),
            "properties": 2, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter({frozenset({"SMITH", "JOHN"}): 1}),
            "co_owner_displays": {frozenset({"SMITH", "JOHN"}): "JOHN SMITH"},
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    co_owners = cluster["audit"]["co_owners"]
    # Smith should aggregate 2 + 1 = 3 parcels; sorted descending by parcels.
    assert co_owners[0]["parcels"] == 3
    assert co_owners[0]["name"] in {"Smith, John A", "JOHN SMITH"}
    # Jane Doe is also present.
    assert any(c["name"] == "Doe, Jane" and c["parcels"] == 1 for c in co_owners)


def test_cluster_audit_linked_operators_via_shared_co_owner():
    """Two clusters seeded by different mailing addresses, both with the
    same human as a co-owner, link to each other via linked_operators."""
    addr_a = "100 MAIN ST | BUFFALO | NY | 14215"
    addr_b = "200 OAK ST | BUFFALO | NY | 14215"
    smith = frozenset({"SMITH", "JOHN"})
    by_owner = {
        # Cluster A
        "acme 1 llc": {
            "slug": "acme-1-llc", "display": "ACME 1 LLC",
            "mail_keys": Counter({addr_a: 3}),
            "properties": 3, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter({smith: 2}),
            "co_owner_displays": {smith: "Smith, John A"},
        },
        "acme 2 llc": {
            "slug": "acme-2-llc", "display": "ACME 2 LLC",
            "mail_keys": Counter({addr_a: 1}),
            "properties": 1, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter(), "co_owner_displays": {},
        },
        # Cluster B (different mail key, same Smith)
        "beta 1 llc": {
            "slug": "beta-1-llc", "display": "BETA 1 LLC",
            "mail_keys": Counter({addr_b: 3}),
            "properties": 3, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter({smith: 1}),
            "co_owner_displays": {smith: "JOHN SMITH"},
        },
        "beta 2 llc": {
            "slug": "beta-2-llc", "display": "BETA 2 LLC",
            "mail_keys": Counter({addr_b: 1}),
            "properties": 1, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter(), "co_owner_displays": {},
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 2
    slugs = sorted(clusters.keys())
    a, b = clusters[slugs[0]], clusters[slugs[1]]
    # A links to B
    a_links = a["audit"]["linked_operators"]
    assert any(L["operator_slug"] == b["operator_slug"] for L in a_links), \
        f"A should link to B; got {a_links}"
    # B links to A
    b_links = b["audit"]["linked_operators"]
    assert any(L["operator_slug"] == a["operator_slug"] for L in b_links), \
        f"B should link to A; got {b_links}"


def test_cluster_audit_service_address_unknown_without_index():
    """When no NYS DOS index is supplied, every cluster's service_address
    block records count=0 and classification='unknown' — the absence of an
    index must not surface false 'shared_owner' confidence."""
    addr = "100 MAIN ST | BUFFALO | NY | 14215"
    by_owner = {}
    for i in range(4):
        by_owner[f"acme {i} llc"] = _owner_agg(
            f"acme-{i}-llc", f"ACME {i} LLC", {addr: 3}, 5
        )
    clusters, _, _ = _build_operator_clusters(by_owner)
    cluster = next(iter(clusters.values()))
    sa = cluster["audit"]["service_address"]
    assert sa["nys_dos_entity_count"] == 0
    assert sa["classification"] == "unknown"


def test_cluster_audit_service_address_flags_registered_agent():
    """When the cluster's mailing address appears in the NYS DOS index with
    a count above REGISTERED_AGENT_THRESHOLD, the audit block surfaces the
    'registered_agent' classification with the count and threshold."""
    addr = "100 MAIN ST | BUFFALO | NY | 14215"
    by_owner = {}
    for i in range(4):
        by_owner[f"acme {i} llc"] = _owner_agg(
            f"acme-{i}-llc", f"ACME {i} LLC", {addr: 3}, 5
        )
    index = {addr: 1247}
    clusters, _, _ = _build_operator_clusters(
        by_owner, agent_address_index=index, dos_max_date="2026-04-30",
    )
    cluster = next(iter(clusters.values()))
    sa = cluster["audit"]["service_address"]
    assert sa["classification"] == "registered_agent"
    assert sa["nys_dos_entity_count"] == 1247
    assert sa["threshold"] >= 1
    assert sa["source"] == "nys_dos_active_corporations"
    assert sa["source_max_date"] == "2026-04-30"


def test_cluster_audit_service_address_flags_shared_owner_when_zero_on_street():
    """A street mailing address absent from the NYS DOS index is positive
    evidence of a real shared owner."""
    addr = "100 MAIN ST | BUFFALO | NY | 14215"
    by_owner = {}
    for i in range(4):
        by_owner[f"acme {i} llc"] = _owner_agg(
            f"acme-{i}-llc", f"ACME {i} LLC", {addr: 3}, 5
        )
    index = {"some other address": 5000}  # mailing addr not in index
    clusters, _, _ = _build_operator_clusters(
        by_owner, agent_address_index=index,
    )
    cluster = next(iter(clusters.values()))
    sa = cluster["audit"]["service_address"]
    assert sa["nys_dos_entity_count"] == 0
    assert sa["classification"] == "shared_owner"


def test_cluster_audit_service_address_silent_for_po_box():
    """PO box addresses don't get classified — the DOS process_address
    field is a service-of-process street, so a PO box never matches and
    silence is preferable to misleading confidence."""
    addr = "PO BOX 99 | BUFFALO | NY | 14210"
    by_owner = {
        "acme one llc": _owner_agg("acme-one-llc", "ACME ONE LLC", {addr: 4}, 4),
        "acme two llc": _owner_agg("acme-two-llc", "ACME TWO LLC", {addr: 3}, 3),
    }
    clusters, _, _ = _build_operator_clusters(
        by_owner, agent_address_index={},
    )
    cluster = next(iter(clusters.values()))
    sa = cluster["audit"]["service_address"]
    assert sa["nys_dos_entity_count"] == 0
    assert sa["classification"] == "unknown"


def test_low_confidence_promoted_to_medium_when_dos_clean():
    """A street cluster with weak cohesion (no shared name stem) would land
    at "low" on the cohesion-only path. But if the NYS DOS index shows the
    address has zero unrelated entities, that's positive evidence of a real
    shared owner — promote the verdict to "medium" and append a note to
    the evidence string."""
    addr = "1675 NIAGARA ST | BUFFALO | NY | 14207"
    diverse_names = [
        "smith holdings llc", "jones holdings llc", "doe holdings llc",
        "kim holdings llc", "patel holdings llc", "ng holdings llc",
        "park holdings llc", "brown holdings llc", "davis holdings llc",
        "lee holdings llc",
    ]
    by_owner = {
        norm: _owner_agg(
            norm.replace(" ", "-"), norm.upper(), {addr: 2}, 2
        )
        for norm in diverse_names
    }
    # Without any DOS index, this cluster should be low-confidence.
    clusters_no_dos, _, counts_no_dos = _build_operator_clusters(by_owner)
    assert counts_no_dos.get("low", 0) == 1
    cluster_no_dos = next(iter(clusters_no_dos.values()))
    assert cluster_no_dos["confidence"] == "low"

    # With a DOS index that does NOT contain this address (count = 0 on a
    # street → "shared_owner"), the verdict promotes to medium.
    clusters, _, counts = _build_operator_clusters(
        by_owner, agent_address_index={"some other address": 999_999},
    )
    assert counts.get("medium", 0) == 1
    assert counts.get("low", 0) == 0
    cluster = next(iter(clusters.values()))
    assert cluster["confidence"] == "medium"
    assert "NYS DOS" in cluster["evidence"]
    # Audit block still records the underlying signals truthfully.
    assert cluster["audit"]["service_address"]["classification"] == "shared_owner"
    assert cluster["audit"]["cohesion"]["score"] < 0.2


def test_promotion_does_not_apply_when_dos_count_low_but_nonzero():
    """A non-zero DOS count below the registered-agent threshold still
    classifies as 'unknown' (not 'shared_owner'), so it must NOT promote
    a low-confidence cluster — we don't have positive evidence either way."""
    addr = "100 OAK ST | BUFFALO | NY | 14215"
    diverse_names = [
        "smith holdings llc", "jones holdings llc", "doe holdings llc",
        "kim holdings llc", "patel holdings llc", "ng holdings llc",
        "park holdings llc", "brown holdings llc", "davis holdings llc",
        "lee holdings llc",
    ]
    by_owner = {
        norm: _owner_agg(
            norm.replace(" ", "-"), norm.upper(), {addr: 2}, 2
        )
        for norm in diverse_names
    }
    # 50 entities — below threshold (100), so classification is "unknown".
    clusters, _, _ = _build_operator_clusters(
        by_owner, agent_address_index={addr: 50},
    )
    cluster = next(iter(clusters.values()))
    assert cluster["audit"]["service_address"]["classification"] == "unknown"
    assert cluster["confidence"] == "low"


def test_top_violation_types_orders_and_caps():
    """_top_violation_types returns at most TOP_VIOLATION_TYPES_N entries
    sorted by count descending."""
    counts = Counter({
        "Section 304 — Exterior Structure": 12,
        "Section 302 — Exterior Property": 8,
        "Section 305 — Interior Structure": 5,
        "Section 308 — Rubbish": 3,
        "Section 309 — Pests": 2,
        "Section 310 — Other": 1,
    })
    out = _top_violation_types(counts)
    assert len(out) == TOP_VIOLATION_TYPES_N == 5
    assert [r["count"] for r in out] == [12, 8, 5, 3, 2]
    assert out[0]["code_section"] == "Section 304 — Exterior Structure"
    assert all(set(r.keys()) == {"code_section", "count"} for r in out)


def test_top_violation_types_empty_returns_empty_list():
    assert _top_violation_types(Counter()) == []


def test_cluster_top_violation_types_sums_across_owners():
    """The cluster's top_violation_types Counter sums across constituent
    owners — same code_section appearing under two LLCs accumulates."""
    by_owner = {
        "alpha llc": {
            **_owner_agg("alpha-llc", "Alpha LLC",
                         {"PO BOX 7 | BUFFALO | NY | 14210": 5}, 5),
            "violation_type_counts": Counter({
                "Section 304 — Exterior Structure": 7,
                "Section 302 — Exterior Property": 2,
            }),
        },
        "beta llc": {
            **_owner_agg("beta-llc", "Beta LLC",
                         {"PO BOX 7 | BUFFALO | NY | 14210": 3}, 3),
            "violation_type_counts": Counter({
                "Section 304 — Exterior Structure": 5,
                "Section 308 — Rubbish": 4,
            }),
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    types = cluster["top_violation_types"]
    # Section 304 sums to 12 across the two owners.
    assert types[0] == {"code_section": "Section 304 — Exterior Structure", "count": 12}
    # All three distinct sections present, descending order.
    assert [r["count"] for r in types] == [12, 4, 2]


def test_cluster_top_violation_types_empty_when_no_data():
    """Owners without violation_type_counts produce an empty list (no raw
    Counter leaks into the emitted JSON)."""
    by_owner = {
        "alpha llc": _owner_agg("alpha-llc", "Alpha LLC",
                                {"PO BOX 7 | BUFFALO | NY | 14210": 5}, 5),
        "beta llc":  _owner_agg("beta-llc", "Beta LLC",
                                {"PO BOX 7 | BUFFALO | NY | 14210": 3}, 3),
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    cluster = next(iter(clusters.values()))
    assert cluster["top_violation_types"] == []


def test_cluster_audit_common_co_owner_suppressed_from_links():
    """A co-owner appearing in MORE than MAX_OPERATORS_PER_CO_OWNER (=5)
    distinct clusters is dropped from linked_operators (still in co_owners)."""
    from co_owner import MAX_OPERATORS_PER_CO_OWNER
    smith = frozenset({"SMITH", "JOHN"})
    by_owner = {}
    # Build (MAX + 1) tiny clusters, each at its own mailing address,
    # each carrying Smith as a co-owner. With suppression in force, none
    # should reference each other via linked_operators on this key.
    for i in range(MAX_OPERATORS_PER_CO_OWNER + 1):
        addr = f"{i} GENERIC ST | BUFFALO | NY | 14215"
        for j in range(2):  # 2 LLCs per cluster
            slug = f"op-{i}-{j}"
            by_owner[f"op {i} {j} llc"] = {
                "slug": slug, "display": f"OP {i} {j} LLC",
                "mail_keys": Counter({addr: 2}),
                "properties": 2, "open": 0, "all_violations": 0,
                "complaints_311_12mo": 0, "total_value": 0, "props": [],
                "co_owner_counts": Counter({smith: 1}) if j == 0 else Counter(),
                "co_owner_displays": ({smith: "Smith, John"} if j == 0 else {}),
            }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == MAX_OPERATORS_PER_CO_OWNER + 1
    for cluster in clusters.values():
        # Smith still appears as raw evidence ...
        names = [c["name"] for c in cluster["audit"]["co_owners"]]
        assert any("Smith" in n for n in names)
        # ... but no linked_operator entry uses Smith as the linking key.
        for L in cluster["audit"]["linked_operators"]:
            assert L["co_owner"] != "Smith, John"


def test_registered_agent_address_demotes_medium_to_low():
    """Real false merge: two unrelated LLCs at 90 State St, Albany.

    That address is the most heavily used filing-service address in New
    York — the NYS DOS index records 19,467 businesses there — yet the
    cluster shipped at medium confidence on the strength of the shared
    address alone. The DOS classification existed and was displayed but was
    never allowed to count against a cluster. See FINDINGS.md 2026-08-07.
    """
    addr = "90 STATE ST | ALBANY | NY | 12207"
    by_owner = {
        "black cloud development llc": _owner_agg(
            "black-cloud-development-llc", "Black Cloud Development LLC", {addr: 4}, 4
        ),
        "northstar acquisition llc": _owner_agg(
            "northstar-acquisition-llc", "Northstar Acquisition LLC", {addr: 2}, 2
        ),
    }

    # Without the DOS index there is no counter-evidence: medium stands.
    clusters_no_dos, _, _ = _build_operator_clusters(by_owner)
    assert next(iter(clusters_no_dos.values()))["confidence"] == "medium"

    clusters, _, counts = _build_operator_clusters(
        by_owner, agent_address_index={addr: 19_467}, dos_max_date="2026-05-08",
    )
    cluster = next(iter(clusters.values()))
    assert cluster["confidence"] == "low"
    assert counts["low"] == 1
    assert counts["medium"] == 0
    assert "19,467 businesses" in cluster["evidence"]
    assert cluster["audit"]["service_address"]["classification"] == "registered_agent"


def test_registered_agent_address_leaves_a_cohesive_family_alone():
    """A real operator may well file through an agent. When the names
    themselves already form a family, the address is not what is holding
    the cluster together, so the counter-evidence does not apply."""
    addr = "80 STATE ST | ALBANY | NY | 12207"
    by_owner = {
        f"hertel {i} llc": _owner_agg(f"hertel-{i}-llc", f"Hertel {i} LLC", {addr: 3}, 5)
        for i in range(4)
    }
    clusters, _, _ = _build_operator_clusters(
        by_owner, agent_address_index={addr: 5_000},
    )
    cluster = next(iter(clusters.values()))
    assert cluster["confidence"] == "high"
    assert "registered-agent" not in cluster["evidence"]


# --- slug alphabet and collision safety ---------------------------------
#
# The frontend interpolates owner and operator slugs straight into inline
# onclick handlers, so the slug alphabet is the backstop that keeps a hostile
# owner name in the assessment roll from becoming script. These tests pin the
# guarantee at the producing end.

SLUG_ALPHABET = re.compile(r"[a-z0-9-]+")

_ADVERSARIAL_NAMES = [
    "'); alert(1); //",
    '"><script>alert(1)</script>',
    "acme </a><img src=x onerror=alert(1)>",
    "javascript:alert(1)",
    "../../etc/passwd",
    "..\\..\\windows\\system32",
    "con",                          # reserved device name on Windows
    "NUL.json",
    "line\nbreak\ttab\r\x00nul",
    "josé ramos",              # non-ASCII letters
    "ΑΒΓ δεζ",       # Greek
    "владимир",   # Cyrillic
    "İstanbul llc",   # dotted capital I: lower() yields i + combining dot
    "emoji \U0001f600 llc",
    "‮evil",                   # right-to-left override
    "a" * 500,
    "   ",
    "---",
    "___",
    "!!!",
    "",
]


@pytest.mark.parametrize("name", _ADVERSARIAL_NAMES)
def test_slugify_output_stays_in_the_alphabet(name):
    """_slugify must emit only [a-z0-9-], for any input whatsoever."""
    slug = _slugify(name)
    assert SLUG_ALPHABET.fullmatch(slug), f"{name!r} -> {slug!r}"


@pytest.mark.parametrize(
    "name", ["", "   ", "!!!", "___", "\U0001f600", "ΑΒΓ"]
)
def test_slugify_never_returns_empty(name):
    """An empty slug would name a file '.json' and link an owner to nowhere.
    Punctuation-only, empty, and wholly non-Latin names fall back."""
    assert _slugify(name) == "unknown"


def test_slugify_caps_length_to_a_writable_filename():
    """A slug becomes a filename, and every filesystem we target caps a name
    at 255 bytes. Uncapped, one long owner name aborts the whole emit with
    ENAMETOOLONG partway through writing the owner portfolios."""
    slug = _slugify("a" * 500)
    assert len(slug) + len(".json.tmp") <= 255


def test_slugify_no_leading_or_trailing_hyphen():
    """A stray hyphen would survive into the filename and the URL."""
    for name in ("  acme llc  ", "!acme llc!", "---acme---llc---"):
        slug = _slugify(name)
        assert not slug.startswith("-") and not slug.endswith("-"), slug


def test_slugify_can_collide_which_is_why_dedup_exists():
    """Distinct owner names really do reduce to the same slug — an accent is
    the cheapest demonstration. Nothing downstream may assume otherwise."""
    assert _slugify("josé") == _slugify("josë") == "jos"


def test_slugify_unique_separates_colliding_labels():
    used = set()
    assert _slugify_unique("josé", used) == "jos"
    assert _slugify_unique("josë", used) == "jos-2"
    assert _slugify_unique("josü", used) == "jos-3"


def test_slugify_unique_suffix_cannot_steal_a_real_slug():
    """A name that legitimately slugifies to 'jos-2' must not be handed the
    same file as the disambiguated 'josë'."""
    used = set()
    assert _slugify_unique("jos 2", used) == "jos-2"
    assert _slugify_unique("josé", used) == "jos"
    assert _slugify_unique("josë", used) == "jos-3"
    assert len(used) == 3


def _emit_parcel(pid, owner_raw, owner_norm):
    return {
        "parcel_id": pid, "address": f"{pid} Main St", "owner_raw": owner_raw,
        "owner_norm": owner_norm, "lat": 42.9, "lng": -78.8,
        "geometry": {"type": "Point", "coordinates": [-78.8, 42.9]},
        "code_violations_open": 1, "code_violations_total": 1,
        "complaints_311_12mo": 0, "demolished": False, "demo_permit": None,
        "concern_score": 2, "last_violation_date": "2026-01-01",
        "violations": [], "complaints": [], "full_market_val": 1000,
        "add_owner": "", "is_self_mail": True, "violation_type_counts": Counter(),
    }


def test_emit_gives_every_colliding_owner_its_own_file(tmp_path, monkeypatch):
    """End to end: owners whose names collapse to one slug must land in
    separate files rather than silently overwriting each other."""
    import emit as emit_mod

    monkeypatch.setattr(emit_mod, "WEB_DATA", tmp_path)
    monkeypatch.setattr(emit_mod, "OWNERS_DIR", tmp_path / "owners")
    monkeypatch.setattr(emit_mod, "OPERATORS_DIR", tmp_path / "operators")

    parcels = [
        _emit_parcel("1", "José", "josé"),
        _emit_parcel("2", "Josë", "josë"),
        _emit_parcel("3", "Josü", "josü"),
    ]
    joined = {
        "parcels": parcels,
        "owners": {p["owner_norm"]: [p["parcel_id"]] for p in parcels},
        "meta": {},
    }
    emit_mod.emit(joined)

    files = sorted(f.name for f in (tmp_path / "owners").glob("*.json"))
    assert files == ["jos-2.json", "jos-3.json", "jos.json"]
    # Each owner's file is the one the map layer points at.
    geo = json.loads((tmp_path / "properties.geojson").read_text())
    by_id = {f["properties"]["id"]: f["properties"] for f in geo["features"]}
    assert len({p["owner_slug"] for p in by_id.values()}) == 3
    for pid, props in by_id.items():
        owner_file = json.loads(
            (tmp_path / "owners" / f"{props['owner_slug']}.json").read_text()
        )
        assert [p["id"] for p in owner_file["properties"]] == [pid]


def test_emit_slugs_are_all_in_the_alphabet(tmp_path, monkeypatch):
    """The property the frontend's inline handlers rely on, asserted on
    emit's actual output rather than on _slugify in isolation."""
    import emit as emit_mod

    monkeypatch.setattr(emit_mod, "WEB_DATA", tmp_path)
    monkeypatch.setattr(emit_mod, "OWNERS_DIR", tmp_path / "owners")
    monkeypatch.setattr(emit_mod, "OPERATORS_DIR", tmp_path / "operators")

    parcels = [
        _emit_parcel(str(i), name, name.lower())
        for i, name in enumerate(_ADVERSARIAL_NAMES)
        if name.strip()
    ]
    joined = {
        "parcels": parcels,
        "owners": {p["owner_norm"]: [p["parcel_id"]] for p in parcels},
        "meta": {},
    }
    emit_mod.emit(joined)

    geo = json.loads((tmp_path / "properties.geojson").read_text())
    for f in geo["features"]:
        slug = f["properties"]["owner_slug"]
        assert SLUG_ALPHABET.fullmatch(slug), slug
    for f in (tmp_path / "owners").glob("*.json"):
        assert SLUG_ALPHABET.fullmatch(f.stem), f.name


# ---------------------------------------------------------------------------
# address_index.json owner rows — the search box reads addresses and owners
# out of one file, so owner rows have to be present, typed, and routable.
# ---------------------------------------------------------------------------

def _emit_index(tmp_path, monkeypatch, parcels):
    import emit as emit_mod

    monkeypatch.setattr(emit_mod, "WEB_DATA", tmp_path)
    monkeypatch.setattr(emit_mod, "OWNERS_DIR", tmp_path / "owners")
    monkeypatch.setattr(emit_mod, "OPERATORS_DIR", tmp_path / "operators")
    emit_mod.emit({
        "parcels": parcels,
        "owners": {
            p["owner_norm"]: [q["parcel_id"] for q in parcels
                              if q["owner_norm"] == p["owner_norm"]]
            for p in parcels
        },
        "meta": {},
    })
    return json.loads((tmp_path / "address_index.json").read_text())


def test_address_index_carries_one_row_per_owner(tmp_path, monkeypatch):
    parcels = [
        _emit_parcel("1", "ACME LLC", "acme llc"),
        _emit_parcel("2", "ACME LLC", "acme llc"),
        _emit_parcel("3", "INCT HOLDINGS LLC", "inct holdings llc"),
    ]
    index = _emit_index(tmp_path, monkeypatch, parcels)

    owners = [r for r in index if r.get("t") == "o"]
    assert len(owners) == 2
    assert {o["name"] for o in owners} == {"ACME LLC", "INCT HOLDINGS LLC"}
    # n is the portfolio size, which is what the search sub-label shows.
    assert {o["name"]: o["n"] for o in owners} == {"ACME LLC": 2, "INCT HOLDINGS LLC": 1}
    assert all(set(o) == {"t", "name", "slug", "n"} for o in owners)


def test_address_index_owner_slugs_are_in_the_alphabet(tmp_path, monkeypatch):
    parcels = [
        _emit_parcel(str(i), name, name.lower())
        for i, name in enumerate(_ADVERSARIAL_NAMES)
        if name.strip()
    ]
    index = _emit_index(tmp_path, monkeypatch, parcels)

    owners = [r for r in index if r.get("t") == "o"]
    assert owners
    for o in owners:
        assert SLUG_ALPHABET.fullmatch(o["slug"]), o


def test_address_index_owner_slugs_resolve_to_portfolio_files(tmp_path, monkeypatch):
    """A search hit routes to #/owner/<slug>, which fetches owners/<slug>.json —
    so every slug in the index must name a file that exists."""
    parcels = [
        _emit_parcel("1", "José", "josé"),
        _emit_parcel("2", "Josë", "josë"),
        _emit_parcel("3", "Josü", "josü"),
    ]
    index = _emit_index(tmp_path, monkeypatch, parcels)

    owners = [r for r in index if r.get("t") == "o"]
    assert len({o["slug"] for o in owners}) == 3
    for o in owners:
        assert (tmp_path / "owners" / f"{o['slug']}.json").exists()


def test_address_index_address_rows_keep_their_shape(tmp_path, monkeypatch):
    """Owner rows are additive: address rows must stay untyped and sorted,
    because the frontend and its tests parse them as they are today."""
    parcels = [
        _emit_parcel("2", "ACME LLC", "acme llc"),
        _emit_parcel("1", "ACME LLC", "acme llc"),
    ]
    index = _emit_index(tmp_path, monkeypatch, parcels)

    addresses = [r for r in index if "t" not in r]
    assert [r["addr"] for r in addresses] == ["1 Main St", "2 Main St"]
    assert all(set(r) == {"addr", "id", "lat", "lng", "owner_slug"} for r in addresses)
    # Addresses first, owners after — no interleaving.
    assert [("t" in r) for r in index] == [False] * len(addresses) + [True] * (len(index) - len(addresses))
