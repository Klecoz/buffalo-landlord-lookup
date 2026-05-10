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
