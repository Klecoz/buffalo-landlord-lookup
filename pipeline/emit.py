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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cluster_score import (
    address_kind_from_key,
    classify_cluster,
    cohesion_details,
    dedup_persons_in_cluster,
)
from co_owner import parse_co_owner, suppress_common_names
from normalize import normalize_mail_address

HERE = Path(__file__).resolve().parent
WEB_DATA = HERE.parent / "web" / "data"
OWNERS_DIR = WEB_DATA / "owners"
OPERATORS_DIR = WEB_DATA / "operators"

# Operator clustering tunables — see docs/superpowers/specs/2026-05-06-llc-unmasking-design.md
# The flat owner-count cap is now handled inside cluster_score.classify_cluster,
# which uses cohesion + address-kind to decide. We still enforce a minimum size
# below to avoid emitting trivial 2-LLC clusters that aren't meaningful.
MIN_CLUSTER_OWNERS = 2           # need at least N distinct LLCs to be a cluster
MIN_CLUSTER_PARCELS = 3          # and at least N total parcels across them


def _slugify(name: str) -> str:
    """Normalized owner string -> filesystem-safe slug."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unknown"


def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(path)


# Public/government owners that dominate a raw "most properties" list and
# aren't useful as a slumlord-leaderboard signal. Match against the
# *normalized* owner name. Substring (in) for org variants, equality for
# placeholders.
_LEADERBOARD_SKIP_SUBSTRINGS = (
    # Government — city/state/county/federal
    "city of buffalo",
    "city buffalo",
    "city of bflo",
    "city bflo",
    "buffalo municipal",
    "buffalo public school",
    "buffalo board of education",
    "state of new york",
    "state new york",
    "state of ny",
    "state ny ",                        # "state ny dept" etc.
    "state university",                # SUNY: "State University Of New York"
    "state teachers",                   # State Teachers College
    "people of the state",              # "People Of The State Of NY"
    "people of new york",
    "county of erie",
    "erie county",
    "united states of america",
    "u s a",
    "u s government",
    "u s postal",
    # Quasi-public agencies & authorities
    "buffalo urban renewal",
    "empire state development",
    "dormitory authority",
    "n f t a",                         # Niagara Frontier Transportation Authority
    "nfta",
    "industrial development agency",
    "housing authority",
    # Utilities
    "niagara mohawk",
    "national grid",
    "verizon new york",
    # Major nonprofit / institutional owners that aren't landlords
    "kaleida health",
    "catholic health",
    "mercy hospital",
    "roswell park",
    "veterans of",
    "diocese of buffalo",
    "salvation army",
    "habitat for humanity",
    "ywca",
    "ymca",
    "young men s christian",
    "young women s christian",
    # Universities/colleges (mostly institutional, not landlord)
    "canisius college",
    "canisius university",
    "d youville",
    "medaille college",
    "medaille university",
    "buffalo state college",
)
_LEADERBOARD_SKIP_EXACT = {"owner of record", "unknown", ""}


def _is_skipped_owner(owner_norm: str) -> bool:
    if owner_norm in _LEADERBOARD_SKIP_EXACT:
        return True
    return any(s in owner_norm for s in _LEADERBOARD_SKIP_SUBSTRINGS)


def _slugify_unique(label: str, used: set[str]) -> str:
    base = _slugify(label)
    slug = base
    i = 2
    while slug in used:
        slug = f"{base}-{i}"
        i += 1
    used.add(slug)
    return slug


def _build_operator_clusters(
    by_owner: dict[str, dict],
) -> tuple[dict[str, dict], dict[str, str], dict[str, int]]:
    """Cluster owners by their primary mailing address.

    Args:
        by_owner: owner_norm -> {
            "slug": str, "display": str,
            "mail_keys": Counter[mail_key],   # tally across non-self-mail parcels
            "properties": int, "open": int, "all_violations": int,
            "complaints_311_12mo": int,
            "props": list[dict],              # parcel records for the operator portfolio
        }

    Returns:
        (clusters, owner_to_operator, counts)
        clusters: operator_slug -> { mailing_address, owners[], totals, properties[],
                                     confidence, evidence, owner_groups[] }
        owner_to_operator: owner_norm -> operator_slug
        counts: {high, medium, low, dropped} — confidence histogram for meta.json
    """
    # Step 1 — pick each owner's PRIMARY mail key (most common across their non-self-mail parcels)
    primary_mail: dict[str, str] = {}
    for owner_norm, agg in by_owner.items():
        keys = agg["mail_keys"]
        if not keys:
            continue
        # Counter.most_common ties broken by insertion order; sort key alphabetically for determinism.
        top_count = max(keys.values())
        candidates = sorted(k for k, c in keys.items() if c == top_count)
        primary_mail[owner_norm] = candidates[0]

    # Step 2 — group owners by mailing key
    by_mail: dict[str, list[str]] = defaultdict(list)
    for owner_norm, key in primary_mail.items():
        if key:
            by_mail[key].append(owner_norm)

    # Step 3 — apply rules
    clusters: dict[str, dict] = {}
    owner_to_operator: dict[str, str] = {}
    used_slugs: set[str] = set()
    counts = {"high": 0, "medium": 0, "low": 0, "dropped": 0}

    for mail_key, owner_norms in by_mail.items():
        # Inherit the leaderboard skip-list at the cluster level.
        if any(_is_skipped_owner(o) for o in owner_norms):
            continue
        # Meaningful size.
        if len(owner_norms) < MIN_CLUSTER_OWNERS:
            continue
        total_parcels = sum(by_owner[o]["properties"] for o in owner_norms)
        if total_parcels < MIN_CLUSTER_PARCELS:
            continue

        # Cohesion-based classification — see cluster_score.py.
        owner_displays = [by_owner[o]["display"] for o in owner_norms]
        addr_kind = address_kind_from_key(mail_key)
        verdict = classify_cluster(owner_displays, addr_kind)
        if verdict["action"] == "drop":
            counts["dropped"] += 1
            continue
        counts[verdict["confidence"]] += 1

        # Build cluster.
        sorted_owners = sorted(owner_norms, key=lambda o: -by_owner[o]["properties"])
        primary_label = by_owner[sorted_owners[0]]["display"]
        suffix = f" (+{len(sorted_owners)-1} more LLC{'s' if len(sorted_owners) > 2 else ''})"
        operator_label = primary_label + suffix

        slug = _slugify_unique(primary_label, used_slugs)

        owners_block = []
        all_props: list[dict] = []
        totals = {"properties": 0, "open": 0, "all_violations": 0, "complaints_311_12mo": 0, "total_value": 0}
        for o in sorted_owners:
            agg = by_owner[o]
            owners_block.append({
                "slug": agg["slug"],
                "display": agg["display"],
                "properties": agg["properties"],
                "open": agg["open"],
                "all_violations": agg["all_violations"],
                "complaints_311_12mo": agg["complaints_311_12mo"],
                "total_value": agg["total_value"],
            })
            all_props.extend(agg["props"])
            for k in totals:
                totals[k] += agg[k]
            owner_to_operator[o] = slug

        # Co-owner aggregation across this cluster's member owners.
        # Sums per-key parcel counts and picks the most-common display
        # variant for each key (across all members).
        cluster_co_owner_counts: Counter[frozenset] = Counter()
        cluster_co_owner_display_counts: dict[frozenset, Counter[str]] = defaultdict(Counter)
        for o in sorted_owners:
            agg = by_owner[o]
            for k, c in agg.get("co_owner_counts", Counter()).items():
                cluster_co_owner_counts[k] += c
                # Vote with parcel count for the canonical display variant
                cluster_co_owner_display_counts[k][agg["co_owner_displays"][k]] += c
        cluster_co_owner_displays = {
            k: cnt.most_common(1)[0][0]
            for k, cnt in cluster_co_owner_display_counts.items()
        }

        # Person-name dedup within the cluster (safe: shared mailing address
        # corroborates the merge; cross-cluster matches still stay separate).
        owner_groups = dedup_persons_in_cluster(owners_block)

        # Structured audit block — the UI reads this to render the
        # "How these names are grouped" disclosure. All fields here are
        # re-shapings of data already on the cluster; no new heuristics.
        cohesion = cohesion_details(owner_displays)
        person_dedups = [
            {"canonical": g["canonical"], "variants": g["variants"]}
            for g in owner_groups
            if g.get("variants")
        ]
        audit = {
            "shared_mailing_address": mail_key,
            "address_kind": addr_kind,
            "member_count": len(owner_norms),
            "cohesion": {
                "score": round(cohesion["score"], 3),
                "distinctive_token": cohesion["distinctive_token"],
                "explanation": cohesion["explanation"],
            },
            "pattern": verdict.get("pattern"),
            "person_dedups": person_dedups,
            "co_owners": [],          # filled in post-pass below
            "linked_operators": [],   # filled in post-pass below
        }

        clusters[slug] = {
            "operator_slug": slug,
            "operator_label": operator_label,
            "mailing_address": mail_key,
            "confidence": verdict["confidence"],
            "evidence": verdict["evidence"],
            "audit": audit,
            "owners": owners_block,
            "owner_groups": owner_groups,
            "total_properties": totals["properties"],
            "total_open_violations": totals["open"],
            "total_all_violations": totals["all_violations"],
            "total_complaints_311_12mo": totals["complaints_311_12mo"],
            "total_value": totals["total_value"],
            "properties": sorted(all_props, key=lambda p: -p["concern_score"]),
        }
        clusters[slug]["_co_owner_counts"] = cluster_co_owner_counts
        clusters[slug]["_co_owner_displays"] = cluster_co_owner_displays

    # ---- Co-owner cross-cluster post-pass ---------------------------------
    # Build a global index of co_owner_key → [(operator_slug, parcels)],
    # apply common-name suppression for the link surface, and attach
    # `co_owners` + `linked_operators` to each cluster's audit block.

    # Step A — global key-to-operators index
    co_owner_to_operators: dict[frozenset, list[tuple[str, int]]] = defaultdict(list)
    for slug, cluster in clusters.items():
        for k, count in cluster["_co_owner_counts"].items():
            co_owner_to_operators[k].append((slug, count))

    # Step B — apply suppression: keys appearing in too many distinct
    # operators are noise for the link surface (kept as raw evidence).
    linkable_index = suppress_common_names(co_owner_to_operators)

    # Step C — fill per-cluster audit fields
    CO_OWNERS_TOP_N = 10
    LINKED_OPS_TOP_N = 10
    for slug, cluster in clusters.items():
        co_counts = cluster["_co_owner_counts"]
        co_displays = cluster["_co_owner_displays"]
        co_owners = sorted(
            (
                {"name": co_displays[k], "parcels": c}
                for k, c in co_counts.items()
            ),
            key=lambda d: -d["parcels"],
        )[:CO_OWNERS_TOP_N]

        link_rows: list[dict] = []
        for k in co_counts:
            if k not in linkable_index:
                continue
            for other_slug, parcels in linkable_index[k]:
                if other_slug == slug:
                    continue
                link_rows.append({
                    "co_owner": co_displays[k],
                    "operator_slug": other_slug,
                    "operator_label": clusters[other_slug]["operator_label"],
                    "parcels": parcels,
                })
        link_rows.sort(key=lambda d: -d["parcels"])
        link_rows = link_rows[:LINKED_OPS_TOP_N]

        cluster["audit"]["co_owners"] = co_owners
        cluster["audit"]["linked_operators"] = link_rows

        # Strip transient fields so they don't end up in emitted JSON.
        del cluster["_co_owner_counts"]
        del cluster["_co_owner_displays"]

    return clusters, owner_to_operator, counts


def emit(joined: dict) -> dict[str, Path]:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    OWNERS_DIR.mkdir(parents=True, exist_ok=True)
    OPERATORS_DIR.mkdir(parents=True, exist_ok=True)

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
    # owners/<slug>.json — aggregates first, geojson + files emitted after
    # operator clustering so each artifact carries operator_slug.
    # ------------------------------------------------------------------
    print(f"Aggregating {len(owners):,} owners...", file=sys.stderr)
    # First pass: build per-owner aggregates AND collect each owner's mailing-address
    # tally. We need this completed BEFORE we can compute operator clusters and write
    # owner files (because owner files include their operator_slug).
    by_owner: dict[str, dict] = {}
    for owner_norm, parcel_ids in owners.items():
        slug = owner_slugs[owner_norm]
        props = []
        owner_displays: dict[str, int] = {}
        mail_keys: Counter[str] = Counter()
        portfolio_violations = 0
        portfolio_open_violations = 0
        portfolio_complaints_311 = 0
        portfolio_value = 0
        oldest_violation = None
        # Co-owner aggregation: every parcel's ADD_OWNER, parsed to a stable
        # key. Same human under different spellings collapses to one entry.
        co_owner_counts: Counter[frozenset] = Counter()
        co_owner_display_counts: dict[frozenset, Counter[str]] = defaultdict(Counter)
        for pid in parcel_ids:
            parcel = by_id.get(pid)
            if not parcel:
                continue
            owner_displays[parcel["owner_raw"]] = owner_displays.get(parcel["owner_raw"], 0) + 1
            portfolio_violations += parcel["code_violations_total"]
            portfolio_open_violations += parcel["code_violations_open"]
            portfolio_complaints_311 += parcel["complaints_311_12mo"]
            portfolio_value += parcel.get("full_market_val", 0) or 0
            if parcel["last_violation_date"]:
                if oldest_violation is None or parcel["last_violation_date"] < oldest_violation:
                    oldest_violation = parcel["last_violation_date"]
            # Mailing-address tally — only if NOT owner-occupied.
            if not parcel.get("is_self_mail"):
                mk = normalize_mail_address(
                    parcel.get("mail_addr"), parcel.get("mail_city"),
                    parcel.get("mail_state"), parcel.get("mail_zip"),
                    parcel.get("po_box"),
                )
                if mk:
                    mail_keys[mk] += 1
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
                "value": parcel.get("full_market_val", 0) or 0,
            })
            parsed = parse_co_owner(parcel.get("add_owner") or "")
            if parsed is not None:
                co_owner_counts[parsed["key"]] += 1
                co_owner_display_counts[parsed["key"]][parsed["display"]] += 1

        # Pick the most-common display variant for each co-owner key.
        co_owner_displays = {
            k: cnt.most_common(1)[0][0]
            for k, cnt in co_owner_display_counts.items()
        }

        display = max(owner_displays.items(), key=lambda kv: kv[1])[0] if owner_displays else owner_norm

        by_owner[owner_norm] = {
            "slug": slug,
            "display": display,
            "variants": list(owner_displays.keys()),
            "mail_keys": mail_keys,
            "properties": len(props),
            "open": portfolio_open_violations,
            "all_violations": portfolio_violations,
            "complaints_311_12mo": portfolio_complaints_311,
            "total_value": portfolio_value,
            "oldest_violation": oldest_violation,
            "props": sorted(props, key=lambda x: -x["concern_score"]),
            "co_owner_counts": co_owner_counts,
            "co_owner_displays": co_owner_displays,
        }

    # Build operator clusters BEFORE writing owner files so each owner gets its operator_slug.
    print("Clustering operators by mailing address...", file=sys.stderr)
    clusters, owner_to_operator, cluster_counts = _build_operator_clusters(by_owner)
    print(
        f"  {len(clusters):,} operator clusters formed "
        f"(high={cluster_counts['high']}, medium={cluster_counts['medium']}, "
        f"low={cluster_counts['low']}, dropped={cluster_counts['dropped']})",
        file=sys.stderr,
    )

    # ------------------------------------------------------------------
    # properties.geojson — emitted now so each feature carries operator_slug
    # for the map-filter feature.
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
                "operator_slug": owner_to_operator.get(p["owner_norm"]),
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

    # Now write owner files (with operator_slug) and collect ranking aggregates.
    print(f"Emitting {len(owners):,} owner portfolios...", file=sys.stderr)
    owner_aggregates: list[dict] = []
    for owner_norm, agg in by_owner.items():
        operator_slug = owner_to_operator.get(owner_norm)
        operator_confidence = (
            clusters[operator_slug]["confidence"] if operator_slug else None
        )
        _atomic_write(OWNERS_DIR / f"{agg['slug']}.json", {
            "owner_norm": owner_norm,
            "owner_display": agg["display"],
            "owner_variants": agg["variants"],
            "total_properties": agg["properties"],
            "total_violations": agg["all_violations"],
            "total_value": agg["total_value"],
            "oldest_violation": agg["oldest_violation"],
            "operator_slug": operator_slug,
            "operator_confidence": operator_confidence,
            "properties": agg["props"],
        })
        owner_aggregates.append({
            "slug": agg["slug"],
            "display": agg["display"],
            "owner_norm": owner_norm,
            "properties": agg["properties"],
            "open": agg["open"],
            "all_violations": agg["all_violations"],
            "complaints_311_12mo": agg["complaints_311_12mo"],
            "total_value": agg["total_value"],
        })

    # Write operator files.
    print(f"Emitting {len(clusters):,} operator portfolios...", file=sys.stderr)
    for slug, cluster in clusters.items():
        _atomic_write(OPERATORS_DIR / f"{slug}.json", cluster)

    # ------------------------------------------------------------------
    # top_owners.json — leaderboards
    # ------------------------------------------------------------------
    print("Emitting top_owners.json...", file=sys.stderr)
    eligible = [o for o in owner_aggregates if not _is_skipped_owner(o["owner_norm"])]

    def _top(key: str, n: int = 20) -> list[dict]:
        ranked = sorted(eligible, key=lambda o: -o[key])
        return [
            {k: o[k] for k in ("slug", "display", "properties", "open", "all_violations", "complaints_311_12mo", "total_value")}
            for o in ranked[:n] if o[key] > 0
        ]

    _atomic_write(WEB_DATA / "top_owners.json", {
        "by_properties": _top("properties"),
        "by_open_violations": _top("open"),
        "by_all_violations": _top("all_violations"),
        "by_complaints_311": _top("complaints_311_12mo"),
        "by_value": _top("total_value"),
    })

    # ------------------------------------------------------------------
    # top_operators.json — operator leaderboard
    # ------------------------------------------------------------------
    print("Emitting top_operators.json...", file=sys.stderr)
    op_aggs = [
        {
            "slug": c["operator_slug"],
            "label": c["operator_label"],
            "mailing_address": c["mailing_address"],
            "confidence": c["confidence"],
            "evidence": c["evidence"],
            "owners_n": len(c["owners"]),
            "properties": c["total_properties"],
            "open": c["total_open_violations"],
            "all_violations": c["total_all_violations"],
            "complaints_311_12mo": c["total_complaints_311_12mo"],
            "total_value": c["total_value"],
        }
        for c in clusters.values()
    ]

    def _top_op(key: str, n: int = 20) -> list[dict]:
        ranked = sorted(op_aggs, key=lambda o: -o[key])
        return [o for o in ranked[:n] if o[key] > 0]

    _atomic_write(WEB_DATA / "top_operators.json", {
        "by_properties": _top_op("properties"),
        "by_open_violations": _top_op("open"),
        "by_all_violations": _top_op("all_violations"),
        "by_complaints_311": _top_op("complaints_311_12mo"),
        "by_value": _top_op("total_value"),
    })

    # Sanity: top 5 operators by property count
    if clusters:
        top_clusters = sorted(clusters.values(), key=lambda c: -c["total_properties"])[:5]
        print("\nTop 5 operators by property count (sanity check):", file=sys.stderr)
        for c in top_clusters:
            print(f"  {c['total_properties']:5d}  {c['operator_label']:60s}  @ {c['mailing_address']}", file=sys.stderr)

    # ------------------------------------------------------------------
    # address_index.json — small list for client-side search
    # ------------------------------------------------------------------
    print("Emitting address_index.json...", file=sys.stderr)
    index = [
        {
            "addr": p["address"],
            "id": p["parcel_id"],
            "lat": p["lat"],
            "lng": p["lng"],
            "owner_slug": owner_slugs.get(p["owner_norm"]),
        }
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
    meta = dict(meta)  # don't mutate caller's dict
    meta["clusters"] = cluster_counts
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
