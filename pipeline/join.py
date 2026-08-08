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
  - Demolitions      -> parcel by permit SBL, then normalized address;
                        a permit only reads as "demolished" when the
                        assessment roll also shows an empty lot

We deliberately do not implement a true geospatial fallback for v1: the
address coverage is good enough that the residual is small, and the
build stays dependency-light. A future pass can add nearest-parcel
matching for orphans.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
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

        # Mailing fields, used downstream for operator clustering.
        mail_addr_raw = (props.get("MAIL_ADDR") or "").strip()
        mail_city = (props.get("MAIL_CITY") or "").strip()
        mail_state = (props.get("MAIL_STATE") or "").strip()
        mail_zip = (props.get("MAIL_ZIP") or "").strip()
        po_box = (props.get("PO_BOX") or "").strip()
        # Self-mail = owner-occupied. Compare normalized strings to avoid
        # casing/abbreviation false negatives.
        is_self_mail = bool(
            mail_addr_raw and normalized and
            normalize_address(mail_addr_raw) == normalized
        )

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
            "add_owner": (props.get("ADD_OWNER") or "").strip(),
            "mail_addr": mail_addr_raw,
            "mail_city": mail_city,
            "mail_state": mail_state,
            "mail_zip": mail_zip,
            "po_box": po_box,
            "is_self_mail": is_self_mail,
            "prop_class": props.get("PROP_CLASS"),
            "year_built": props.get("YR_BLT"),
            "full_market_val": int(props.get("FULL_MARKET_VAL") or 0),
            # Assessment figures — used to corroborate demolition permits.
            "land_av": int(props.get("LAND_AV") or 0),
            "total_av": int(props.get("TOTAL_AV") or 0),
            "geometry": geom,
            # to be filled below
            "code_violations_open": 0,
            "code_violations_total": 0,
            "complaints_311_12mo": 0,
            "demolished": False,
            "demo_permit": None,
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


def _join_violations(by_addr: dict[str, dict], violations: list[dict]) -> tuple[int, str]:
    """Match violations to parcels by normalized address.

    Returns (matched_count, max_date_iso). max_date is the freshest
    `date` field observed across all violations (matched or not), so the
    UI can render a freshness pill on the violations panel.
    """
    matched = 0
    max_date_iso = ""
    for v in violations:
        date = _parse_date(v.get("date"))
        if date and date.isoformat() > max_date_iso:
            max_date_iso = date.isoformat()
        norm = normalize_address(v.get("address") or "")
        parcel = _index_lookup(by_addr, norm)
        if not parcel:
            continue
        matched += 1
        is_open = (v.get("status") or "").upper() == "ACTIVE"
        parcel["code_violations_total"] += 1
        if is_open:
            parcel["code_violations_open"] += 1
        if date:
            prev = parcel["last_violation_date"]
            if prev is None or date.isoformat() > prev:
                parcel["last_violation_date"] = date.isoformat()
        parcel["violations"].append({
            "date": v.get("date"),
            "status": v.get("status"),
            "description": v.get("description"),
            "code_section": v.get("code_section"),
        })
    return matched, max_date_iso


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
        # Calendar-year-back so "last 12 months" is inclusive of the same day
        # last year (e.g., 2024-05-10 -> 2023-05-10), independent of leap days.
        try:
            cutoff = anchor.replace(year=anchor.year - 1)
        except ValueError:
            # Anchor is Feb 29 in a leap year; fall back to Feb 28.
            cutoff = anchor.replace(year=anchor.year - 1, day=28)
        cutoff_iso = cutoff.isoformat()[:19]
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


def _parcel_reads_vacant(p: dict) -> bool:
    """Does the current assessment roll describe an empty lot?

    Two independent signals, either of which is enough:
      - PROP_CLASS 3xx is the NYS code for vacant land.
      - The improvement is worth nothing: total assessed value has fallen to
        (or below) the land-only value, i.e. the structure adds no value.

    The value test demands both figures be positive. A parcel with LAND_AV
    and TOTAL_AV both 0 is a roll record with no assessment at all — silence,
    not evidence of an empty lot — so it only counts as vacant if PROP_CLASS
    says so. (361 of 93,440 parcels are in that state.)
    """
    if (p.get("prop_class") or "").strip().startswith("3"):
        return True
    land_av = p.get("land_av") or 0
    total_av = p.get("total_av") or 0
    return land_av > 0 and total_av > 0 and total_av <= land_av


