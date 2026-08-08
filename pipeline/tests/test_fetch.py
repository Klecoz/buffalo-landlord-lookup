"""Tests for fetch.py — the only module that talks to the network.

Covers the two seam-failure modes that have bitten us before:
  - Pagination boundaries (Socrata + ArcGIS return early when page < limit).
  - Atomic write: the .tmp file must be cleaned up on failure so a half-
    written cache doesn't masquerade as a successful prior fetch.

HTTP is mocked end-to-end via responses; no real requests leave the test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch as fetch_mod


# --- _atomic_write_json --------------------------------------------------


def test_atomic_write_json_writes_payload(tmp_path: Path):
    out = tmp_path / "data.json"
    fetch_mod._atomic_write_json(out, {"hello": "world"})
    assert out.exists()
    assert json.loads(out.read_text()) == {"hello": "world"}


def test_atomic_write_json_no_tmp_left_after_success(tmp_path: Path):
    """The .json.tmp sibling must not survive a successful write."""
    out = tmp_path / "data.json"
    fetch_mod._atomic_write_json(out, [1, 2, 3])
    assert not (tmp_path / "data.json.tmp").exists()


def test_atomic_write_json_cleans_tmp_on_failure(tmp_path: Path):
    """If json.dump raises, the .tmp file must be removed so a partial
    write can't be mistaken for a successful prior fetch on the next run."""
    out = tmp_path / "data.json"

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        fetch_mod._atomic_write_json(out, {"bad": Unserializable()})

    assert not out.exists()
    assert not (tmp_path / "data.json.tmp").exists()


def test_atomic_write_json_overwrites_existing(tmp_path: Path):
    """Replace must be atomic — second write overwrites first cleanly."""
    out = tmp_path / "data.json"
    fetch_mod._atomic_write_json(out, {"v": 1})
    fetch_mod._atomic_write_json(out, {"v": 2})
    assert json.loads(out.read_text()) == {"v": 2}
    assert not (tmp_path / "data.json.tmp").exists()


# --- _socrata pagination ------------------------------------------------


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")


