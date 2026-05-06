"""Emit static artifacts for the frontend.

Writes to ../web/data/:
  properties.geojson      — every parcel + rolled-up stats (map source)
  owners/<slug>.json      — per-owner portfolio, lazy-loaded on click
  address_index.json      — list of {addr, parcel_id} for autocomplete search
  meta.json               — refresh date, row counts, skip counts

Per-owner files keep the initial page payload small. The full owners
dictionary is replaced by an `owner_slug` field on each parcel that
points to the right portfolio file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WEB_DATA = HERE.parent / "web" / "data"
OWNERS_DIR = WEB_DATA / "owners"


def _slugify(name: str) -> str:
    """Normalized owner string -> filesystem-safe slug."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unknown"


def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(path)


def emit(joined: dict) -> dict[str, Path]:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    OWNERS_DIR.mkdir(parents=True, exist_ok=True)

    parcels = joined["parcels"]
    owners = joined["owners"]
    meta = joined["meta"]

    # Resolve owner -> slug, attach to each parcel
    owner_slugs: dict[str, str] = {}
    used: set[str] = set()
    for owner_norm in owners:
        base = _slugify(owner_norm)
        slug = base
        i = 2
        while slug in used:
            slug = f"{base}-{i}"
            i += 1
        used.add(slug)
        owner_slugs[owner_norm] = slug

    # Build a flat map parcel_id -> parcel (for owner files)
    by_id: dict[Any, dict] = {p["parcel_id"]: p for p in parcels if p["parcel_id"]}

    # ------------------------------------------------------------------
    # properties.geojson
    # ------------------------------------------------------------------
    print("Emitting properties.geojson...", file=sys.stderr)
    features = []
    for p in parcels:
        if not p.get("geometry"):
            continue
        slug = owner_slugs.get(p["owner_norm"], "")
        portfolio_size = len(owners.get(p["owner_norm"], []))
        features.append({
            "type": "Feature",
            "geometry": p["geometry"],
            "properties": {
                "id": p["parcel_id"],
                "addr": p["address"],
                "owner": p["owner_raw"],
                "owner_slug": slug,
                "portfolio_n": portfolio_size,
                "violations_open": p["code_violations_open"],
                "violations_total": p["code_violations_total"],
                "complaints_311_12mo": p["complaints_311_12mo"],
                "demolished": p["demolished"],
                "concern_score": p["concern_score"],
                "last_violation": p["last_violation_date"],
            },
        })
    _atomic_write(WEB_DATA / "properties.geojson", {
        "type": "FeatureCollection",
        "features": features,
    })

    # ------------------------------------------------------------------
    # owners/<slug>.json
    # ------------------------------------------------------------------
    print(f"Emitting {len(owners):,} owner portfolios...", file=sys.stderr)
    for owner_norm, parcel_ids in owners.items():
        slug = owner_slugs[owner_norm]
        props = []
        owner_displays: dict[str, int] = {}
        portfolio_violations = 0
        oldest_violation = None
        for pid in parcel_ids:
            parcel = by_id.get(pid)
            if not parcel:
                continue
            owner_displays[parcel["owner_raw"]] = owner_displays.get(parcel["owner_raw"], 0) + 1
            portfolio_violations += parcel["code_violations_total"]
            if parcel["last_violation_date"]:
                if oldest_violation is None or parcel["last_violation_date"] < oldest_violation:
                    oldest_violation = parcel["last_violation_date"]
            props.append({
                "id": parcel["parcel_id"],
                "addr": parcel["address"],
                "lat": parcel["lat"],
                "lng": parcel["lng"],
                "violations_open": parcel["code_violations_open"],
                "violations_total": parcel["code_violations_total"],
                "complaints_311_12mo": parcel["complaints_311_12mo"],
                "demolished": parcel["demolished"],
                "concern_score": parcel["concern_score"],
            })

        # Pick the most-frequent display variant of the owner name as the canonical
        display = max(owner_displays.items(), key=lambda kv: kv[1])[0] if owner_displays else owner_norm

        _atomic_write(OWNERS_DIR / f"{slug}.json", {
            "owner_norm": owner_norm,
            "owner_display": display,
            "owner_variants": list(owner_displays.keys()),
            "total_properties": len(props),
            "total_violations": portfolio_violations,
            "oldest_violation": oldest_violation,
            "properties": sorted(props, key=lambda x: -x["concern_score"]),
        })

    # ------------------------------------------------------------------
    # address_index.json — small list for client-side search
    # ------------------------------------------------------------------
    print("Emitting address_index.json...", file=sys.stderr)
    index = [
        {"addr": p["address"], "id": p["parcel_id"]}
        for p in parcels if p["address"] and p["parcel_id"]
    ]
    index.sort(key=lambda x: x["addr"])
    _atomic_write(WEB_DATA / "address_index.json", index)

    # ------------------------------------------------------------------
    # parcels/<id>.json — per-parcel dossier with violation/complaint detail
    # (Avoid: too many files for filesystem; instead one consolidated dossier
    # file is overkill in size. Compromise: ship dossier_records.json keyed
    # by parcel id, lazy-loaded once on demand.)
    # ------------------------------------------------------------------
    print("Emitting dossiers.json...", file=sys.stderr)
    dossiers = {}
    for p in parcels:
        # Only ship dossiers for parcels with any signal — saves space
        if (p["code_violations_total"] or p["complaints_311_12mo"] or p["demolished"]):
            dossiers[p["parcel_id"]] = {
                "violations": p["violations"],
                "complaints": p["complaints"],
            }
    _atomic_write(WEB_DATA / "dossiers.json", dossiers)

    # ------------------------------------------------------------------
    # meta.json
    # ------------------------------------------------------------------
    print("Emitting meta.json...", file=sys.stderr)
    _atomic_write(WEB_DATA / "meta.json", meta)

    return {
        "properties": WEB_DATA / "properties.geojson",
        "owners_dir": OWNERS_DIR,
        "address_index": WEB_DATA / "address_index.json",
        "meta": WEB_DATA / "meta.json",
        "dossiers": WEB_DATA / "dossiers.json",
    }


if __name__ == "__main__":
    from join import join_all
    emit(join_all())
