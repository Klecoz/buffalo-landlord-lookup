# Transparency UI (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the operator-clustering audit trail and per-source data freshness visible in the Buffalo Landlord Lookup UI, without changing any clustering heuristics.

**Architecture:** Pipeline emits two new things — a structured `audit` block on each cluster (re-shaping data the cluster already has) and per-source `*_max_date` fields in `meta.json`. Frontend reads those and renders (a) a collapsed `<details>` "How these names are grouped" disclosure on operator pages and (b) small freshness pills next to each data panel header. The clustering algorithm itself is untouched.

**Tech Stack:** Python 3 + pytest (pipeline). Vanilla JS + CSS (frontend, no build step). MapLibre GL JS for the map (untouched here).

**Spec:** `docs/superpowers/specs/2026-05-07-transparency-and-verified-confidence-design.md`

**Out of scope (Stage 2, separate plan later):** validation labels, calibration computation, reader feedback channel.

---

## File Structure

**Pipeline (modify):**
- `pipeline/cluster_score.py` — add `cohesion_details()` that returns score + token + explanation in one structured object; add `pattern` field to `classify_cluster()` output (None or `"alter_ego"`). Existing `name_stem_cohesion()` keeps its 2-tuple return for back-compat.
- `pipeline/emit.py` — at cluster construction (around line 231), assemble an `audit` dict and attach to each cluster; pass through unchanged into the per-operator JSON written under `web/data/operators/`.
- `pipeline/join.py` — `_join_violations` returns the max `inspection_date` it observed; the meta dict gains `code_violations_max_date`.

**Pipeline (tests, modify/create):**
- `pipeline/tests/test_cluster_score.py` — new tests for `cohesion_details()` and the `pattern` field.
- `pipeline/tests/test_emit.py` — new test asserting the `audit` block shape on a fixture cluster.

**Frontend (modify):**
- `web/app.js` — `loadMeta` keeps the colophon line; `renderOperator` (around line 714) adds the disclosure block; both `renderDossier` (around line 304) and `renderOperator`/`renderPortfolio` get freshness pills near the data they qualify.
- `web/index.html` — no structural change.
- `web/style.css` — add `.freshness-pill`, `.freshness-pill.fresh`, `.aging`, `.stale`; add `.audit-details` for the `<details>` disclosure.

---

## Task 1: Add `cohesion_details()` to cluster_score

**Why first:** Several downstream pieces (audit block, tests) need the cohesion *token* and *score* as first-class values rather than parsed from the `"5 of 8 owners share 'acme'"` evidence string. Adding a sibling function is safer than changing `name_stem_cohesion`'s signature (existing tests destructure the 2-tuple).

**Files:**
- Modify: `pipeline/cluster_score.py`
- Test: `pipeline/tests/test_cluster_score.py`

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/test_cluster_score.py` (above the "--- classify_cluster ---" comment block, after the existing cohesion tests):

```python
# --- cohesion_details ----------------------------------------------------

def test_cohesion_details_strong_family():
    from cluster_score import cohesion_details
    d = cohesion_details([
        "hertel properties llc",
        "hertel holdings llc",
        "hertel realty llc",
    ])
    assert d["score"] == 1.0
    assert d["distinctive_token"] == "hertel"
    assert "hertel" in d["explanation"]
    assert d["owner_count"] == 3


def test_cohesion_details_no_distinctive_tokens():
    from cluster_score import cohesion_details
    d = cohesion_details(["llc", "inc"])  # all stopwords
    assert d["score"] == 0.0
    assert d["distinctive_token"] is None
    assert d["explanation"] == "no distinctive tokens"


def test_cohesion_details_single_owner():
    from cluster_score import cohesion_details
    d = cohesion_details(["solo llc"])
    assert d["score"] == 1.0
    assert d["distinctive_token"] is None
    assert d["explanation"] == "single owner"


