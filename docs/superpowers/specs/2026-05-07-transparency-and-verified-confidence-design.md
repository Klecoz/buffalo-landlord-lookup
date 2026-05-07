# Transparency Layer + Verified Confidence

**Status:** approved design, ready for implementation planning
**Date:** 2026-05-07

## Context

Buffalo Landlord Lookup is a civic-data tool that names real people and groups
LLCs into "operator" clusters using heuristic mailing-address clustering plus
cohesion scoring (`pipeline/cluster_score.py`). It is intended to be defensible
to outside civic readers — local journalists, tenant organizations, curious
neighbors — not just personal use.

Three trust gaps block that audience:

1. **Confidence is unverified.** The pipeline emits high/medium/low labels and
   a one-line evidence string, but the labels have never been checked against
   ground truth. A miscalibrated threshold could mislabel real merges or
   wrongly merge unrelated LLCs at a service address.
2. **The audit trail is too thin.** Today the cluster panel shows one short
   string ("5 of 8 owners share 'acme'"). A skeptical reader can't see *which*
   LLCs were merged, *which* mailing address linked them, or what other
   signals fired (alter-ego matches, person-name dedups).
3. **Freshness caveats are buried.** The README explains 311 froze in 2024-05,
   but a reader landing on a landlord page sees panels of 311 data with only
   a single global "refreshed YYYY-MM-DD" line in the colophon. Per-source
   freshness isn't visible where the data is.

The thesis: a reader of a landlord page should be able to answer three
questions without leaving the page — *who exactly is in this group and why*,
*how fresh is this data and what's known stale*, and *how sure is the tool
and where could it be wrong*.

## Approach (overview)

Single design, two implementation cycles.

**Stage 1 — Transparency UI** ships first. It surfaces information the
pipeline already computes (cluster members, shared mailing address, cohesion
score, alter-ego links, person dedups; per-source max dates) into
reader-facing UI without changing any heuristics.

**Stage 2 — Validation set + calibration** follows. It introduces the first
ground-truth labels for the clustering output and reports precision, recall,
and per-confidence calibration on every pipeline run.

No reader feedback channel (mailto, GitHub issue link) is in scope for this
cycle.

## Stage 1 — Transparency UI

### 1A. Per-source freshness pills

**Pipeline change.** Extend `meta.json` so every data source the UI shows has
its own max-observed date. Today only 311 has `complaints_311_max_date`.

In `pipeline/join.py:349`, add:

- `code_violations_max_date` — max `inspection_date` (or equivalent) across
  fetched violations
- `parcels_generated_at` — already implicitly current, but record the ArcGIS
  layer's `editingInfo.lastEditDate` if available; otherwise reuse
  `generated_at`
- Keep existing `complaints_311_max_date` and `generated_at`

**Frontend change.** Add a small pill component rendered inline next to each
data-panel header on landlord and parcel pages:

- **Green ("current")**: max date within 30 days of `generated_at`
- **Amber ("aging")**: 31–180 days
- **Red ("stale" + explicit copy)**: more than 180 days, OR a known-frozen
  dataset (the 311 case)

Special-case copy for 311 when `generated_at - complaints_311_max_date >
180d`: "Buffalo's 311 dataset (`whkc-e5vr`) stopped updating May 2024. The
12-month window below ends at the dataset's max date, not today."

The pill replaces the silent "newest date in this panel is two years old"
problem with an explicit reader-facing disclosure right where the data lives.

### 1B. "How these names are grouped" disclosure

**Pipeline change.** Extend each cluster object in
`pipeline/emit.py:231` to add a structured `audit` block alongside the
existing `evidence` string. The data already exists on the cluster — this is
re-shaping, not new computation:

```jsonc
audit: {
  shared_mailing_address: "123 main st buffalo ny 14201",
  address_kind: "residential" | "commercial" | "po_box",
  cohesion: {
    score: 0.83,
    distinctive_token: "acme",
    explanation: "5 of 8 owners share 'acme'"
  },
  member_count: 8,
  alter_ego_links: [...],   // populated when alter-ego rule fires; else []
  person_dedups: [           // already partly in owner_groups
    { canonical: "John A Smith",
      variants: ["JOHN SMITH", "JOHN A. SMITH", "J A SMITH"] }
  ]
}
```

`owners[]` and `mailing_address` continue to live at the top level; the
`audit` block is a focused render-time bundle for the UI.

