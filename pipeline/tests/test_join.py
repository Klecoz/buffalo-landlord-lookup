"""Tests for join.py — the parcel-spine assembly and join logic."""

import sys
from datetime import date
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
    matched, max_date = _join_violations(by_addr, violations)
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


def test_join_311_window_includes_boundary_day():
    """The cutoff is calendar-year-back, so a complaint exactly one year
    before the anchor (same month/day) is included. Guards against the
    365-day off-by-one across leap years.
    """
    fc = _parcel_fc([
        {"LOC_ST_NBR": "100", "LOC_STREET": "Main", "PRIMARY_OWNER": "X", "SBL": "AAA"},
    ])
    parcels, by_addr = _build_parcel_records(fc)
    requests = [
        # Anchor (max date) lands across a leap year — 2024 is a leap year,
        # so a naive timedelta(days=365) cutoff would land on 2023-05-11 and
        # exclude the boundary record below.
        {"subject": "DPIS", "address_number": "100", "address_line_1": "Main",
         "open_date": "2024-05-10T00:00:00"},
        {"subject": "DPIS", "address_number": "100", "address_line_1": "Main",
         "open_date": "2023-05-10T00:00:00"},  # exactly 12 months back — must be IN window
    ]
    matched, _ = _join_311(by_addr, requests)
    assert matched == 2
    assert by_addr["100 MAIN"]["complaints_311_12mo"] == 2


def _demo_parcel_fc(**overrides):
    """One vacant-lot parcel at 999 DEMOLISH RD, SBL padded like the real feed."""
    row = {
        "LOC_ST_NBR": "999", "LOC_STREET": "Demolish Rd", "PRIMARY_OWNER": "X",
        "SBL": "10073000060080000000", "PROP_CLASS": "311",
        "LAND_AV": 5000, "TOTAL_AV": 5000,
    }
    row.update(overrides)
    return _parcel_fc([row])


def test_join_demolitions_matches_by_padded_sbl():
    """Permit SBLs are 16 chars; parcel SBLs carry a 4-digit sub-parcel
    suffix. The permit key is right-padded with zeros to line them up."""
    parcels, by_addr = _build_parcel_records(_demo_parcel_fc())
    demos = [{
        "stname": "SOME OTHER ADDRESS", "apno": "BLD-1",
        "sbl": "1007300006008000", "issued": "2024-03-04T00:00:00.000",
    }]
    stats = _join_demolitions(parcels, by_addr, demos)
    assert stats["matched_sbl"] == 1
    assert stats["matched_address"] == 0
    p = by_addr["999 DEMOLISH RD"]
    assert p["demolished"] is True
    assert p["demo_permit"] == {"date": "2024-03-04", "via": "sbl"}


def test_join_demolitions_falls_back_to_address_without_sbl():
    parcels, by_addr = _build_parcel_records(_demo_parcel_fc())
    demos = [{"stname": "999 Demolish Rd", "apno": "BLD-1", "issued": "2024-03-04T00:00:00.000"}]
    stats = _join_demolitions(parcels, by_addr, demos)
    assert stats["matched_sbl"] == 0
    assert stats["matched_address"] == 1
    assert by_addr["999 DEMOLISH RD"]["demo_permit"]["via"] == "address"


def test_join_demolitions_ignores_junk_short_sbl():
    """A handful of permits carry 4-6 char values in `sbl`. Those are not
    SBLs — fall through to the address rather than matching on a prefix."""
    parcels, by_addr = _build_parcel_records(_demo_parcel_fc())
    demos = [{"stname": "999 Demolish Rd", "sbl": "10073", "issued": "2024-03-04T00:00:00.000"}]
    stats = _join_demolitions(parcels, by_addr, demos)
    assert stats["matched_address"] == 1
    assert by_addr["999 DEMOLISH RD"]["demo_permit"]["via"] == "address"


