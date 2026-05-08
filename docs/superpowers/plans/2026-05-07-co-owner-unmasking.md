# Co-owner Unmasking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface `ADD_OWNER` co-owners on parcels as cross-cluster identity evidence inside the existing operator-page audit disclosure — without auto-merging anything.

**Architecture:** A new `pipeline/co_owner.py` module parses raw `ADD_OWNER` strings into a `(key, display)` pair using existing helpers from `cluster_score.py`. Co-owner counts are aggregated per owner during the `by_owner` build (`emit.py`), then accumulated per cluster during cluster construction. A second pass after all clusters are built creates a global `co_owner_key → [operator]` index, applies a common-name suppression threshold, and attaches `co_owners` and `linked_operators` to each cluster's `audit` block. Frontend extends `renderAuditDisclosure` with two new sections.

**Tech Stack:** Python 3 + pytest (pipeline). Vanilla JS (frontend, no build step).

**Spec:** `docs/superpowers/specs/2026-05-07-co-owner-unmasking-design.md`

**Out of scope:** auto-merging on co-owner match, `ADD_MAIL_ADDR` clustering, demolition `applicant`, single-owner portfolio surfacing, project-wide overviews.

---

## File Structure

**Create:**
- `pipeline/co_owner.py` — co-owner parsing + linked-operator filtering. One responsibility: turn raw `ADD_OWNER` strings into stable keys, and decide which co-owners are "common-name noise" not worth linking on. Small, focused, easy to test.
- `pipeline/tests/test_co_owner.py` — unit tests for the new module.

**Modify:**
- `pipeline/join.py` — `_build_parcel_records` extracts `ADD_OWNER` into the parcel record as `add_owner`.
- `pipeline/emit.py` — aggregate per-owner co-owner counts in the `by_owner` pass; in `_build_operator_clusters`, accumulate to per-cluster counts; after all clusters are built, build a global index, apply suppression, attach `co_owners` and `linked_operators` to each cluster's `audit` block.
- `pipeline/tests/test_emit.py` — new tests for the cluster-level co-owner aggregation, common-name suppression, and cross-cluster linking.
- `web/app.js` — `renderAuditDisclosure` adds two new sections.

---

## Task 1: Carry `ADD_OWNER` into parcel records

**Why first:** Every downstream piece needs the field on the parcel. This is the smallest possible change to unlock the rest.

**Files:**
- Modify: `pipeline/join.py:154-200` (parcel record construction in `_build_parcel_records`)
- Test: `pipeline/tests/test_join.py`

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/test_join.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests/test_join.py -k add_owner -v
```

Expected: 2 failures with `KeyError: 'add_owner'`.

- [ ] **Step 3: Add `add_owner` to the parcel record**

In `pipeline/join.py`, find the `record = { ... }` dict literal in `_build_parcel_records` (around line 171). Insert a single line `"add_owner": (props.get("ADD_OWNER") or "").strip(),` immediately after the existing `"owner_norm": owner_norm,` line. The relevant portion becomes:

```python
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
            ...
```

- [ ] **Step 4: Run the join tests**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests/test_join.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add pipeline/join.py pipeline/tests/test_join.py
git commit -m "feat(pipeline): carry ADD_OWNER through to parcel records"
```

---

## Task 2: New `co_owner` module — parse and suppression

**Why a new module:** Co-owner indexing is a different concern from cohesion / person-dedup. Keeping it in its own module keeps `cluster_score.py` focused. Small, single-responsibility unit.

**Files:**
- Create: `pipeline/co_owner.py`
- Create: `pipeline/tests/test_co_owner.py`

- [ ] **Step 1: Write failing tests**

Create `pipeline/tests/test_co_owner.py`:

