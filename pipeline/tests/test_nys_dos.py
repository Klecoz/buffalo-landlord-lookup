"""Tests for the NYS DOS service-address enrichment.

Covers two pure pieces — the index builder (counting distinct DOS entities
per normalized service-of-process address) and the threshold classifier.
The Socrata fetch is not exercised here; integration is verified end-to-end
via the pipeline run.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cluster_score import (
    REGISTERED_AGENT_THRESHOLD,
    classify_service_address,
)
from nys_dos import build_index_from_records, _normalize_dos_record


# --- _normalize_dos_record ----------------------------------------------

def test_normalize_dos_record_matches_pipeline_mailing_format():
    """A DOS record's process address normalizes to the same '|'-joined
    key the rest of the pipeline uses for cluster mailing addresses."""
    rec = {
        "dos_id": "1",
        "dos_process_address_1": "100 Main Street",
        "dos_process_city": "Buffalo",
        "dos_process_state": "NY",
        "dos_process_zip": "14215",
    }
    assert _normalize_dos_record(rec) == "100 MAIN ST | BUFFALO | NY | 14215"


def test_normalize_dos_record_handles_empty():
    assert _normalize_dos_record({"dos_id": "1"}) == ""
    assert _normalize_dos_record({}) == ""


def test_normalize_dos_record_handles_po_box():
    rec = {
        "dos_id": "2",
        "dos_process_address_1": "P.O. Box 42",
        "dos_process_city": "Albany",
        "dos_process_state": "NY",
        "dos_process_zip": "12207",
    }
    assert _normalize_dos_record(rec) == "PO BOX 42 | ALBANY | NY | 12207"


# --- build_index_from_records -------------------------------------------

def test_build_index_counts_distinct_entities():
    """Two entities at the same normalized service address → count of 2."""
    records = [
        {
            "dos_id": "1",
            "dos_process_address_1": "100 Main St",
            "dos_process_city": "Buffalo",
            "dos_process_state": "NY",
            "dos_process_zip": "14215",
        },
        {
            "dos_id": "2",
            "dos_process_address_1": "100 MAIN STREET",  # same after normalize
            "dos_process_city": "BUFFALO",
            "dos_process_state": "NY",
            "dos_process_zip": "14215",
        },
        {
            "dos_id": "3",
            "dos_process_address_1": "200 Oak Ave",
            "dos_process_city": "Buffalo",
            "dos_process_state": "NY",
            "dos_process_zip": "14215",
        },
    ]
    index = build_index_from_records(records)
    assert index["100 MAIN ST | BUFFALO | NY | 14215"] == 2
    assert index["200 OAK AVE | BUFFALO | NY | 14215"] == 1


def test_build_index_dedupes_repeated_dos_id():
    """The same dos_id appearing twice (paginator overlap, etc.) is counted once."""
    records = [
        {
            "dos_id": "1",
            "dos_process_address_1": "100 Main St",
            "dos_process_city": "Buffalo",
            "dos_process_state": "NY",
            "dos_process_zip": "14215",
        },
        {
            "dos_id": "1",  # same dos_id
            "dos_process_address_1": "100 Main St",
            "dos_process_city": "Buffalo",
            "dos_process_state": "NY",
            "dos_process_zip": "14215",
        },
    ]
    index = build_index_from_records(records)
    assert index["100 MAIN ST | BUFFALO | NY | 14215"] == 1


def test_build_index_skips_unparseable_rows():
    """Rows without a parseable address or without a dos_id are ignored."""
    records = [
        {"dos_id": "1"},                                   # no address
        {"dos_process_address_1": "100 Main St"},          # no dos_id
        {                                                   # valid
            "dos_id": "2",
            "dos_process_address_1": "100 Main St",
            "dos_process_city": "Buffalo",
            "dos_process_state": "NY",
            "dos_process_zip": "14215",
        },
    ]
    index = build_index_from_records(records)
    assert index == {"100 MAIN ST | BUFFALO | NY | 14215": 1}


# --- classify_service_address ------------------------------------------

def test_classify_at_threshold_boundary():
    """Counts at the threshold and above flip to registered_agent; below stays out."""
    assert classify_service_address(REGISTERED_AGENT_THRESHOLD - 1, "street") == "unknown"
    assert classify_service_address(REGISTERED_AGENT_THRESHOLD, "street") == "registered_agent"
    assert classify_service_address(REGISTERED_AGENT_THRESHOLD + 1, "street") == "registered_agent"


def test_classify_zero_on_street_is_shared_owner():
    """A street address with no DOS pool is positive evidence of shared ownership."""
    assert classify_service_address(0, "street") == "shared_owner"


def test_classify_zero_on_po_box_is_unknown():
    """PO boxes don't get classified — DOS process addresses are streets,
    so a PO box won't match anyway and silence > false confidence."""
    assert classify_service_address(0, "po_box") == "unknown"
    assert classify_service_address(5, "po_box") == "unknown"


def test_classify_low_nonzero_is_unknown():
    """1–99 entities is ambiguous: too many to be a single owner's mailbox,
    too few to be a major registered-agent pool. Stay silent."""
    assert classify_service_address(1, "street") == "unknown"
    assert classify_service_address(50, "street") == "unknown"
    assert classify_service_address(99, "street") == "unknown"
