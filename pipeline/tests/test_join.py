"""Tests for join.py — the parcel-spine assembly and join logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from join import (
    _build_parcel_records,
    _compute_concern_score,
    _join_311,
    _join_demolitions,
    _join_violations,
)


def _parcel_fc(rows):
    """Tiny GeoJSON FeatureCollection builder for tests."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": p,
                "geometry": {"type": "Point", "coordinates": [-78.85, 42.91]},
            }
            for p in rows
        ],
    }


def test_build_parcel_records_basic():
    fc = _parcel_fc([
        {
            "LOC_ST_NBR": "216", "LOC_STREET": "Landon",
            "PRIMARY_OWNER": "ACME PROPERTIES LLC",
            "SBL": "AAA", "PRINT_KEY": "1.1-1-1",
            "FULL_MARKET_VAL": 175000,
        },
    ])
    parcels, by_addr = _build_parcel_records(fc)
    assert len(parcels) == 1
    assert "216 LANDON" in by_addr
    p = by_addr["216 LANDON"]
    assert p["owner_norm"] == "acme properties llc"
    assert p["lat"] == 42.91 and p["lng"] == -78.85
    assert p["full_market_val"] == 175000


def test_build_parcel_records_missing_value_defaults_zero():
    fc = _parcel_fc([
        {"LOC_ST_NBR": "1", "LOC_STREET": "Main", "PRIMARY_OWNER": "X", "SBL": "A"},
    ])
    parcels, _ = _build_parcel_records(fc)
    assert parcels[0]["full_market_val"] == 0


def test_build_parcel_records_drops_unaddressed():
    fc = _parcel_fc([
        {"PRIMARY_OWNER": "X", "SBL": "AAA"},  # no address fields
    ])
    parcels, by_addr = _build_parcel_records(fc)
    assert parcels == []
    assert by_addr == {}


def test_join_violations_aggregates_open_total_and_date():
    fc = _parcel_fc([
        {"LOC_ST_NBR": "216", "LOC_STREET": "Landon", "PRIMARY_OWNER": "X", "SBL": "AAA"},
    ])
    parcels, by_addr = _build_parcel_records(fc)
    violations = [
        {"address": "216 Landon", "status": "ACTIVE",
         "date": "2026-01-01T00:00:00.000", "description": "leak"},
        {"address": "216 LANDON ST", "status": "CLOSED",
         "date": "2024-05-01T00:00:00.000", "description": "old"},
        {"address": "216 LANDON", "status": "ACTIVE",
         "date": "2025-08-15T00:00:00.000", "description": "rodents"},
    ]
    matched = _join_violations(by_addr, violations)
    assert matched == 3
    p = by_addr["216 LANDON"]
    assert p["code_violations_total"] == 3
    assert p["code_violations_open"] == 2
    assert p["last_violation_date"].startswith("2026-01-01")


def test_join_311_window_anchored_on_max_date():
    """The 12-month window is anchored to the dataset's MAX open_date so a
    stale dataset still reports something in `complaints_311_12mo`.
    """
    fc = _parcel_fc([
        {"LOC_ST_NBR": "100", "LOC_STREET": "Main", "PRIMARY_OWNER": "X", "SBL": "AAA"},
    ])
    parcels, by_addr = _build_parcel_records(fc)
    requests = [
        # max date is 2024-05-10; anchor 12 months back -> 2023-05-10
        {"subject": "DPIS", "address_number": "100", "address_line_1": "Main",
         "open_date": "2024-05-10T00:00:00"},  # in window
        {"subject": "DPIS", "address_number": "100", "address_line_1": "Main",
         "open_date": "2023-09-01T00:00:00"},  # in window
        {"subject": "DPIS", "address_number": "100", "address_line_1": "Main",
         "open_date": "2022-01-01T00:00:00"},  # OUT of window
    ]
    matched, max_date = _join_311(by_addr, requests)
    assert matched == 2
    assert max_date.startswith("2024-05-10")
    assert by_addr["100 MAIN"]["complaints_311_12mo"] == 2


def test_join_demolitions_flags_parcel():
    fc = _parcel_fc([
        {"LOC_ST_NBR": "999", "LOC_STREET": "Demolish Rd", "PRIMARY_OWNER": "X", "SBL": "AAA"},
    ])
    parcels, by_addr = _build_parcel_records(fc)
    demos = [{"stname": "999 Demolish Rd", "apno": "BLD-1"}]
    matched = _join_demolitions(by_addr, demos)
    assert matched == 1
    assert by_addr["999 DEMOLISH RD"]["demolished"] is True


def test_concern_score_formula():
    p = {"code_violations_open": 3, "complaints_311_12mo": 2, "demolished": False}
    assert _compute_concern_score(p) == 8  # 2*3 + 1*2

    p2 = {"code_violations_open": 0, "complaints_311_12mo": 0, "demolished": True}
    assert _compute_concern_score(p2) == 5