def test_join_demolitions_counts_sbl_address_disagreement():
    """When a permit's SBL and its address point at different parcels, the
    SBL wins and the disagreement is counted for the console summary."""
    fc = _parcel_fc([
        {"LOC_ST_NBR": "999", "LOC_STREET": "Demolish Rd", "PRIMARY_OWNER": "X",
         "SBL": "10073000060080000000", "PROP_CLASS": "311"},
        {"LOC_ST_NBR": "111", "LOC_STREET": "Other St", "PRIMARY_OWNER": "Y",
         "SBL": "99999000060080000000", "PROP_CLASS": "311"},
    ])
    parcels, by_addr = _build_parcel_records(fc)
    demos = [{
        "stname": "111 Other St", "sbl": "1007300006008000",
        "issued": "2024-03-04T00:00:00.000",
    }]
    stats = _join_demolitions(parcels, by_addr, demos)
    assert stats["sbl_address_disagreements"] == 1
    assert by_addr["999 DEMOLISH RD"]["demolished"] is True
    assert by_addr["111 OTHER ST"]["demolished"] is False


def test_join_demolitions_latest_permit_wins():
    parcels, by_addr = _build_parcel_records(_demo_parcel_fc())
    demos = [
        {"stname": "999 Demolish Rd", "issued": "2011-06-01T00:00:00.000"},
        {"stname": "999 Demolish Rd", "issued": "2023-09-15T00:00:00.000"},
        {"stname": "999 Demolish Rd", "issued": "2004-01-20T00:00:00.000"},
    ]
    _join_demolitions(parcels, by_addr, demos)
    assert by_addr["999 DEMOLISH RD"]["demo_permit"]["date"] == "2023-09-15"


def test_join_demolitions_requires_vacancy():
    """A permit on a parcel that still assesses as an improved building is
    recorded, but does not make the parcel demolished — permits get pulled,
    abandoned, and superseded by rebuilds."""
    fc = _demo_parcel_fc(PROP_CLASS="210", LAND_AV=8000, TOTAL_AV=95000)
    parcels, by_addr = _build_parcel_records(fc)
    demos = [{"stname": "999 Demolish Rd", "issued": "2024-03-04T00:00:00.000"}]
    stats = _join_demolitions(parcels, by_addr, demos)
    assert stats["demolished_parcels"] == 0
    assert stats["permit_but_not_vacant"] == 1
    p = by_addr["999 DEMOLISH RD"]
    assert p["demolished"] is False
    assert p["demo_permit"]["date"] == "2024-03-04"


def test_join_demolitions_vacancy_via_assessment_only():
    """PROP_CLASS still says dwelling but the improvement carries no value —
    total assessed has fallen to the land-only figure. That's a cleared lot
    the class code hasn't caught up with."""
    fc = _demo_parcel_fc(PROP_CLASS="210", LAND_AV=6000, TOTAL_AV=6000)
    parcels, by_addr = _build_parcel_records(fc)
    demos = [{"stname": "999 Demolish Rd", "issued": "2024-03-04T00:00:00.000"}]
    stats = _join_demolitions(parcels, by_addr, demos)
    assert stats["demolished_parcels"] == 1


def test_join_demolitions_missing_assessment_is_not_vacancy():
    """LAND_AV and TOTAL_AV both zero is a roll record with no assessment at
    all. Silence isn't evidence — without a 3xx class it doesn't count."""
    fc = _demo_parcel_fc(PROP_CLASS="210", LAND_AV=0, TOTAL_AV=0)
    parcels, by_addr = _build_parcel_records(fc)
    demos = [{"stname": "999 Demolish Rd", "issued": "2024-03-04T00:00:00.000"}]
    stats = _join_demolitions(parcels, by_addr, demos)
    assert stats["demolished_parcels"] == 0
    assert stats["permit_but_not_vacant"] == 1


