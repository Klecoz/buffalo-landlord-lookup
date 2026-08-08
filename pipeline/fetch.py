"""Fetch raw datasets from Buffalo OpenData and NYS GIS Clearinghouse.

Field/dataset IDs were probed live in Buffalo's catalog:
- Code violations parent: ivrf-k9vm  (the "Active Code Violations" view abwd-pczc
  is access-controlled, but the parent serves and includes a `status` field).
- 311 service requests: whkc-e5vr
- Permits: 9p2d-f3yt with aptype='DEMOLITION'
- Parcels: NYS Clearinghouse with MUNI_NAME='Buffalo'

Outputs JSON/GeoJSON files in raw/. Writes are atomic (tmp + rename) so
partial failures don't corrupt prior caches.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
RAW.mkdir(exist_ok=True)

SOCRATA_HOST = "https://data.buffalony.gov"
NYS_PARCELS = (
    "https://gisservices.its.ny.gov/arcgis/rest/services/"
    "NYS_Tax_Parcels_Public/FeatureServer/1/query"
)

PARCEL_WHERE = "MUNI_NAME='Buffalo'"

PAGE_SIZE = 50_000  # Socrata
ARC_PAGE = 1000     # ArcGIS REST


def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w") as f:
            json.dump(data, f)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _socrata(dataset_id: str, where: str | None = None) -> list[dict]:
    url = f"{SOCRATA_HOST}/resource/{dataset_id}.json"
    out: list[dict] = []
    offset = 0
    while True:
        # `$order` is not optional. SODA gives no stable row order to an
        # unordered query, so consecutive `$offset` windows can be sliced out
        # of differently-sorted result sets — the row count comes out right
        # while some rows are duplicated and others are silently missing.
        # `:id` is the internal row identifier, present on every dataset.
        params: dict[str, Any] = {
            "$limit": PAGE_SIZE,
            "$offset": offset,
            "$order": ":id",
        }
        if where:
            params["$where"] = where
        r = requests.get(url, params=params, timeout=180)
        r.raise_for_status()
        page = r.json()
        out.extend(page)
        print(f"  {dataset_id}: {len(out):,} rows", file=sys.stderr)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return out


def _arcgis_geojson(url: str, where: str) -> dict:
    features: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": "*",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": ARC_PAGE,
            "returnGeometry": "true",
            "outSR": "4326",
        }
        r = requests.get(url, params=params, timeout=240)
        r.raise_for_status()
        data = r.json()
        page = data.get("features", [])
        features.extend(page)
        print(f"  parcels: {len(features):,} features", file=sys.stderr)
        if not data.get("exceededTransferLimit") and len(page) < ARC_PAGE:
            break
        if not page:
            break
        offset += ARC_PAGE
        time.sleep(0.2)
    return {"type": "FeatureCollection", "features": features}


# --- Public entry points -------------------------------------------------

def fetch_code_violations() -> Path:
    """All code violations (active + closed). Filtered by status in join.py."""
    print("Fetching code violations (ivrf-k9vm)...", file=sys.stderr)
    rows = _socrata("ivrf-k9vm")
    out = RAW / "code_violations.json"
    _atomic_write_json(out, rows)
    return out


def fetch_311_housing() -> Path:
    """Housing-related 311 service requests.

    Filter at the API level by subject = DPIS (Department of Permits &
    Inspection Services) or BMHA (Buffalo Municipal Housing Authority).
    Note: this dataset stopped updating in 2024-05; see meta.json for
    `complaints_311_max_date` so the UI can disclose freshness.
    """
    where = "subject in('DPIS','Buffalo Municipal Housing Authority')"
    print("Fetching 311 housing requests (DPIS + BMHA)...", file=sys.stderr)
    rows = _socrata("whkc-e5vr", where=where)
    out = RAW / "service_requests_311.json"
    _atomic_write_json(out, rows)
    return out


def fetch_demolitions() -> Path:
    """Demolition permits (aptype='DEMOLITION', ~10k rows)."""
    print("Fetching demolition permits...", file=sys.stderr)
    rows = _socrata("9p2d-f3yt", where="aptype='DEMOLITION'")
    out = RAW / "demolitions.json"
    _atomic_write_json(out, rows)
    return out


def fetch_parcels() -> Path:
    """Buffalo parcels via NYS Clearinghouse FeatureServer (~93k features)."""
    print(f"Fetching parcels (where={PARCEL_WHERE})...", file=sys.stderr)
    fc = _arcgis_geojson(NYS_PARCELS, PARCEL_WHERE)
    out = RAW / "parcels.geojson"
    _atomic_write_json(out, fc)
    return out


def fetch_all() -> dict[str, Path]:
    return {
        "code_violations": fetch_code_violations(),
        "service_requests_311": fetch_311_housing(),
        "demolitions": fetch_demolitions(),
        "parcels": fetch_parcels(),
    }


if __name__ == "__main__":
    fetch_all()