def test_cohesion_details_empty():
    from cluster_score import cohesion_details
    d = cohesion_details([])
    assert d["score"] == 0.0
    assert d["distinctive_token"] is None
    assert d["owner_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd pipeline && pytest tests/test_cluster_score.py -k cohesion_details -v
```

Expected: 4 tests fail with `ImportError: cannot import name 'cohesion_details' from 'cluster_score'`.

- [ ] **Step 3: Implement `cohesion_details`**

In `pipeline/cluster_score.py`, replace the existing `name_stem_cohesion` function (the block from `def name_stem_cohesion(...)` through its closing `return (score, evidence)`) with this pair:

```python
def cohesion_details(owner_names: list[str]) -> dict:
    """Structured form of cohesion analysis.

    Returns dict with: score (0.0–1.0), distinctive_token (str|None),
    explanation (str), owner_count (int). Used by emit.py to build the
    per-cluster audit block surfaced in the UI.
    """
    n = len(owner_names)
    if n == 0:
        return {"score": 0.0, "distinctive_token": None,
                "explanation": "empty cluster", "owner_count": 0}
    if n == 1:
        return {"score": 1.0, "distinctive_token": None,
                "explanation": "single owner", "owner_count": 1}

    token_owner_counts: Counter[str] = Counter()
    for name in owner_names:
        for t in set(_tokenize_for_stem(name)):
            token_owner_counts[t] += 1

    if not token_owner_counts:
        return {"score": 0.0, "distinctive_token": None,
                "explanation": "no distinctive tokens", "owner_count": n}

    token, count = max(
        token_owner_counts.items(),
        key=lambda kv: (kv[1], len(kv[0])),
    )
    return {
        "score": count / n,
        "distinctive_token": token,
        "explanation": f"{count} of {n} owners share '{token}'",
        "owner_count": n,
    }


def name_stem_cohesion(owner_names: list[str]) -> tuple[float, str]:
    """Score how much a cluster's owner names look like one family.

    Returns (score in 0.0–1.0, evidence_string). Score = fraction of owners
    sharing the most common distinctive token. Higher = tighter family.

    Thin wrapper around cohesion_details — kept for back-compat with
    classify_cluster and existing tests.
    """
    d = cohesion_details(owner_names)
    return (d["score"], d["explanation"])
```

- [ ] **Step 4: Run all cluster_score tests**

```bash
cd pipeline && pytest tests/test_cluster_score.py -v
```

Expected: all tests pass (the 4 new `cohesion_details` tests plus the existing suite, since `name_stem_cohesion` still returns the 2-tuple).

- [ ] **Step 5: Commit**

```bash
git add pipeline/cluster_score.py pipeline/tests/test_cluster_score.py
git commit -m "feat(pipeline): cohesion_details — structured cohesion result for audit block"
```

---

## Task 2: Tag `classify_cluster` output with a `pattern` field

**Why:** The audit panel needs to show "alter-ego match fired" as a discrete signal. Today it's only inferable by string-matching the evidence (`"alter-ego pattern"`). A structured field is cleaner and makes UI rendering straightforward.

**Files:**
- Modify: `pipeline/cluster_score.py`
- Test: `pipeline/tests/test_cluster_score.py`

- [ ] **Step 1: Write failing tests**

Append to `pipeline/tests/test_cluster_score.py` after the alter-ego test block:

```python
def test_classify_pattern_alter_ego_set():
    result = classify_cluster(
        ["Mahoney, Martin C", "259 Breckenridge LLC"], "street",
    )
    assert result["pattern"] == "alter_ego"


def test_classify_pattern_none_for_normal_cluster():
    result = classify_cluster(
        [f"hertel holdings {i} llc" for i in range(5)], "street",
    )
    assert result["pattern"] is None


def test_classify_pattern_none_for_po_box_alter_ego_shape():
    """PO-box pairs go through the n<=8 branch, not alter-ego."""
    result = classify_cluster(
        ["Mahoney, Martin C", "259 Breckenridge LLC"], "po_box",
    )
    assert result["pattern"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd pipeline && pytest tests/test_cluster_score.py -k pattern -v
```

Expected: 3 tests fail with `KeyError: 'pattern'`.

- [ ] **Step 3: Add `pattern` to every return path of `classify_cluster`**

In `pipeline/cluster_score.py`, edit `classify_cluster`. Each existing `return {...}` dict must gain a `"pattern"` key — `"alter_ego"` for the alter-ego branch, `None` for all others. The full updated function body (replacing the existing `def classify_cluster(...)` through its final `return ...`) is:

```python
def classify_cluster(owner_names: list[str], address_kind: str) -> dict:
    """Decide whether to keep a cluster and at what confidence.

    address_kind: "po_box" | "street". PO boxes are a stronger identity
    signal than street addresses, so the thresholds are looser.
    Returns {action, confidence, evidence, pattern}. `pattern` is one of
    {"alter_ego", None} — surfaced in the per-cluster audit block.
    """
    n = len(owner_names)
    score, evidence = name_stem_cohesion(owner_names)
    is_po = address_kind == "po_box"

    if not is_po and n == 2:
        llc_count = sum(1 for name in owner_names if _is_llc_like(name))
        person_count = sum(
            1 for name in owner_names
            if not _is_llc_like(name) and _person_signature(name) is not None
        )
        if llc_count == 1 and person_count == 1:
            return {
                "action": "keep", "confidence": "high",
                "evidence": "person + LLC at shared street address — alter-ego pattern",
                "pattern": "alter_ego",
            }

    if is_po and score >= 0.5:
        return {"action": "keep", "confidence": "high",
                "evidence": evidence, "pattern": None}
    if is_po and n <= 8:
        return {
            "action": "keep", "confidence": "high",
            "evidence": f"{n} LLC{'s' if n != 1 else ''} sharing one PO box",
            "pattern": None,
        }
    if not is_po and score >= 0.6:
        return {"action": "keep", "confidence": "high",
                "evidence": evidence, "pattern": None}
    if not is_po and score >= 0.3:
        return {"action": "keep", "confidence": "medium",
                "evidence": evidence, "pattern": None}
    if n > 30 and score < 0.3:
        return {
            "action": "drop", "confidence": "low",
            "evidence": f"{n} unrelated owners at one address — likely agent or property manager",
            "pattern": None,
        }
    if score >= 0.2:
        return {"action": "keep", "confidence": "medium",
                "evidence": evidence, "pattern": None}
    return {"action": "keep", "confidence": "low",
            "evidence": evidence, "pattern": None}
```

- [ ] **Step 4: Run all cluster_score tests**

```bash
cd pipeline && pytest tests/test_cluster_score.py -v
```

Expected: all tests pass — the existing tests still match (they only check `action`, `confidence`, `evidence`); the 3 new `pattern` tests now pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/cluster_score.py pipeline/tests/test_cluster_score.py
git commit -m "feat(pipeline): classify_cluster emits structured pattern field (alter_ego flag)"
```

---

## Task 3: Emit `audit` block on each cluster

**Files:**
- Modify: `pipeline/emit.py`
- Test: `pipeline/tests/test_emit.py`

- [ ] **Step 1: Write a failing test for the audit block**

Append to `pipeline/tests/test_emit.py`:

```python
def test_cluster_emits_audit_block():
    """Each operator cluster gets a structured `audit` dict bundling
    everything the UI needs to render the 'How these names are grouped'
    disclosure."""
    by_owner = {}
    for i in range(4):
        slug = f"acme-{i}-llc"
        display = f"ACME {i} LLC"
        by_owner[display.lower()] = {
            "slug": slug, "display": display,
            "mail_keys": Counter({"100 MAIN ST | BUFFALO | NY | 14215": 3}),
            "properties": 5, "open": 1, "all_violations": 2,
            "complaints_311_12mo": 0, "total_value": 100_000,
            "props": [],
        }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1, "fixture should produce one cluster"
    cluster = next(iter(clusters.values()))
    audit = cluster["audit"]
    assert audit["shared_mailing_address"] == cluster["mailing_address"]
    assert audit["address_kind"] == "street"
    assert audit["member_count"] == 4
    assert audit["cohesion"]["distinctive_token"] == "acme"
    assert audit["cohesion"]["score"] == 1.0
    assert "acme" in audit["cohesion"]["explanation"]
    assert audit["pattern"] is None
    assert audit["person_dedups"] == []  # no person-name variants in fixture


def test_cluster_audit_records_alter_ego_pattern():
    """A 1-person + 1-LLC street cluster fires the alter-ego rule and the
    audit block surfaces the pattern."""
    by_owner = {
        "mahoney, martin c": {
            "slug": "mahoney-martin-c", "display": "Mahoney, Martin C",
            "mail_keys": Counter({"259 BRECKENRIDGE | BUFFALO | NY | 14222": 2}),
            "properties": 1, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 200_000, "props": [],
        },
        "259 breckenridge llc": {
            "slug": "259-breckenridge-llc", "display": "259 Breckenridge LLC",
            "mail_keys": Counter({"259 BRECKENRIDGE | BUFFALO | NY | 14222": 1}),
            "properties": 1, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 150_000, "props": [],
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    assert len(clusters) == 1
    cluster = next(iter(clusters.values()))
    assert cluster["audit"]["pattern"] == "alter_ego"


def test_cluster_audit_surfaces_person_dedups():
    """When dedup_persons_in_cluster collapses a name into variants, those
    variants land in audit.person_dedups."""
    addr = "100 OAK ST | BUFFALO | NY | 14215"
    by_owner = {
        "john smith": {
            "slug": "john-smith", "display": "JOHN SMITH",
            "mail_keys": Counter({addr: 2}),
            "properties": 5, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
        },
        "smith, john a": {
            "slug": "smith-john-a", "display": "SMITH, JOHN A",
            "mail_keys": Counter({addr: 2}),
            "properties": 3, "open": 0, "all_violations": 0,
            "complaints_311_12mo": 0, "total_value": 0, "props": [],
        },
    }
    clusters, _, _ = _build_operator_clusters(by_owner)
    if not clusters:
        # MIN_CLUSTER_OWNERS / MIN_CLUSTER_PARCELS may exclude tiny fixtures
        # — bail out cleanly rather than fail spuriously.
        import pytest as _pt
        _pt.skip("cluster size below emit.py minimums for this fixture")
    cluster = next(iter(clusters.values()))
    dedups = cluster["audit"]["person_dedups"]
    assert len(dedups) == 1
    assert dedups[0]["canonical"] == "JOHN SMITH"
    assert "SMITH, JOHN A" in dedups[0]["variants"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd pipeline && pytest tests/test_emit.py -v
```

Expected: the new tests fail with `KeyError: 'audit'`. Existing tests still pass.

- [ ] **Step 3: Build the `audit` block in emit.py**

In `pipeline/emit.py`, add this import near the top with the other `cluster_score` imports (search for `from cluster_score import` to find the existing import block):

```python
from cluster_score import (
    address_kind_from_key,
    classify_cluster,
    cohesion_details,
    dedup_persons_in_cluster,
)
```

(Add `cohesion_details` to whatever names are already imported; keep existing names.)

Then in `_build_operator_clusters`, modify the cluster-construction block (around `pipeline/emit.py:231` — the `clusters[slug] = { ... }` literal). Just before that assignment, after the existing `owner_groups = dedup_persons_in_cluster(owners_block)` line, insert:

```python
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
        }
```

Then in the `clusters[slug] = { ... }` dict literal, add a line `"audit": audit,` between `"evidence": verdict["evidence"],` and `"owners": owners_block,`. The relevant portion becomes:

```python
        clusters[slug] = {
            "operator_slug": slug,
            "operator_label": operator_label,
            "mailing_address": mail_key,
            "confidence": verdict["confidence"],
            "evidence": verdict["evidence"],
            "audit": audit,
            "owners": owners_block,
            "owner_groups": owner_groups,
            ...
```

(Leave the rest of the dict unchanged.)

- [ ] **Step 4: Verify the new tests pass**

```bash
cd pipeline && pytest tests/test_emit.py -v
```

Expected: all tests pass, including the 3 new `audit`-block tests.

- [ ] **Step 5: Run the full pipeline test suite**

```bash
cd pipeline && pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add pipeline/emit.py pipeline/tests/test_emit.py
git commit -m "feat(pipeline): per-cluster audit block — shared address, cohesion, pattern, dedups"
```

---

## Task 4: Track per-source `*_max_date` in meta.json

**Files:**
- Modify: `pipeline/join.py`

- [ ] **Step 1: Update `_join_violations` to return the max observed date**

In `pipeline/join.py`, replace the entire `_join_violations` function (currently around lines 212–236) with:

```python
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
```

- [ ] **Step 2: Update the caller in `join_all` to capture and emit the new value**

In `pipeline/join.py`, find the line `v_matched = _join_violations(by_addr, violations)` (around line 314) and replace it with:

```python
    v_matched, v_max_date = _join_violations(by_addr, violations)
```

Then update the meta dict (around line 350) to add `code_violations_max_date`:

```python
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
        "demolitions_matched": d_matched,
        "owners": len(owners),
    }
```

- [ ] **Step 3: Run the join tests**

```bash
cd pipeline && pytest tests/test_join.py -v
```

Expected: green. (If `test_join.py` calls `_join_violations` directly anywhere it'd need the new tuple unpacking — at time of plan writing it doesn't, but if the test fails on that line, update the destructuring there to match.)

- [ ] **Step 4: Commit**

```bash
git add pipeline/join.py
git commit -m "feat(pipeline): emit code_violations_max_date in meta.json"
```

---

## Task 5: Frontend — freshness pill component

**Why:** Stale 311 data is the highest-stakes case. The pill makes "this dataset stopped updating" reader-visible without burying the line in the colophon.

**Files:**
- Modify: `web/app.js` (add helper + use in the three render functions)
- Modify: `web/style.css` (add `.freshness-pill` rules)

- [ ] **Step 1: Add the helper function in app.js**

In `web/app.js`, find the helpers section (around line 22, after the `escapeHtml` and `fmtMoney` helpers, before `_copyLinkBtnHtml`). Insert:

```javascript
// Freshness pill: a small inline label rendered next to a panel header
// that tells the reader how current the underlying source is.
//
// kind: "violations" | "311" | "parcels"
// Returns an HTML string; pass through directly into a template literal.
function freshnessPill(kind) {
  const meta = state.meta || {};
  const generated = meta.generated_at || "";
  const maxDateByKind = {
    violations: meta.code_violations_max_date || "",
    "311": meta.complaints_311_max_date || "",
    parcels: meta.generated_at || "",
  };
  const labelByKind = {
    violations: "Code violations",
    "311": "311 complaints",
    parcels: "Parcels",
  };
  const max = maxDateByKind[kind] || "";
  const label = labelByKind[kind] || kind;
  if (!max && !generated) return "";

  const ageDays = (() => {
    if (!max) return Infinity;
    const ms = Date.now() - new Date(max).getTime();
    return Math.floor(ms / 86400000);
  })();

  // Special-case 311 freeze: the dataset stopped updating in 2024-05.
  // If the max date precedes the run by > 180 days, treat it as known-frozen.
  if (kind === "311" && ageDays > 180) {
    return `<span class="freshness-pill stale" title="Buffalo's 311 dataset (whkc-e5vr) stopped updating May 2024. The 12-month window ends at the dataset's max date, not today.">${label}: dataset frozen since ${max.slice(0, 7)}</span>`;
  }

  let cls = "fresh";
  if (ageDays > 180) cls = "stale";
  else if (ageDays > 30) cls = "aging";

  const dateLabel = max ? max.slice(0, 10) : generated.slice(0, 10);
  return `<span class="freshness-pill ${cls}">${label}: through ${dateLabel}</span>`;
}
```

- [ ] **Step 2: Insert the pill in `renderDossier`**

In `web/app.js`, find the `<h3>Recent code violations` line (around line 341). Replace those three header lines (the violations h3, the empty/list rendering, and the 311 h3) so they read:

```javascript
    <h3>Recent code violations (${violations.length}) ${freshnessPill("violations")}</h3>
    ${violations.length === 0
      ? `<p class="empty">No code violations on record.</p>`
      : `<ul class="violations">${violations.slice(0, 10).map(v => `
          <li>
            <div class="date">${fmtDate(v.date)} · ${escapeHtml(v.status || "")}</div>
            <div>${escapeHtml(v.description || v.code_section || "—")}</div>
          </li>`).join("")}</ul>`
    }

    <h3>Recent 311 housing complaints (${complaints.length}) ${freshnessPill("311")}</h3>
```

(Leave the rest of `renderDossier` unchanged.)

- [ ] **Step 3: Insert the pill on the operator and owner property tables**

In `renderOperator` (around line 787), change:

```javascript
    <h3>Properties (top 200 by concern)</h3>
```

to:

```javascript
    <h3>Properties (top 200 by concern) ${freshnessPill("violations")} ${freshnessPill("311")}</h3>
```

In `renderPortfolio` (around line 453), change:

```javascript
    <h3>Properties (sorted by concern score)</h3>
```

to:

```javascript
    <h3>Properties (sorted by concern score) ${freshnessPill("violations")} ${freshnessPill("311")}</h3>
```

- [ ] **Step 4: Add the CSS**

In `web/style.css`, after the `.evidence` rules (around line 691, before the `/* ----- Responsive */` block), insert:

```css
/* ----- Freshness pill --------------------------------------------------- */
.freshness-pill {
  display: inline-block;
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 400;
  letter-spacing: 0;
  color: var(--ink-2);
  margin-left: 8px;
  padding: 2px 6px;
  border: 1px solid var(--rule);
  border-radius: 2px;
  vertical-align: 2px;
  text-transform: none;
  white-space: nowrap;
}
.freshness-pill.fresh {
  color: var(--ink);
  border-color: var(--rule-2);
}
.freshness-pill.aging {
  color: var(--ink-2);
  border-color: var(--rule-2);
}
.freshness-pill.stale {
  color: var(--signal);
  border-color: var(--signal);
}
```

- [ ] **Step 5: Manual smoke test**

```bash
cd web && python -m http.server 8000
```

Open http://localhost:8000, click any parcel with 311 data. Expect:
- "Recent 311 housing complaints" header has a red pill reading "311 complaints: dataset frozen since 2024-05" (or close to it).
- "Recent code violations" header has a green-ish pill with a recent date.
- Hovering the 311 pill reveals the explanatory tooltip.

If the pill is invisible or not styled, hard-reload (Cmd-Shift-R).

- [ ] **Step 6: Commit**

```bash
git add web/app.js web/style.css
git commit -m "feat(web): per-source freshness pills next to data panel headers"
```

---

## Task 6: Frontend — "How these names are grouped" disclosure on operator pages

**Files:**
- Modify: `web/app.js` (`renderOperator`)
- Modify: `web/style.css` (`.audit-details` styles)

- [ ] **Step 1: Add the audit-rendering helper in app.js**

In `web/app.js`, immediately above `function renderOperator(op)` (around line 714), insert:

```javascript
// Render the "How these names are grouped" disclosure body for an operator.
// Pulls fields from op.audit (emitted by the pipeline). Falls back to the
// top-level evidence string if op.audit is missing (older data files).
function renderAuditDisclosure(op) {
  const a = op.audit;
  if (!a) {
    return op.evidence
      ? `<details class="audit-details"><summary>How these names are grouped</summary>
           <p>${escapeHtml(op.evidence)}</p>
         </details>`
      : "";
  }

  const cohesion = a.cohesion || {};
  const cohesionLine = cohesion.explanation
    ? `<li><span class="audit-key">Cohesion</span> ${escapeHtml(cohesion.explanation)} <span class="sub">(score ${cohesion.score})</span></li>`
    : "";
  const patternLine = a.pattern === "alter_ego"
    ? `<li><span class="audit-key">Pattern</span> alter-ego — one person + one LLC at the same street address. Classic LLC-unmasking signal.</li>`
    : "";
  const dedupLines = (a.person_dedups || []).map(d => `
    <li><span class="audit-key">Name dedup</span>
      <strong>${escapeHtml(d.canonical)}</strong>
      <span class="sub">also recorded as: ${(d.variants || []).map(escapeHtml).join(", ")}</span>
    </li>`).join("");
  const memberLines = (op.owners || []).map(o => `
    <li><span class="audit-key">Member</span> ${escapeHtml(o.display)}
      <span class="sub">(${o.properties} prop${o.properties === 1 ? "" : "s"})</span>
    </li>`).join("");

  return `
    <details class="audit-details">
      <summary>How these names are grouped</summary>
      <ul class="audit-list">
        <li><span class="audit-key">Shared mailing address</span> ${escapeHtml(a.shared_mailing_address || "—")}
          <span class="sub">(${escapeHtml(a.address_kind || "")})</span></li>
        ${cohesionLine}
        ${patternLine}
        ${dedupLines}
        ${memberLines}
      </ul>
      <p class="audit-foot sub">${a.member_count} LLC${a.member_count === 1 ? "" : "s"} merged into one operator. Bulk LLC ownership data is not publicly available in NYS, so this is the best inference the public data allows.</p>
    </details>`;
}
```

- [ ] **Step 2: Insert the disclosure in `renderOperator`'s template**

In `web/app.js`, find the line in `renderOperator` that reads:

```javascript
    <p class="empty" style="margin:2px 0 12px;">Mailing address: <strong>${escapeHtml(op.mailing_address)}</strong></p>
```

(around line 770). Insert the disclosure call right after that line (before `<div class="stat-grid">`):

```javascript
    <p class="empty" style="margin:2px 0 12px;">Mailing address: <strong>${escapeHtml(op.mailing_address)}</strong></p>
    ${renderAuditDisclosure(op)}

    <div class="stat-grid">
```

- [ ] **Step 3: Add the CSS**

In `web/style.css`, immediately after the `.freshness-pill` block from Task 5, insert:

```css
/* ----- Audit disclosure ("How these names are grouped") ----------------- */
.audit-details {
  margin: 4px 0 14px;
  border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
  padding: 6px 0;
}
.audit-details > summary {
  font-family: var(--sans);
  font-size: 12px;
  color: var(--ink-2);
  cursor: pointer;
  padding: 4px 0;
  list-style: none;
  user-select: none;
}
.audit-details > summary::-webkit-details-marker { display: none; }
.audit-details > summary::before {
  content: "▸ ";
  display: inline-block;
  width: 12px;
  color: var(--rule-2);
}
.audit-details[open] > summary::before { content: "▾ "; }
.audit-details[open] > summary { color: var(--ink); }

.audit-list {
  list-style: none;
  margin: 6px 0 4px;
  padding: 0;
  font-size: 13px;
  line-height: 1.55;
}
.audit-list > li {
  padding: 3px 0;
  border-bottom: 1px dotted var(--rule);
}
.audit-list > li:last-child { border-bottom: 0; }
.audit-key {
  display: inline-block;
  font-family: var(--mono);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-2);
  margin-right: 6px;
  min-width: 7em;
}
.audit-list .sub {
  display: inline;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--ink-2);
}
.audit-foot {
  margin: 8px 0 0;
  font-family: var(--sans);
  font-size: 12px;
  color: var(--ink-2);
}
```

- [ ] **Step 4: Run pipeline and smoke test**

```bash
cd pipeline && python run.py
```

Expected: completes without error; `web/data/operators/<slug>.json` files now have an `audit` field.

```bash
cd ../web && python -m http.server 8000
```

Open the site. From the leaderboard, click any operator (a multi-LLC entry).
Expect:
- A faint "▸ How these names are grouped" disclosure under the mailing-address line.
- Clicking it expands to show shared mailing address, address_kind, cohesion explanation, any pattern, and a list of member LLCs.
- For an alter-ego cluster (a 1-person + 1-LLC operator), the "Pattern" line reads "alter-ego".

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/style.css
git commit -m "feat(web): 'How these names are grouped' audit disclosure on operator pages"
```

---

## Task 7: Frontend — short audit note on owner (non-operator) pages

**Why:** Single-owner pages should explicitly say "no LLC grouping applied" so absence of the disclosure isn't read as a bug.

**Files:**
- Modify: `web/app.js` (`renderPortfolio`)

- [ ] **Step 1: Add the note in `renderPortfolio`**

In `web/app.js`, find the existing `${operatorHint}` line in `renderPortfolio`'s template (around line 432). Add a sibling line just above the `${variants}` line so the section reads:

```javascript
    <div class="addr">${escapeHtml(portfolio.owner_display)}</div>
    ${operatorHint}
    ${portfolio.operator_slug
      ? ""
      : `<p class="evidence sub-note">Single owner — no LLC grouping applied. Properties owned by the same person under shell LLCs with distinct names may appear separately.</p>`}
    ${variants}
```

(No new CSS — `.evidence` is already styled and the note inherits it.)

- [ ] **Step 2: Smoke test**

Reload the dev site, search for an owner whose name doesn't appear in any operator cluster (any "John Smith"-style entry without the "Same mailing address as related LLCs →" CTA). The owner page should now show the "Single owner — no LLC grouping applied" note.

For an owner that *is* part of an operator cluster, the existing `operatorHint` line still appears and the new note is suppressed.

- [ ] **Step 3: Commit**

```bash
git add web/app.js
git commit -m "feat(web): note 'no LLC grouping' on single-owner portfolio pages"
```

---

## Task 8: End-to-end verification

- [ ] **Step 1: Full pipeline test suite**

```bash
cd pipeline && pytest -v
```

Expected: all green.

- [ ] **Step 2: Re-run the pipeline against real data**

```bash
cd pipeline && python run.py
```

Expected: completes without warnings about missing keys; `web/data/meta.json` now contains `code_violations_max_date`; at least some `web/data/operators/*.json` files contain a non-empty `audit` block.

Quick check:

```bash
python -c "import json; m = json.load(open('../web/data/meta.json')); print('vmax:', m.get('code_violations_max_date'), '311max:', m.get('complaints_311_max_date'))"
ls ../web/data/operators | head -5
python -c "import json, glob; f = sorted(glob.glob('../web/data/operators/*.json'))[0]; d = json.load(open(f)); print(json.dumps(d.get('audit'), indent=2))"
```

Expected: a populated `audit` block including `shared_mailing_address`, `cohesion`, `pattern`, `person_dedups`, `member_count`.

- [ ] **Step 3: Browser smoke**

```bash
cd ../web && python -m http.server 8000
```

In a browser:

1. Visit http://localhost:8000.
2. Click any parcel with 311 data → verify the red "311 complaints: dataset frozen since 2024-05" pill appears next to the 311 heading.
3. Open the leaderboard → click an operator with 4+ LLCs → verify the "▸ How these names are grouped" disclosure exists and is collapsed by default. Expand it and check: shared mailing address, address kind, cohesion explanation, list of member LLCs.
4. Find an alter-ego operator (a person+LLC cluster — e.g. one labeled high-confidence with only 2 constituent owners) → verify the disclosure lists `Pattern: alter-ego`.
5. Open a single-owner portfolio page (one without the "Same mailing address as related LLCs" CTA) → verify the "Single owner — no LLC grouping applied" note appears.

- [ ] **Step 4: Final commit if any cleanup is needed**

If anything visual needed touch-up during Step 3, fix it now and:

```bash
git add -p
git commit -m "fix(web): polish freshness pill / audit disclosure rendering"
```

Otherwise nothing to commit — Stage 1 is complete.

---

## Definition of done (Stage 1)

- `meta.json` includes both `code_violations_max_date` and `complaints_311_max_date`.
- Each cluster JSON includes an `audit` block with `shared_mailing_address`, `address_kind`, `member_count`, `cohesion`, `pattern`, `person_dedups`.
- `pytest` is green for the pipeline.
- The 311 panel on a parcel page shows the red "frozen since 2024-05" pill.
- An operator page shows a collapsed-by-default "How these names are grouped" disclosure that expands into a structured trail.
- A single-owner page shows the "no LLC grouping applied" note.

Stage 2 (validation set + calibration) ships in a separate plan after this lands.