```python
"""Tests for co-owner parsing and link-noise suppression.

The co_owner module turns raw ADD_OWNER strings into stable keys so the
same human appearing under slightly different spellings on different
parcels collapses to one identity, and decides which co-owners are too
common to use as a cross-cluster link signal.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from co_owner import parse_co_owner, MAX_OPERATORS_PER_CO_OWNER, suppress_common_names


# --- parse_co_owner ------------------------------------------------------

def test_parse_comma_form():
    parsed = parse_co_owner("Smith, John A")
    assert parsed is not None
    assert parsed["key"] == frozenset({"SMITH", "JOHN"})
    assert parsed["display"] == "Smith, John A"


def test_parse_natural_order():
    parsed = parse_co_owner("John Smith")
    assert parsed is not None
    assert parsed["key"] == frozenset({"SMITH", "JOHN"})


def test_parse_normalizes_case_and_punctuation():
    """Same human in different spellings collapses to one key."""
    a = parse_co_owner("Smith, John A")
    b = parse_co_owner("SMITH, JOHN")
    c = parse_co_owner("John A Smith")
    assert a["key"] == b["key"] == c["key"]


def test_parse_skips_llc_like_values():
    """A business entity in ADD_OWNER is not a person — we don't key it."""
    assert parse_co_owner("Smith Holdings LLC") is None
    assert parse_co_owner("ACME PROPERTIES INC") is None


def test_parse_skips_single_token_garbage():
    """A one-token name (or empty string) can't be person-matched safely."""
    assert parse_co_owner("Kelley") is None
    assert parse_co_owner("") is None
    assert parse_co_owner("   ") is None


def test_parse_handles_hyphenated_lastname():
    """A hyphenated last name keeps as a single token."""
    parsed = parse_co_owner("Jackson-Molenda, Karen")
    assert parsed is not None
    # First+last set; first token of last_part = "Jackson-Molenda"
    # _person_signature splits on whitespace, so the hyphen stays.
    assert "KAREN" in parsed["key"]


# --- suppress_common_names ----------------------------------------------

def test_suppress_filters_common_names():
    """A co-owner key appearing in many distinct operators is suppressed
    from the cross-cluster link surface."""
    # Build an index with one rare and one common co-owner.
    rare_key = frozenset({"DOE", "JANE"})
    common_key = frozenset({"SMITH", "JOHN"})
    index = {
        rare_key: ["op-a", "op-b"],
        common_key: [f"op-{i}" for i in range(MAX_OPERATORS_PER_CO_OWNER + 1)],
    }
    filtered = suppress_common_names(index)
    assert rare_key in filtered
    assert common_key not in filtered


def test_suppress_keeps_at_threshold():
    """At exactly MAX_OPERATORS_PER_CO_OWNER appearances, still considered link-worthy."""
    key = frozenset({"DOE", "JANE"})
    index = {key: [f"op-{i}" for i in range(MAX_OPERATORS_PER_CO_OWNER)]}
    filtered = suppress_common_names(index)
    assert key in filtered
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests/test_co_owner.py -v
```

Expected: import errors — `co_owner` module does not exist.

- [ ] **Step 3: Create the module**

Create `pipeline/co_owner.py`:

```python
"""Parse ADD_OWNER strings into stable co-owner keys, and decide which
keys are too common to be useful cross-cluster link evidence.

Reuses _person_signature and _is_llc_like from cluster_score.py — same
human-name handling we already trust for in-cluster person dedup.
"""

from __future__ import annotations

from typing import Optional

from cluster_score import _is_llc_like, _person_signature


# A co-owner key appearing in MORE than this many distinct operators is
# treated as common-name noise (e.g. "Smith, John" across the whole city)
# and excluded from the cross-cluster link surface. Stays as raw evidence
# in the per-cluster co_owners list — only suppressed from linked_operators.
MAX_OPERATORS_PER_CO_OWNER = 5


def parse_co_owner(raw: str) -> Optional[dict]:
    """Return {"key": frozenset, "display": str} or None for unkeyable input.

    None when:
    - empty / whitespace
    - looks like an LLC / corp / inc (caller wants humans only)
    - cannot extract a (first, last) pair (single-token names, garbage)
    """
    if not raw or not raw.strip():
        return None
    if _is_llc_like(raw):
        return None
    sig = _person_signature(raw)
    if sig is None:
        return None
    return {"key": sig, "display": raw.strip()}


def suppress_common_names(
    index: dict[frozenset, list],
) -> dict[frozenset, list]:
    """Drop entries whose value-list length exceeds MAX_OPERATORS_PER_CO_OWNER.

    `index` maps co-owner key → list of appearances (e.g. operator slugs).
    Returns a filtered shallow copy. Lengths AT the threshold are kept;
    only strictly greater is dropped.
    """
    return {k: v for k, v in index.items() if len(v) <= MAX_OPERATORS_PER_CO_OWNER}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests/test_co_owner.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add pipeline/co_owner.py pipeline/tests/test_co_owner.py
git commit -m "feat(pipeline): co_owner module — parse ADD_OWNER, suppress common-name noise"
```