def test_socrata_short_page_terminates_pagination(monkeypatch):
    """A page strictly smaller than PAGE_SIZE means we've reached the end —
    paginate must stop and not request another page."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["$offset"])
        # Return 1 row (much less than PAGE_SIZE=50_000), so loop terminates.
        return _FakeResponse([{"id": "a"}])

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    rows = fetch_mod._socrata("dataset-id")
    assert rows == [{"id": "a"}]
    assert calls == [0]


def test_socrata_full_page_paginates_again(monkeypatch):
    """A page exactly PAGE_SIZE rows must trigger another fetch at the
    next offset (we don't know it's the last page from the size alone)."""
    page_size = fetch_mod.PAGE_SIZE
    pages = [
        [{"i": i} for i in range(page_size)],   # full page → keep going
        [{"i": page_size}],                      # short page → stop
    ]
    offsets = []

    def fake_get(url, params=None, timeout=None):
        offsets.append(params["$offset"])
        return _FakeResponse(pages.pop(0))

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    rows = fetch_mod._socrata("dataset-id")
    assert offsets == [0, page_size]
    assert len(rows) == page_size + 1


def test_socrata_passes_where_clause(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params)
        return _FakeResponse([])

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    fetch_mod._socrata("dataset-id", where="status='ACTIVE'")
    assert captured["$where"] == "status='ACTIVE'"


def test_socrata_propagates_http_error(monkeypatch):
    """A 5xx must surface — silent failures here mean stale caches in prod."""
    import requests

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"error": "boom"}, status=500)

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    with pytest.raises(requests.HTTPError):
        fetch_mod._socrata("dataset-id")


# --- _arcgis_geojson pagination ----------------------------------------


def test_arcgis_pagination_stops_when_no_exceeded_flag(monkeypatch):
    """ArcGIS uses exceededTransferLimit. When it's missing/false AND the
    page is short, pagination must stop."""
    pages = [
        # Full page but no exceededTransferLimit → still stop because page < ARC_PAGE? Actually full ARC_PAGE rows means we keep going.
        # Use short page (<ARC_PAGE) with no exceeded flag → stop.
        {"features": [{"id": 1}, {"id": 2}]},
    ]
    offsets = []

    def fake_get(url, params=None, timeout=None):
        offsets.append(params["resultOffset"])
        return _FakeResponse(pages.pop(0))

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda *_: None)
    fc = fetch_mod._arcgis_geojson("http://x", "1=1")
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    assert offsets == [0]


def test_arcgis_pagination_continues_on_exceeded_transfer_limit(monkeypatch):
    """exceededTransferLimit:true must trigger another page even if the
    current page is short of ARC_PAGE."""
    arc_page = fetch_mod.ARC_PAGE
    pages = [
        {"features": [{"i": i} for i in range(arc_page)], "exceededTransferLimit": True},
        {"features": [{"i": arc_page}]},  # short page → stop
    ]
    offsets = []

    def fake_get(url, params=None, timeout=None):
        offsets.append(params["resultOffset"])
        return _FakeResponse(pages.pop(0))

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda *_: None)
    fc = fetch_mod._arcgis_geojson("http://x", "1=1")
    assert offsets == [0, arc_page]
    assert len(fc["features"]) == arc_page + 1


def test_arcgis_empty_page_terminates(monkeypatch):
    """An empty features page is also a stop condition — guards against
    infinite loops when an ArcGIS endpoint quietly returns nothing."""
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"features": [], "exceededTransferLimit": True})

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda *_: None)
    fc = fetch_mod._arcgis_geojson("http://x", "1=1")
    assert fc["features"] == []


# --- public entry points: smoke through fetch_311_housing -----------------


def test_fetch_311_housing_writes_file_and_uses_dpis_filter(tmp_path, monkeypatch):
    """End-to-end seam test: fetch_311_housing pulls rows, writes the
    expected file, and passes the documented DPIS/BMHA where-clause."""
    captured_where = []

    def fake_get(url, params=None, timeout=None):
        captured_where.append(params.get("$where"))
        return _FakeResponse([{"case": "abc"}])

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    monkeypatch.setattr(fetch_mod, "RAW", tmp_path)

    out = fetch_mod.fetch_311_housing()
    assert out == tmp_path / "service_requests_311.json"
    assert json.loads(out.read_text()) == [{"case": "abc"}]
    # The dataset is filtered at the API to housing-related subjects only.
    assert any("DPIS" in (w or "") for w in captured_where)
    assert any("Buffalo Municipal Housing Authority" in (w or "") for w in captured_where)


# --- _socrata paging stability (unordered queries drop rows) --------------


class _UnstableSocrataServer:
    """Models a real Socrata dataset paged without `$order`.

    SODA does not guarantee a stable row order across requests unless the
    query names one, so consecutive `$offset` windows can be sliced out of
    differently-ordered result sets. This fake reproduces that by rotating
    its backing rows on every request that arrives without `$order`, which
    makes some rows appear twice and others never appear at all.
    """

    def __init__(self, rows, page_size):
        self.rows = rows
        self.page_size = page_size
        self.requests = 0

    def get(self, url, params=None, timeout=None):
        self.requests += 1
        rows = self.rows
        if not params.get("$order"):
            # A different arbitrary order on each request — the windows no
            # longer tile the dataset.
            shift = (self.page_size // 2) * self.requests
            rows = rows[shift:] + rows[:shift]
        offset = params["$offset"]
        return _FakeResponse(rows[offset:offset + params["$limit"]])


def test_socrata_requests_a_stable_order(monkeypatch):
    """Every page request must name an `$order`, or SODA is free to return
    the windows out of a re-sorted result set."""
    orders = []

    def fake_get(url, params=None, timeout=None):
        orders.append(params.get("$order"))
        return _FakeResponse([])

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    fetch_mod._socrata("dataset-id")
    assert orders == [":id"]


def test_socrata_multi_page_fetch_loses_no_rows(monkeypatch):
    """The regression that cost us 8,956 code violations on 2026-08-07:
    a multi-page pull off an unordered query silently substituted duplicate
    rows for missing ones while keeping the total row count correct."""
    monkeypatch.setattr(fetch_mod, "PAGE_SIZE", 100)
    expected = [{"uniquekey": str(i)} for i in range(250)]
    server = _UnstableSocrataServer(expected, fetch_mod.PAGE_SIZE)
    monkeypatch.setattr(fetch_mod.requests, "get", server.get)

    rows = fetch_mod._socrata("dataset-id")

    from collections import Counter
    assert Counter(r["uniquekey"] for r in rows) == Counter(
        r["uniquekey"] for r in expected
    )