**Frontend change.** On operator landlord pages (`web/app.js:725` region),
insert a `<details>` disclosure titled "How these names are grouped",
collapsed by default, body containing:

- The shared mailing address
- The list of LLCs merged into this operator (already in `owners[]`)
- The cohesion explanation (existing `evidence` string)
- Any alter-ego matches that fired
- Any person-name dedups within the cluster

For non-operator owner pages: render a short single-line variant — "This is
a single owner — no LLC grouping applied." — so readers know absence of the
panel is intentional, not a bug.

Visual style stays consistent with the recent minimalist reskin (no heavy
boxes; thin rules and small caps for the section header).

## Stage 2 — Validation set + calibration

### 2A. Hand-curated labels

New file `pipeline/validation/labels.yaml`:

```yaml
- kind: true_merge
  description: "ACME Properties — 8 LLCs at 123 Main St, per Buffalo News 2024-09-12"
  mailing_address: "123 main st buffalo ny 14201"
  expect_in_cluster: ["acme-1-llc", "acme-2-llc", ...]
  expect_confidence: high  # or medium
  source: "..."

- kind: false_positive_pool
  description: "Service-address pool at 555 Delaware Ave (registered agent)"
  mailing_address: "555 delaware ave buffalo ny"
  expect_action: drop
  source: "Owners visibly unrelated; agent address per NYS DOS"
```

Target ~50 labels initially: a mix of clear true merges (sourced from press
coverage and court filings) and clear service-address pools (registered agent
addresses, large CPA firms, mass property managers).

### 2B. Validation runner

New file `pipeline/validation/run.py`:

- Loads `labels.yaml`
- Loads the latest emitted clusters and operator slugs
- For each `true_merge`, checks that the expected LLCs land in the same
  cluster and that the confidence label meets `expect_confidence`
- For each `false_positive_pool`, checks the cluster was dropped (or scored
  low) per `expect_action`
- Computes precision and recall at each confidence threshold
- Computes a calibration table: for clusters scored *high*, what fraction of
  the labeled-positive cases are recovered; for clusters scored *low*, what
  fraction of labeled-negative cases stayed dropped or low

Wired into `pipeline/run.py` as a final step. Failure modes are reported but
non-fatal — a labels-file mismatch shouldn't break a data refresh.

### 2C. Surface calibration to readers

Extend `meta.json` with a `validation` block:

```json
"validation": {
  "labeled_true": 42,
  "labeled_false": 12,
  "precision_at_medium_or_higher": 0.95,
  "recall_at_medium_or_higher": 0.88,
  "calibration": {
    "high":   {"true_positive": 18, "total": 19},
    "medium": {"true_positive": 14, "total": 18},
    "low":    {"true_positive": 4,  "total": 5}
  },
  "ran_at": "..."
}
```

Frontend (`web/index.html:47` colophon area): add a small disclosure
"Calibration: of clusters scored high-confidence, X of Y match labeled
ground truth." Clicking expands the full table with definitions.

## Out of scope for this cycle

- Reader feedback channel (mailto, GitHub issue link)
- Automated freshness alerting / CI-driven refresh
- Per-cluster reader review or override
- Calibration-driven retuning of cluster thresholds (deferred until enough
  labels exist to draw conclusions)

## Verification

**Stage 1:**

- `cd pipeline && pytest` — existing suite green; new tests asserting the
  `audit` block shape on a fixture cluster
- `python pipeline/run.py` — emits the new `*_max_date` and `audit` fields
- `cd web && python -m http.server 8000` — pick a known medium-confidence
  operator, confirm the disclosure exists, is collapsed by default, and
  reveals shared mailing + member LLCs + cohesion line on expand. Confirm
  the 311 panel shows the red "frozen 2024-05" pill.

**Stage 2:**

- `pytest pipeline/validation/` — runner correctly scores a fixture labels
  file (one true merge that's present, one false positive that was dropped)
- `python pipeline/run.py` — `meta.json` gains a non-empty `validation` block
- Frontend colophon shows the calibration line; expanding shows the table

## Critical files

- `pipeline/emit.py:231` — cluster object construction
- `pipeline/join.py:349` — meta dict
- `pipeline/cluster_score.py` — read-only, source of cohesion details
- `pipeline/run.py` — wire validation final step
- `pipeline/validation/` (new) — labels.yaml, run.py, tests
- `web/app.js:368, 725` — landlord page rendering
- `web/index.html:47` — colophon
- `web/style.css` — pill + disclosure styles
