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
    GENERIC_ADDRESS_OWNER_CAP,
)


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


# --- operator clustering -------------------------------------------------

def _owner_agg(slug, display, mail_keys, properties, open_v=0, all_v=0, c311=0):
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
    clusters, mapping = _build_operator_clusters(by_owner)
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
    """A mailing address shared by > GENERIC_ADDRESS_OWNER_CAP owners is treated
    as a service provider and never seeds a cluster.
    """
    lawyer_mail = "100 LAW ST | BUFFALO | NY | 14202"
    by_owner = {
        f"unrelated llc {i}": _owner_agg(f"unrelated-{i}", f"Unrelated {i} LLC",
                                         {lawyer_mail: 1}, 1)
        for i in range(GENERIC_ADDRESS_OWNER_CAP + 5)
    }
    clusters, mapping = _build_operator_clusters(by_owner)
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
    clusters, mapping = _build_operator_clusters(by_owner)
    # Only one owner has a mailing key → not a cluster (need ≥2 owners).
    assert clusters == {}


def test_solo_llc_not_clustered():
    """A single LLC with multiple parcels mailed to one address is not a cluster."""
    by_owner = {
        "lonely llc": _owner_agg("lonely-llc", "Lonely LLC",
                                 {"PO BOX 99 | BUFFALO | NY | 14210": 10}, 10),
    }
    clusters, mapping = _build_operator_clusters(by_owner)
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
    clusters, _ = _build_operator_clusters(by_owner)
    assert clusters == {}


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
    clusters, mapping = _build_operator_clusters(by_owner)
    assert clusters == {}
    assert mapping == {}