---

## Task 3: Aggregate co-owner counts per owner in `by_owner`

**Why:** Per-cluster aggregation in Task 4 needs co-owner data already rolled up per owner. This task does that rollup during the existing `by_owner` build, where we already iterate every parcel — so it's nearly-free.

**Files:**
- Modify: `pipeline/emit.py:307-366` (the `by_owner` build loop)

- [ ] **Step 1: Add the import**

In `pipeline/emit.py`, find the existing imports near the top. Add to the `from cluster_score import (...)` block — actually no, this is a new module. Add a new import line below the existing cluster_score block:

```python
from co_owner import parse_co_owner
```

(Place it next to the other from-`cluster_score` import block; alphabetical order between `cluster_score` and `normalize` is fine.)

- [ ] **Step 2: Aggregate co-owners during the by_owner pass**

In `_emit_owners` (or whichever function builds `by_owner`; locate by `by_owner: dict[str, dict] = {}` near `pipeline/emit.py:307`), modify the per-owner loop. Inside the existing `for owner_norm, parcel_ids in owners.items():` block, immediately after the existing local-variable initializations (`portfolio_value = 0`, `oldest_violation = None`), add:

```python
        # Co-owner aggregation: every parcel's ADD_OWNER, parsed to a stable
        # key. Same human under different spellings collapses to one entry.
        co_owner_counts: Counter[frozenset] = Counter()
        co_owner_display_counts: dict[frozenset, Counter[str]] = defaultdict(Counter)
```

Then inside the `for pid in parcel_ids:` loop (after the existing parcel field reads, before the `props.append(...)` call), add:

```python
            parsed = parse_co_owner(parcel.get("add_owner") or "")
            if parsed is not None:
                co_owner_counts[parsed["key"]] += 1
                co_owner_display_counts[parsed["key"]][parsed["display"]] += 1
```

After the `for pid in parcel_ids:` loop ends but before the `display = max(...)` line, add:

```python
        # Pick the most-common display variant for each co-owner key.
        co_owner_displays = {
            k: cnt.most_common(1)[0][0]
            for k, cnt in co_owner_display_counts.items()
        }
```

Then in the `by_owner[owner_norm] = { ... }` dict literal, add two lines between `"props": ...` and the closing `}`:

```python
            "co_owner_counts": co_owner_counts,
            "co_owner_displays": co_owner_displays,
```

The relevant portion becomes:

```python
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
```