def _join_demolitions(
    parcels: list[dict], by_addr: dict[str, dict], demos: list[dict]
) -> dict:
    """Attach the latest demolition permit to each parcel, then decide which
    parcels actually read as demolished.

    A permit is an application to knock a building down, not proof that it
    came down: permits go back to 2000, get abandoned, and get superseded by
    rebuilds. So a permit alone sets `demo_permit`; `demolished` is only true
    when the current assessment roll also shows an empty lot.

    Matching prefers the permit's SBL over its address. Permit SBLs are 16
    chars; parcel SBLs carry a 4-digit sub-parcel suffix on top of that, so
    the permit key is right-padded with zeros. Address matching stays as a
    fallback for the ~200 permits with no usable SBL.

    Returns a stats dict for the meta record and the console summary.
    """
    by_sbl: dict[str, dict] = {}
    for p in parcels:
        sbl = (p.get("sbl") or "").strip()
        if sbl:
            by_sbl.setdefault(sbl, p)

    matched_sbl = matched_addr = disagreements = unmatched = 0
    max_issued = ""

    for d in demos:
        issued = (d.get("issued") or "")[:10]
        if issued > max_issued:
            max_issued = issued

        sbl = (d.get("sbl") or "").strip()
        sbl_parcel = None
        if len(sbl) >= 16:  # shorter values in this feed are junk, not SBLs
            sbl_parcel = by_sbl.get(sbl.ljust(20, "0")) or by_sbl.get(sbl)
        addr_parcel = _index_lookup(
            by_addr, normalize_address((d.get("stname") or "").strip())
        )

        if sbl_parcel is not None:
            parcel, via = sbl_parcel, "sbl"
            matched_sbl += 1
            if addr_parcel is not None and addr_parcel is not sbl_parcel:
                disagreements += 1
        elif addr_parcel is not None:
            parcel, via = addr_parcel, "address"
            matched_addr += 1
        else:
            unmatched += 1
            continue

        # Latest permit wins — a parcel demolished twice is really the story
        # of the most recent clearance.
        prev = parcel.get("demo_permit")
        if prev is None or issued > (prev.get("date") or ""):
            parcel["demo_permit"] = {"date": issued, "via": via}

    demolished = permit_not_vacant = 0
    for p in parcels:
        if not p.get("demo_permit"):
            continue
        if _parcel_reads_vacant(p):
            p["demolished"] = True
            demolished += 1
        else:
            permit_not_vacant += 1

    return {
        "matched": matched_sbl + matched_addr,
        "matched_sbl": matched_sbl,
        "matched_address": matched_addr,
        "sbl_address_disagreements": disagreements,
        "unmatched": unmatched,
        "demolished_parcels": demolished,
        "permit_but_not_vacant": permit_not_vacant,
        "max_issued": max_issued,
    }


# A demolition permit is a live concern signal only while it's recent: a lot
# cleared in 2004 is neighborhood history, not something the current owner is
# doing now. Five years, hardcoded on purpose — this is a judgment call about
# what "recent" means, not a knob worth configuring.
DEMO_SCORE_YEARS = 5


def _compute_concern_score(p: dict, today: date | None = None) -> int:
    if today is None:
        today = datetime.now(timezone.utc).date()

    demo_points = 0
    if p.get("demolished"):
        try:
            cutoff = today.replace(year=today.year - DEMO_SCORE_YEARS)
        except ValueError:  # today is Feb 29 and the target year isn't a leap year
            cutoff = today.replace(year=today.year - DEMO_SCORE_YEARS, day=28)
        issued = (p.get("demo_permit") or {}).get("date") or ""
        if issued >= cutoff.isoformat():
            demo_points = 5

    return (
        2 * p["code_violations_open"]
        + 1 * p["complaints_311_12mo"]
        + demo_points
    )


def join_all() -> dict:
    print("Loading parcels...", file=sys.stderr)
    parcels_geo = _load_json(RAW / "parcels.geojson")
    parcels, by_addr = _build_parcel_records(parcels_geo)
    print(f"  built {len(parcels):,} parcel records", file=sys.stderr)

    print("Joining code violations...", file=sys.stderr)
    violations = _load_json(RAW / "code_violations.json")
    v_matched, v_max_date = _join_violations(by_addr, violations)
    print(f"  matched {v_matched:,}/{len(violations):,}", file=sys.stderr)

    print("Joining 311 housing complaints...", file=sys.stderr)
    requests_311 = _load_json(RAW / "service_requests_311.json")
    c_matched, c_max_date = _join_311(by_addr, requests_311)
    print(f"  matched {c_matched:,}/{len(requests_311):,} (max date {c_max_date[:10]})", file=sys.stderr)

    print("Joining demolitions...", file=sys.stderr)
    demos = _load_json(RAW / "demolitions.json")
    d = _join_demolitions(parcels, by_addr, demos)
    print(
        f"  matched {d['matched']:,}/{len(demos):,} permits "
        f"({d['matched_sbl']:,} by SBL, {d['matched_address']:,} by address, "
        f"{d['sbl_address_disagreements']:,} where the two disagreed) -> "
        f"{d['demolished_parcels']:,} parcels demolished, "
        f"{d['permit_but_not_vacant']:,} with a permit but a standing building",
        file=sys.stderr,
    )

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
        "code_violations_max_date": v_max_date,
        "complaints_311_total": len(requests_311),
        "complaints_311_matched": c_matched,
        "complaints_311_max_date": c_max_date,
        "demolitions_total": len(demos),
        "demolitions_matched": d["matched"],
        "demolitions_max_date": d["max_issued"],
        "demolished_parcels": d["demolished_parcels"],
        "owners": len(owners),
    }

    return {"parcels": parcels, "owners": dict(owners), "meta": meta}


if __name__ == "__main__":
    join_all()
