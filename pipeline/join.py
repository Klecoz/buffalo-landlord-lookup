"""Join raw datasets onto the parcel spine.

Parcels are the canonical record. Each parcel gets:
  parcel_id, address, lat, lng, owner_raw, owner_normalized, geometry,
  code_violations_open, code_violations_total, last_violation_date,
  complaints_311_12mo, demolished, concern_score
plus a flat list of recent violations and complaints kept for the
property-dossier UI.

Joins:
  - Code violations  -> parcel by normalized address (then SBL fallback)
  - 311 requests     -> parcel by normalized address; type-filtered
  - Demolitions      -> parcel by normalized address; signal only

We deliberately do not implement a true geospatial fallback for v1: the
address coverage is good enough that the residual is small, and the
build stays dependency-light. A future pass can add nearest-parcel
matching for orphans.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from normalize import (
    _STREET_TYPE_CANON,
    normalize_address,
    normalize_owner,
)


_STREET_TYPE_TOKENS = set(_STREET_TYPE_CANON.values())


def _strip_trailing_type(addr_norm: str) -> str:
    """'216 LANDON ST' -> '216 LANDON'. Used to tolerate parcel data that
    omits the street type while violations include it (or vice versa).
    """
    if not addr_norm:
        return addr_norm
    parts = addr_norm.split()
    if len(parts) >= 3 and parts[-1] in _STREET_TYPE_TOKENS:
        return " ".join(parts[:-1])
    return addr_norm


def _index_lookup(by_addr: dict, addr_norm: str):
    """Try exact match, then no-type fallback."""
    if not addr_norm:
        return None
    if addr_norm in by_addr:
        return by_addr[addr_norm]
    stripped = _strip_trailing_type(addr_norm)
    return by_addr.get(stripped) if stripped != addr_norm else None


HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"


# 311 types/subjects we count as housing-quality complaints. Substring match.
HOUSING_311_KEYWORDS = (
    "no heat",
    "heat",
    "hot water",
    "rodent",
    "vermin",
    "garbage",
    "trash",
    "illegal occupancy",
    "illegal conversion",
    "dwelling",
    "housing",
    "lead paint",
    "mold",
    "plumbing",
    "infestation",
)


def _load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    # Socrata returns "YYYY-MM-DDTHH:MM:SS.000" (no tz)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_housing_311(row: dict) -> bool:
    blob = " ".join(
        str(row.get(k, "") or "").lower()
        for k in ("subject", "reason", "type", "object_type")
    )
    return any(kw in blob for kw in HOUSING_311_KEYWORDS)


def _build_parcel_records(parcels_geo: dict) -> tuple[list[dict], dict[str, dict]]:
    """Return (parcels list, lookup-by-normalized-address)."""
    parcels: list[dict] = []
    by_addr: dict[str, dict] = {}

    for feat in parcels_geo["features"]:
        props = feat.get("properties", {})
        geom = feat.get("geometry")

        # Construct address from LOC_ST_NBR + LOC_STREET, fallback to PARCEL_ADDR.
        loc_nbr = props.get("LOC_ST_NBR") or ""
        loc_street = props.get("LOC_STREET") or ""
        if loc_nbr and loc_street:
            full_addr = f"{loc_nbr} {loc_street}".strip()
        else:
            full_addr = props.get("PARCEL_ADDR") or ""

        normalized = normalize_address(full_addr)
        if not normalized:
            continue

        # Compute parcel centroid for the map (rough — first ring's first vertex
        # if polygon, or the point itself).
        lat = lng = None
        if geom and geom.get("type") == "Polygon":
            try:
                coords = geom["coordinates"][0]
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                lng = sum(xs) / len(xs)
                lat = sum(ys) / len(ys)
            except (IndexError, ZeroDivisionError):
                pass
        elif geom and geom.get("type") == "MultiPolygon":
            try:
                coords = geom["coordinates"][0][0]
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                lng = sum(xs) / len(xs)
                lat = sum(ys) / len(ys)
            except (IndexError, ZeroDivisionError):
                pass
        elif geom and geom.get("type") == "Point":
            lng, lat = geom["coordinates"]

        owner_raw = (props.get("PRIMARY_OWNER") or "").strip()
        owner_norm = normalize_owner(owner_raw)
        sbl = props.get("SBL") or ""

        record = {
            "parcel_id": sbl or props.get("PRINT_KEY") or props.get("OBJECTID"),
            "print_key": props.get("PRINT_KEY"),
            "sbl": sbl,
            "address": full_addr,
            "address_norm": normalized,
            "lat": lat,
            "lng": lng,
            "owner_raw": owner_raw,
            "owner_norm": owner_norm,
            "prop_class": props.get("PROP_CLASS"),
            "year_built": props.get("YR_BLT"),
            "geometry": geom,
            # to be filled below
            "code_violations_open": 0,
            "code_violations_total": 0,
            "complaints_311_12mo": 0,
            "demolished": False,
            "last_violation_date": None,
            "violations": [],
            "complaints": [],
        }
        parcels.append(record)
        # Last-write-wins on duplicate addresses (rare, but condos exist)
        by_addr[normalized] = record
        # Also index by no-type key so violations like "216 LANDON ST" find
        # parcels recorded as "216 LANDON". Don't overwrite an existing exact key.
        stripped = _strip_trailing_type(normalized)
        if stripped != normalized and stripped not in by_addr:
            by_addr[stripped] = record

    return parcels, by_addr


def _join_violations(by_addr: dict[str, dict], violations: list[dict]) -> int:
    matched = 0
    for v in violations:
        norm = normalize_address(v.get("address") or "")
        parcel = _index_lookup(by_addr, norm)
        if not parcel:
            continue
        matched += 1
        is_open = (v.get("status") or "").upper() == "ACTIVE"
        parcel["code_violations_total"] += 1
        if is_open:
            parcel["code_violations_open"] += 1
        date = _parse_date(v.get("date"))
        if date:
            prev = parcel["last_violation_date"]
            if prev is None or date.isoformat() > prev:
                parcel["last_violation_date"] = date.isoformat()
        # keep a slim record for the dossier
        parcel["violations"].append({
            "date": v.get("date"),
            "status": v.get("status"),
            "description": v.get("description"),
            "code_section": v.get("code_section"),
        })
    return matched


def _join_311(by_addr: dict[str, dict], requests_311: list[dict]) -> tuple[int, str]:
    """Match each 311 record to a parcel by normalized address.

    The dataset's "last 12 months" window is computed relative to the dataset's
    max open_date — not today — because the source feed stopped refreshing
    in 2024-05. Returns (matched_count, max_date_iso) so the meta record can
    disclose freshness.
    """
    # Pre-pass: find the dataset's max date to anchor the 12-month window
    max_date = ""
    for r in requests_311:
        d = r.get("open_date") or ""
        if d > max_date:
            max_date = d
    if max_date:
        anchor = datetime.fromisoformat(max_date.replace("Z", "+00:00"))
        cutoff_iso = (anchor - timedelta(days=365)).isoformat()[:19]
    else:
        cutoff_iso = ""

    matched = 0
    for r in requests_311:
        # All rows are housing-related by API filter; no client-side filter.
        num = r.get("address_number") or ""
        line = r.get("address_line_1") or ""
        full = f"{num} {line}".strip() if num else line
        norm = normalize_address(full)
        parcel = _index_lookup(by_addr, norm)
        if not parcel:
            continue
        opened = r.get("open_date") or ""
        if cutoff_iso and opened and opened >= cutoff_iso:
            parcel["complaints_311_12mo"] += 1
            matched += 1
        parcel["complaints"].append({
            "date": opened,
            "subject": r.get("subject"),
            "reason": r.get("reason"),
            "type": r.get("type"),
        })
    return matched, max_date


def _join_demolitions(by_addr: dict[str, dict], demos: list[dict]) -> int:
    matched = 0
    for d in demos:
        # Permits dataset: stname + (no street number? sample had stname='216 LANDON' style? probe says stname)
        # Permits sample includes apno, stname, sbl. stname may be just street name.
        # Try several reconstructions.
        parts = [d.get(k) for k in ("apno",)]  # placeholders to avoid lint
        full = (d.get("stname") or "").strip()
        norm = normalize_address(full)
        parcel = _index_lookup(by_addr, norm)
        if parcel:
            parcel["demolished"] = True
            matched += 1
    return matched


def _compute_concern_score(p: dict) -> int:
    return (
        2 * p["code_violations_open"]
        + 1 * p["complaints_311_12mo"]
        + (5 if p["demolished"] else 0)
    )


def join_all() -> dict:
    print("Loading parcels...", file=sys.stderr)
    parcels_geo = _load_json(RAW / "parcels.geojson")
    parcels, by_addr = _build_parcel_records(parcels_geo)
    print(f"  built {len(parcels):,} parcel records", file=sys.stderr)

    print("Joining code violations...", file=sys.stderr)
    violations = _load_json(RAW / "code_violations.json")
    v_matched = _join_violations(by_addr, violations)
    print(f"  matched {v_matched:,}/{len(violations):,}", file=sys.stderr)

    print("Joining 311 housing complaints...", file=sys.stderr)
    requests_311 = _load_json(RAW / "service_requests_311.json")
    c_matched, c_max_date = _join_311(by_addr, requests_311)
    print(f"  matched {c_matched:,}/{len(requests_311):,} (max date {c_max_date[:10]})", file=sys.stderr)

    print("Joining demolitions...", file=sys.stderr)
    demos = _load_json(RAW / "demolitions.json")
    d_matched = _join_demolitions(by_addr, demos)
    print(f"  matched {d_matched:,}/{len(demos):,}", file=sys.stderr)

    # Trim per-parcel slim lists to most recent 25 to bound JSON size
    for p in parcels:
        p["violations"] = sorted(
            p["violations"], key=lambda x: x.get("date") or "", reverse=True
        )[:25]
        p["complaints"] = sorted(
            p["complaints"], key=lambda x: x.get("date") or "", reverse=True
        )[:25]
        p["concern_score"] = _compute_concern_score(p)

    # Build owners index
    owners: dict[str, list[str]] = defaultdict(list)
    for p in parcels:
        if p["owner_norm"]:
            owners[p["owner_norm"]].append(p["parcel_id"])

    # Sanity: print top 10 owners by property count
    top = sorted(owners.items(), key=lambda kv: -len(kv[1]))[:10]
    print("\nTop 10 owners by property count (sanity check):", file=sys.stderr)
    for name, ids in top:
        print(f"  {len(ids):5d}  {name}", file=sys.stderr)

    # Compute meta
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parcels": len(parcels),
        "violations_total": len(violations),
        "violations_matched": v_matched,
        "complaints_311_total": len(requests_311),
        "complaints_311_matched": c_matched,
        "complaints_311_max_date": c_max_date,
        "demolitions_total": len(demos),
        "demolitions_matched": d_matched,
        "owners": len(owners),
    }

    return {"parcels": parcels, "owners": dict(owners), "meta": meta}


if __name__ == "__main__":
    join_all()