- [ ] **Step 3: Run pipeline tests to confirm nothing regressed**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests -q
```

Expected: green. (No new test for this step — it's plumbing that Task 4's tests will exercise end-to-end.)

- [ ] **Step 4: Commit**

```bash
git add pipeline/emit.py
git commit -m "feat(pipeline): aggregate per-owner co-owner counts during by_owner build"
```

---

## Task 4: Attach `co_owners` and `linked_operators` to cluster audit blocks

**Why:** This is where the global cross-cluster index actually forms and gets surfaced as audit evidence. Two-pass design: build all clusters first (existing logic), then a post-pass computes the global co-owner index, applies suppression, and attaches per-cluster fields.

**Files:**
- Modify: `pipeline/emit.py:_build_operator_clusters` (around line 137) — accumulate per-cluster co-owner aggregates and run the post-pass.
- Test: `pipeline/tests/test_emit.py`

- [ ] **Step 1: Write failing tests**

Append to `pipeline/tests/test_emit.py`:

```python
def test_cluster_audit_co_owners_field_populated():
    """When parcels in a cluster carry ADD_OWNER, the cluster audit block
    surfaces a co_owners list with the human names and parcel counts."""
    addr = "100 MAIN ST | BUFFALO | NY | 14215"
    by_owner = {
        "acme 1 llc": {
            "slug": "acme-1-llc", "display": "ACME 1 LLC",
            "mail_keys": Counter({addr: 3}),
            "properties": 3, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter({
                frozenset({"SMITH", "JOHN"}): 2,
                frozenset({"DOE", "JANE"}): 1,
            }),
            "co_owner_displays": {
                frozenset({"SMITH", "JOHN"}): "Smith, John A",
                frozenset({"DOE", "JANE"}): "Doe, Jane",
            },
        },
        "acme 2 llc": {
            "slug": "acme-2-llc", "display": "ACME 2 LLC",
            "mail_keys": Counter({addr: 2}),
            "properties": 2, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter({frozenset({"SMITH", "JOHN"}): 1}),
            "co_owner_displays": {frozenset({"SMITH", "JOHN"}): "JOHN SMITH"},
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    co_owners = cluster["audit"]["co_owners"]
    # Smith should aggregate 2 + 1 = 3 parcels; sorted descending by parcels.
    assert co_owners[0]["parcels"] == 3
    assert co_owners[0]["name"] in {"Smith, John A", "JOHN SMITH"}
    # Jane Doe is also present.
    assert any(c["name"] == "Doe, Jane" and c["parcels"] == 1 for c in co_owners)


def test_cluster_audit_linked_operators_via_shared_co_owner():
    """Two clusters seeded by different mailing addresses, both with the
    same human as a co-owner, link to each other via linked_operators."""
    addr_a = "100 MAIN ST | BUFFALO | NY | 14215"
    addr_b = "200 OAK ST | BUFFALO | NY | 14215"
    smith = frozenset({"SMITH", "JOHN"})
    by_owner = {
        # Cluster A
        "acme 1 llc": {
            "slug": "acme-1-llc", "display": "ACME 1 LLC",
            "mail_keys": Counter({addr_a: 3}),
            "properties": 3, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter({smith: 2}),
            "co_owner_displays": {smith: "Smith, John A"},
        },
        "acme 2 llc": {
            "slug": "acme-2-llc", "display": "ACME 2 LLC",
            "mail_keys": Counter({addr_a: 1}),
            "properties": 1, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter(), "co_owner_displays": {},
        },
        # Cluster B (different mail key, same Smith)
        "beta 1 llc": {
            "slug": "beta-1-llc", "display": "BETA 1 LLC",
            "mail_keys": Counter({addr_b: 3}),
            "properties": 3, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter({smith: 1}),
            "co_owner_displays": {smith: "JOHN SMITH"},
        },
        "beta 2 llc": {
            "slug": "beta-2-llc", "display": "BETA 2 LLC",
            "mail_keys": Counter({addr_b: 1}),
            "properties": 1, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
            "co_owner_counts": Counter(), "co_owner_displays": {},
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 2
    slugs = sorted(clusters.keys())
    a, b = clusters[slugs[0]], clusters[slugs[1]]
    # A links to B
    a_links = a["audit"]["linked_operators"]
    assert any(L["operator_slug"] == b["operator_slug"] for L in a_links), \
        f"A should link to B; got {a_links}"
    # B links to A
    b_links = b["audit"]["linked_operators"]
    assert any(L["operator_slug"] == a["operator_slug"] for L in b_links), \
        f"B should link to A; got {b_links}"


def test_cluster_audit_common_co_owner_suppressed_from_links():
    """A co-owner appearing in MORE than MAX_OPERATORS_PER_CO_OWNER (=5)
    distinct clusters is dropped from linked_operators (still in co_owners)."""
    from co_owner import MAX_OPERATORS_PER_CO_OWNER
    smith = frozenset({"SMITH", "JOHN"})
    by_owner = {}
    # Build (MAX + 1) tiny clusters, each at its own mailing address,
    # each carrying Smith as a co-owner. With suppression in force, none
    # should reference each other via linked_operators on this key.
    for i in range(MAX_OPERATORS_PER_CO_OWNER + 1):
        addr = f"{i} GENERIC ST | BUFFALO | NY | 14215"
        for j in range(2):  # 2 LLCs per cluster
            slug = f"op-{i}-{j}"
            by_owner[f"op {i} {j} llc"] = {
                "slug": slug, "display": f"OP {i} {j} LLC",
                "mail_keys": Counter({addr: 2}),
                "properties": 2, "open": 0, "all_violations": 0,
                "complaints_311_12mo": 0, "total_value": 0, "props": [],
                "co_owner_counts": Counter({smith: 1}) if j == 0 else Counter(),
                "co_owner_displays": ({smith: "Smith, John"} if j == 0 else {}),
            }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == MAX_OPERATORS_PER_CO_OWNER + 1
    for cluster in clusters.values():
        # Smith still appears as raw evidence ...
        names = [c["name"] for c in cluster["audit"]["co_owners"]]
        assert any("Smith" in n for n in names)
        # ... but no linked_operator entry uses Smith as the linking key.
        for L in cluster["audit"]["linked_operators"]:
            assert L["co_owner"] != "Smith, John"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests/test_emit.py -k "co_owner or linked" -v
```

Expected: 3 failures with `KeyError: 'co_owners'` (or similar audit-block key error).

- [ ] **Step 3: Add the import**

In `pipeline/emit.py`, near the top, add:

```python
from co_owner import suppress_common_names
```

(Next to the existing `from co_owner import parse_co_owner` from Task 3.)

- [ ] **Step 4: Accumulate per-cluster co-owner aggregates during cluster build**

In `pipeline/emit.py`, inside `_build_operator_clusters`, find the existing `for o in sorted_owners:` loop (around line 212). After that loop ends, BEFORE the `# Person-name dedup within the cluster` comment, insert:

```python
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
```

(`defaultdict` is already imported via `from collections import Counter, defaultdict` near the top of `emit.py`. If not, add `defaultdict` to that import.)

Then in the same function, just before the `clusters[slug] = { ... }` literal, store the per-cluster aggregates as transient fields on the cluster object so the post-pass can read them:

Find the existing `audit = { ... }` literal (around line 241). Inside it (between `"person_dedups": person_dedups,` and the closing `}`), add two lines:

```python
            "co_owners": [],          # filled in post-pass below
            "linked_operators": [],   # filled in post-pass below
```

Then after the `clusters[slug] = { ... }` block, but still inside the `for mail_key, owner_norms in by_mail.items():` loop, attach the per-cluster Counter as a transient (non-emitted) attribute:

```python
        clusters[slug]["_co_owner_counts"] = cluster_co_owner_counts
        clusters[slug]["_co_owner_displays"] = cluster_co_owner_displays
```

- [ ] **Step 5: Add the post-pass that builds the global index and fills audit fields**

Still in `_build_operator_clusters`, after the `for mail_key, owner_norms in by_mail.items():` loop ends (and before `return clusters, owner_to_operator, counts`), insert:

```python
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
        # co_owners: sorted by parcel count descending
        co_counts = cluster["_co_owner_counts"]
        co_displays = cluster["_co_owner_displays"]
        co_owners = sorted(
            (
                {"name": co_displays[k], "parcels": c}
                for k, c in co_counts.items()
            ),
            key=lambda d: -d["parcels"],
        )[:CO_OWNERS_TOP_N]

        # linked_operators: for each non-suppressed co-owner in this cluster,
        # list other clusters that share the key.
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
```

- [ ] **Step 6: Run the new tests**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests/test_emit.py -v
```

Expected: all green, including the 3 new tests from Step 1.

- [ ] **Step 7: Run the full pipeline test suite**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests -q
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add pipeline/emit.py pipeline/tests/test_emit.py
git commit -m "feat(pipeline): co_owners + linked_operators in cluster audit block"
```

---

## Task 5: Frontend — render co-owner sections in the audit disclosure

**Files:**
- Modify: `web/app.js` (`renderAuditDisclosure`)

- [ ] **Step 1: Extend `renderAuditDisclosure` to render the two new sections**

In `web/app.js`, find `function renderAuditDisclosure(op)`. Inside the existing `if (!a)` fallback the function already returns early — leave that path alone. Inside the main path (where `a` is the audit object), add two new `<li>` blocks that will render AFTER the Member list (per the spec).

Locate the existing `const memberLines = ...` definition. After it, add:

```javascript
  const coOwnerLines = (a.co_owners || []).map(c => `
    <li><span class="audit-key">Co-owner</span>
      <strong>${escapeHtml(c.name)}</strong>
      <span class="sub">(${c.parcels} parcel${c.parcels === 1 ? "" : "s"} in this cluster)</span>
    </li>`).join("");
  const linkedOpLines = (a.linked_operators || []).map(L => `
    <li><span class="audit-key">Linked operator</span>
      <a href="#/operator/${encodeURIComponent(L.operator_slug)}"
         onclick="event.preventDefault(); window.openOperator('${escapeHtml(L.operator_slug)}')">${escapeHtml(L.operator_label)}</a>
      <span class="sub">via ${escapeHtml(L.co_owner)} (${L.parcels} parcel${L.parcels === 1 ? "" : "s"} there)</span>
    </li>`).join("");
```

Then in the existing return template literal for the disclosure body, find the existing line:

```javascript
        ${dedupLines}
        ${memberLines}
```

and change it to:

```javascript
        ${dedupLines}
        ${memberLines}
        ${coOwnerLines}
        ${linkedOpLines}
```

(No new CSS — the lines reuse `.audit-list`, `.audit-key`, and `.sub` styles already defined in Task 6 of the previous cycle.)

- [ ] **Step 2: Run pipeline against cached raw data and verify emitted JSON**

```bash
cd /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline && .venv/bin/python run.py --no-fetch
```

Expected: completes without error in ~40 seconds.

Verify the new fields are present on at least one operator:

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/python -c "
import json, glob
files = glob.glob('/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/web/data/operators/*.json')
hits = 0
for f in files:
    d = json.load(open(f))
    audit = d.get('audit', {})
    if audit.get('co_owners') or audit.get('linked_operators'):
        hits += 1
        if hits <= 3:
            print('---', d.get('operator_label'))
            print('  co_owners:', audit.get('co_owners')[:3])
            print('  linked_operators:', audit.get('linked_operators')[:3])
print(f'{hits}/{len(files)} operators carry co-owner audit data')
"
```

Expected: a non-zero hit count and at least one operator with both `co_owners` and `linked_operators` populated.

- [ ] **Step 3: Browser smoke**

```bash
cd /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/web && python3 -m http.server 8765
```

Open http://localhost:8765, click Top landlords, open one of the operators identified by Step 2 as having co-owner audit data. Expand "How these names are grouped". Confirm:

- "Co-owner" rows appear with names and parcel counts.
- "Linked operator" rows appear (if any) and clicking one navigates to that operator's page.

Stop the server when done (Ctrl-C if foregrounded; otherwise `pkill -f "http.server 8765"`).

- [ ] **Step 4: Commit**

```bash
git add web/app.js
git commit -m "feat(web): co-owner evidence + linked operators in audit disclosure"
```

---

## Task 6: End-to-end verification

- [ ] **Step 1: Full pipeline test suite**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/pytest /Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/tests -q
```

Expected: all green.

- [ ] **Step 2: Confirm the production data sanity numbers**

```bash
/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/pipeline/.venv/bin/python -c "
import json, glob
files = glob.glob('/Users/arseniocolon/Desktop/repos/buffalo-landlord-lookup/web/data/operators/*.json')
co_owner_clusters = 0
linked_clusters = 0
total_links = 0
for f in files:
    d = json.load(open(f))
    audit = d.get('audit', {})
    if audit.get('co_owners'):
        co_owner_clusters += 1
    if audit.get('linked_operators'):
        linked_clusters += 1
        total_links += len(audit['linked_operators'])
print(f'Operators with co_owners: {co_owner_clusters}/{len(files)}')
print(f'Operators with linked_operators: {linked_clusters}/{len(files)}')
print(f'Total cross-cluster links emitted: {total_links}')
"
```

Expected: a few hundred operators carry `co_owners` (since 26% of parcels have ADD_OWNER) and a meaningful subset of those produce `linked_operators` after suppression.

- [ ] **Step 3: Browser confirmation on one alter-ego operator**

Manually pick an operator that the Stage 1 work showed as alter-ego (e.g. one of the 262 alter-ego clusters). Open its page in the dev server, expand the audit disclosure, and confirm:

- The audit panel still renders correctly (no regression from Stage 1).
- If that cluster has co-owners on its parcels, they appear.
- If that cluster shares a co-owner with another cluster, the "Linked operator" row appears.

This is a manual eyeball check — there's no test command. Note any regressions immediately.

---

## Definition of done

- `meta.json` shape unchanged.
- Each operator JSON's `audit` block carries `co_owners` and `linked_operators` arrays (possibly empty).
- Suppression threshold of 5 distinct operators is respected: `linked_operators` never references a co-owner that appears in more than 5 clusters.
- Frontend operator pages render the two new sections inside the existing `<details>` disclosure when the data is non-empty.
- No regression in any existing test or rendering surface.
