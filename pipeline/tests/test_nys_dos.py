"""Tests for the NYS DOS service-address enrichment.

Covers two pure pieces — the index builder (counting distinct DOS entities
per normalized service-of-process address) and the threshold classifier.
The Socrata fetch is not exercised here; integration is verified end-to-end
via the pipeline run.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cluster_score import (
    REGISTERED_AGENT_THRESHOLD,
    SHARED_OWNER_THRESHOLD,
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


def test_classify_below_shared_owner_threshold_is_shared_owner():
    """A street address with <SHARED_OWNER_THRESHOLD entities is too few to
    plausibly be a filing-service pool. Treat as shared-owner positive."""
    assert classify_service_address(SHARED_OWNER_THRESHOLD - 1, "street") == "shared_owner"


def test_classify_zero_on_po_box_is_unknown():
    """PO boxes don't get classified — DOS process addresses are streets,
    so a PO box won't match anyway and silence > false confidence."""
    assert classify_service_address(0, "po_box") == "unknown"
    assert classify_service_address(5, "po_box") == "unknown"


def test_classify_middle_range_is_unknown():
    """Counts between SHARED_OWNER_THRESHOLD and REGISTERED_AGENT_THRESHOLD
    are ambiguous — too many for a single owner's office, too few for a
    major registered-agent service. Stay silent."""
    assert classify_service_address(SHARED_OWNER_THRESHOLD, "street") == "unknown"
    assert classify_service_address(50, "street") == "unknown"
    assert classify_service_address(REGISTERED_AGENT_THRESHOLD - 1, "street") == "unknown"


# --- _paginate_dataset ---------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_paginate_dataset_requests_a_stable_order(monkeypatch):
    """Same SODA paging hazard as fetch.py: without an `$order`, the 4.2M-row
    active-corporations pull silently skips entities, undercounting the
    registered-agent pools this index exists to detect."""
    import nys_dos

    orders = []

    def fake_get(url, params=None, headers=None, timeout=None):
        orders.append(params.get("$order"))
        return _FakeResponse([])

    monkeypatch.setattr(nys_dos.requests, "get", fake_get)
    list(nys_dos._paginate_dataset(None))
    assert orders == [":id"]


# --- cache freshness -----------------------------------------------------


def test_index_is_fresh_false_when_file_absent(tmp_path):
    import nys_dos
    assert nys_dos._index_is_fresh(tmp_path / "nope.json", 30) is False


def test_index_is_fresh_true_for_a_just_written_file(tmp_path):
    import nys_dos
    p = tmp_path / "idx.json"
    p.write_text("{}")
    assert nys_dos._index_is_fresh(p, 30) is True


def test_index_is_fresh_false_past_the_window(tmp_path):
    import os
    import time as _time
    import nys_dos
    p = tmp_path / "idx.json"
    p.write_text("{}")
    old = _time.time() - 31 * 86400
    os.utime(p, (old, old))
    assert nys_dos._index_is_fresh(p, 30) is False


def _stub_network(monkeypatch, nys_dos, rows):
    monkeypatch.setattr(nys_dos, "_fetch_dataset_max_date", lambda token: "2026-07-01")
    monkeypatch.setattr(nys_dos, "_paginate_dataset", lambda token: iter(rows))


def test_corrupt_cache_is_refetched_not_fatal(tmp_path, monkeypatch):
    """A truncated cache file — an interrupted write, a full disk — used to
    abort the whole pipeline run with a JSONDecodeError. The cache is
    derived data; the right move is to rebuild it."""
    import nys_dos
    idx = tmp_path / "nys_dos_address_index.json"
    idx.write_text('{"index": {"1 MAIN ST | BUF')  # truncated mid-write
    monkeypatch.setattr(nys_dos, "INDEX_PATH", idx)
    _stub_network(monkeypatch, nys_dos, [{
        "dos_id": "1", "dos_process_address_1": "1 Main St",
        "dos_process_city": "Buffalo", "dos_process_state": "NY",
        "dos_process_zip": "14202",
    }])

    index, max_date = nys_dos.fetch_and_build_index()

    assert max_date == "2026-07-01"
    assert sum(index.values()) == 1
    # And the rebuilt cache is readable.
    assert json.loads(idx.read_text())["index"] == index


def test_cache_missing_index_key_is_refetched(tmp_path, monkeypatch):
    """An older/partial payload shape must not KeyError the run."""
    import nys_dos
    idx = tmp_path / "nys_dos_address_index.json"
    idx.write_text('{"source": "nys_dos_active_corporations"}')
    monkeypatch.setattr(nys_dos, "INDEX_PATH", idx)
    _stub_network(monkeypatch, nys_dos, [])

    index, _ = nys_dos.fetch_and_build_index()
    assert index == {}


def test_fresh_cache_is_used_without_touching_the_network(tmp_path, monkeypatch):
    import nys_dos
    idx = tmp_path / "nys_dos_address_index.json"
    idx.write_text(json.dumps({
        "index": {"1 MAIN ST | BUFFALO | NY | 14202": 7},
        "source_max_date": "2026-06-01",
        "address_count": 1,
    }))
    monkeypatch.setattr(nys_dos, "INDEX_PATH", idx)

    def explode(*a, **k):
        raise AssertionError("network hit despite a fresh cache")

    monkeypatch.setattr(nys_dos, "_paginate_dataset", explode)

    index, max_date = nys_dos.fetch_and_build_index()
    assert index == {"1 MAIN ST | BUFFALO | NY | 14202": 7}
    assert max_date == "2026-06-01"