def test_join_demolitions_reports_max_issued_date():
    parcels, by_addr = _build_parcel_records(_demo_parcel_fc())
    demos = [
        {"stname": "999 Demolish Rd", "issued": "2019-02-01T00:00:00.000"},
        {"stname": "NOWHERE AT ALL", "issued": "2026-07-30T00:00:00.000"},
    ]
    stats = _join_demolitions(parcels, by_addr, demos)
    # Max date spans unmatched permits too — it describes the feed, not the join.
    assert stats["max_issued"] == "2026-07-30"
    assert stats["unmatched"] == 1


def test_concern_score_formula():
    p = {"code_violations_open": 3, "complaints_311_12mo": 2, "demolished": False}
    assert _compute_concern_score(p) == 8  # 2*3 + 1*2


def test_concern_score_demolition_recency_window():
    """A recent demolition adds 5; an old one still shows as demolished on
    the map but stops driving the score."""
    today = date(2026, 8, 7)
    recent = {
        "code_violations_open": 0, "complaints_311_12mo": 0,
        "demolished": True, "demo_permit": {"date": "2024-05-02", "via": "sbl"},
    }
    old = {
        "code_violations_open": 0, "complaints_311_12mo": 0,
        "demolished": True, "demo_permit": {"date": "2019-05-02", "via": "sbl"},
    }
    assert _compute_concern_score(recent, today=today) == 5
    assert _compute_concern_score(old, today=today) == 0


def test_concern_score_demolition_window_boundary():
    """The window is calendar-years-back and inclusive of the boundary day."""
    today = date(2026, 8, 7)
    on_boundary = {
        "code_violations_open": 0, "complaints_311_12mo": 0,
        "demolished": True, "demo_permit": {"date": "2021-08-07", "via": "sbl"},
    }
    day_before = {
        "code_violations_open": 0, "complaints_311_12mo": 0,
        "demolished": True, "demo_permit": {"date": "2021-08-06", "via": "sbl"},
    }
    assert _compute_concern_score(on_boundary, today=today) == 5
    assert _compute_concern_score(day_before, today=today) == 0


def test_parcel_record_carries_add_owner():
    """ADD_OWNER from raw parcel properties is preserved on the parcel record
    so downstream stages can mine it for cross-LLC identity links."""
    from join import _build_parcel_records
    geo = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "PRIMARY_OWNER": "ACME PROPERTIES LLC",
                "ADD_OWNER": "Smith, John A",
                "LOC_ST_NBR": "100", "LOC_STREET": "MAIN ST",
                "LOC_ZIP": "14215",
                "MAIL_ADDR": "100 MAIN ST", "MAIL_CITY": "BUFFALO",
                "MAIL_STATE": "NY", "MAIL_ZIP": "14215",
                "PARCEL_ADDR": "100 MAIN ST",
                "PRINT_KEY": "ABC", "SBL": "1.00-1-1",
                "FULL_MARKET_VAL": 0, "PROP_CLASS": 220, "YR_BLT": 1900,
            },
            "geometry": {"type": "Point", "coordinates": [-78.8, 42.9]},
        }],
    }
    parcels, _ = _build_parcel_records(geo)
    assert len(parcels) == 1
    assert parcels[0]["add_owner"] == "Smith, John A"


def test_parcel_record_add_owner_blank_when_missing():
    """ADD_OWNER absent from properties yields an empty-string field, not KeyError."""
    from join import _build_parcel_records
    geo = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "PRIMARY_OWNER": "JONES LLC",
                "LOC_ST_NBR": "200", "LOC_STREET": "OAK ST",
                "LOC_ZIP": "14215",
                "MAIL_ADDR": "200 OAK ST", "MAIL_CITY": "BUFFALO",
                "MAIL_STATE": "NY", "MAIL_ZIP": "14215",
                "PARCEL_ADDR": "200 OAK ST",
                "PRINT_KEY": "XYZ", "SBL": "1.00-1-2",
                "FULL_MARKET_VAL": 0, "PROP_CLASS": 220, "YR_BLT": 1900,
            },
            "geometry": {"type": "Point", "coordinates": [-78.8, 42.9]},
        }],
    }
    parcels, _ = _build_parcel_records(geo)
    assert parcels[0]["add_owner"] == ""
