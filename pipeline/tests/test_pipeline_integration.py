"""End-to-end integration test for the pipeline composition.

The unit tests cover each module in isolation. This file exercises the
join → emit seam: writes synthetic raw fixtures to a tmp directory,
runs join_all() + emit() against them, and asserts the resulting web/data
artifacts have the expected shape.

The goal is not deep coverage — those tests live elsewhere — but to catch
the kind of breakage that only shows up across the seam: renamed dict
keys, removed required fields, accidental schema drift in emit's output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import join as join_mod
import emit as emit_mod


# --- Fixture builders ---------------------------------------------------


def _parcel_feature(
    sbl: str,
    addr: str,
    owner: str,
    *,
    mail_addr: str | None = None,
    mail_city: str = "BUFFALO",
    mail_state: str = "NY",
    mail_zip: str = "14215",
    market_val: int = 100_000,
    prop_class: str = "210",
) -> dict:
    """Build a minimal GeoJSON feature mirroring the NYS parcel schema
    (subset of fields that join._build_parcel_records actually reads)."""
    num, _, street = addr.partition(" ")
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            # Tiny square around a Buffalo lat/lng so centroid math works.
            "coordinates": [[
                [-78.870, 42.880], [-78.869, 42.880],
                [-78.869, 42.881], [-78.870, 42.881],
                [-78.870, 42.880],
            ]],
        },
        "properties": {
            "SBL": sbl,
            "PRINT_KEY": sbl,
            "OBJECTID": sbl,
            "LOC_ST_NBR": num,
            "LOC_STREET": street,
            "PARCEL_ADDR": addr,
            "PRIMARY_OWNER": owner,
            "ADD_OWNER": "",
            "MAIL_ADDR": mail_addr if mail_addr is not None else addr,
            "MAIL_CITY": mail_city,
            "MAIL_STATE": mail_state,
            "MAIL_ZIP": mail_zip,
            "PO_BOX": "",
            "PROP_CLASS": prop_class,
            "YR_BLT": 1920,
            "FULL_MARKET_VAL": market_val,
        },
    }


def _write_fixtures(raw_dir: Path) -> None:
    """Lay down the four raw files join_all() reads."""
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 3 parcels: two share a non-self mailing address (operator-cluster bait,
    # though our cluster threshold is higher — we just want emit() to walk
    # the whole code path without crashing).
    parcels = {
        "type": "FeatureCollection",
        "features": [
            _parcel_feature(
                "001-1", "100 MAIN ST", "ACME LLC",
                mail_addr="999 OFFSITE AVE",
            ),
            _parcel_feature(
                "001-2", "200 MAIN ST", "ACME PROPERTIES LLC",
                mail_addr="999 OFFSITE AVE",
            ),
            _parcel_feature(
                "001-3", "300 ELM ST", "JOHN SMITH",
                # mail = parcel addr → owner-occupied
                mail_addr="300 ELM ST",
                # 3xx = vacant land, which is what corroborates the
                # demolition permit below into demolished == True.
                prop_class="311",
            ),
        ],
    }
    (raw_dir / "parcels.geojson").write_text(json.dumps(parcels))

    # One open violation on parcel 1, one closed on parcel 2.
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00.000")
    violations = [
        {
            "address": "100 MAIN ST", "status": "ACTIVE",
            "date": today_iso, "description": "Broken windows",
            "code_section": "X.1",
        },
        {
            "address": "200 MAIN ST", "status": "CLOSED",
            "date": today_iso, "description": "Old peeling paint",
            "code_section": "X.2",
        },
    ]
    (raw_dir / "code_violations.json").write_text(json.dumps(violations))

    # Two 311 calls for parcel 1, both within the dataset's 12-month window
    # (the window is anchored to the dataset's max date, not today).
    requests_311 = [
        {
            "address_number": "100", "address_line_1": "MAIN ST",
            "open_date": today_iso, "subject": "DPIS",
            "reason": "no heat", "type": "housing",
        },
        {
            "address_number": "100", "address_line_1": "MAIN ST",
            "open_date": today_iso, "subject": "DPIS",
            "reason": "rodent", "type": "housing",
        },
    ]
    (raw_dir / "service_requests_311.json").write_text(json.dumps(requests_311))

    # One demolition matched to parcel 3, issued recently enough to score.
    demolitions = [{
        "stname": "300 ELM ST", "apno": "DEMO-1", "sbl": "001-3",
        "issued": today_iso,
    }]
    (raw_dir / "demolitions.json").write_text(json.dumps(demolitions))


# --- The integration test -----------------------------------------------


@pytest.fixture
def pipeline_paths(tmp_path, monkeypatch):
    """Redirect both modules' on-disk roots into tmp_path so the test
    doesn't read from or write to the real raw/ + web/data/ trees."""
    raw = tmp_path / "raw"
    web_data = tmp_path / "web_data"
    owners_dir = web_data / "owners"
    operators_dir = web_data / "operators"

    monkeypatch.setattr(join_mod, "RAW", raw)
    monkeypatch.setattr(emit_mod, "WEB_DATA", web_data)
    monkeypatch.setattr(emit_mod, "OWNERS_DIR", owners_dir)
    monkeypatch.setattr(emit_mod, "OPERATORS_DIR", operators_dir)

    _write_fixtures(raw)
    return {"raw": raw, "web_data": web_data, "owners": owners_dir, "operators": operators_dir}


def test_pipeline_join_then_emit_produces_expected_artifacts(pipeline_paths):
    """The full join→emit composition writes the four artifacts the
    frontend reads (properties.geojson, address_index, top_owners, meta)
    with the expected shape and counts."""
    joined = join_mod.join_all()
    emit_mod.emit(joined)

    web = pipeline_paths["web_data"]

    # All four frontend-required artifacts exist.
    for fname in ("properties.geojson", "address_index.json",
                  "top_owners.json", "meta.json"):
        assert (web / fname).exists(), f"missing emitted artifact: {fname}"

    # meta counts reflect our fixtures: 3 parcels in, 3 owners distinct.
    meta = json.loads((web / "meta.json").read_text())
    assert meta["parcels"] == 3
    assert meta["owners"] == 3
    assert meta["violations_total"] == 2
    assert meta["complaints_311_total"] == 2
    assert meta["demolitions_total"] == 1
    assert meta["violations_matched"] == 2
    assert meta["demolitions_matched"] == 1

    # properties.geojson is a real FeatureCollection, one feature per parcel.
    geo = json.loads((web / "properties.geojson").read_text())
    assert geo["type"] == "FeatureCollection"
    assert len(geo["features"]) == 3

    # The address index is the {addr,id,...} list the search box reads.
    idx = json.loads((web / "address_index.json").read_text())
    assert isinstance(idx, list) and len(idx) == 3
    assert {row["addr"] for row in idx} == {"100 MAIN ST", "200 MAIN ST", "300 ELM ST"}


def test_pipeline_owner_files_per_owner(pipeline_paths):
    """Per-owner JSON files are written and contain the expected parcels."""
    joined = join_mod.join_all()
    emit_mod.emit(joined)

    owner_files = list(pipeline_paths["owners"].glob("*.json"))
    # 3 distinct owners → 3 portfolio files.
    assert len(owner_files) == 3

    # Find the ACME LLC file (slug derived from normalized name).
    acme = next((f for f in owner_files if "acme-llc" in f.name), None)
    assert acme is not None, f"no acme file in {[f.name for f in owner_files]}"
    payload = json.loads(acme.read_text())
    assert payload["owner_display"]
    # ACME LLC has one parcel (100 MAIN ST). Other ACME variant gets its own slug.
    assert len(payload["properties"]) == 1
    assert payload["properties"][0]["addr"] == "100 MAIN ST"


def test_pipeline_concern_score_reflects_signals(pipeline_paths):
    """Parcel concern score = 2·open_violations + 1·311_12mo + 5·demolished.
    Confirms join._compute_concern_score wiring through to the GeoJSON."""
    joined = join_mod.join_all()
    emit_mod.emit(joined)

    geo = json.loads((pipeline_paths["web_data"] / "properties.geojson").read_text())
    by_addr = {f["properties"]["addr"]: f["properties"] for f in geo["features"]}

    # 100 MAIN ST: 1 open viol (2), 2 311 within window (2) = 4
    assert by_addr["100 MAIN ST"]["concern_score"] == 4
    # 200 MAIN ST: 0 open viol, 0 311, 0 demo = 0
    assert by_addr["200 MAIN ST"]["concern_score"] == 0
    # 300 ELM ST: recent demolition permit + vacant parcel class = 5
    assert by_addr["300 ELM ST"]["concern_score"] == 5
    assert by_addr["300 ELM ST"]["demolished"] is True
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # The permit rides through emit onto the map feature, and is omitted
    # entirely from the parcels that never had one.
    assert by_addr["300 ELM ST"]["demo_permit"]["date"] == today
    assert "demo_permit" not in by_addr["100 MAIN ST"]


def test_pipeline_runs_with_dos_index(pipeline_paths):
    """emit() accepts the DOS agent_address_index kwarg without breaking
    the artifact shape — guards the recent NYS DOS join from regressing."""
    joined = join_mod.join_all()
    # Empty index simulates "DOS fetch ran but nothing matched" — the
    # interesting code path is that emit doesn't crash on empty.
    emit_mod.emit(joined, agent_address_index={}, dos_max_date="2026-04-01")

    meta = json.loads((pipeline_paths["web_data"] / "meta.json").read_text())
    assert meta["parcels"] == 3
