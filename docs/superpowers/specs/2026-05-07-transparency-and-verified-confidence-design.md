> **Status:** Shipped — see git log around 2026-05. Stage 2 (validation set + calibration disclosure) was descoped and is no longer planned. This file is kept for historical context only and is NOT a live roadmap item.

# Transparency Layer

**Date:** 2026-05-07

## Context

Buffalo Landlord Lookup is a civic-data tool that names real people and groups
LLCs into "operator" clusters using heuristic mailing-address clustering plus
cohesion scoring (`pipeline/cluster_score.py`). It is intended to be defensible
to outside civic readers — local journalists, tenant organizations, curious
neighbors — not just personal use.

Three trust gaps blocked that audience when this design was written:

1. **Confidence is unverified.** The pipeline emits high/medium/low labels and
   a one-line evidence string.
2. **The audit trail is too thin.** Today the cluster panel shows one short
   string ("5 of 8 owners share 'acme'"). A skeptical reader can't see *which*
   LLCs were merged, *which* mailing address linked them, or what other
   signals fired (alter-ego matches, person-name dedups).
3. **Freshness caveats are buried.** The README explains 311 froze in 2024-05,
   but a reader landing on a landlord page sees panels of 311 data with only
   a single global "refreshed YYYY-MM-DD" line in the colophon. Per-source
   freshness isn't visible where the data is.

The thesis: a reader of a landlord page should be able to answer two
questions without leaving the page — *who exactly is in this group and why*,
and *how fresh is this data and what's known stale*.

## Transparency UI (shipped)

### Per-source freshness pills

`meta.json` carries a max-observed date for every data source the UI shows
(`code_violations_max_date`, `complaints_311_max_date`, `generated_at`).

A small pill component renders inline next to each data-panel header on
landlord and parcel pages:

- **Green ("current")**: max date within 30 days of `generated_at`
- **Amber ("aging")**: 31–180 days
- **Red ("stale" + explicit copy)**: more than 180 days, OR a known-frozen
  dataset (the 311 case)

Special-case copy for 311 when `generated_at - complaints_311_max_date >
180d`: "Buffalo's 311 dataset (`whkc-e5vr`) stopped updating May 2024. The
12-month window below ends at the dataset's max date, not today."

### "How these names are grouped" disclosure

Each cluster carries a structured `audit` block alongside the existing
`evidence` string:

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
  alter_ego_links: [...],
  person_dedups: [
    { canonical: "John A Smith",
      variants: ["JOHN SMITH", "JOHN A. SMITH", "J A SMITH"] }
  ]
}
```

On operator landlord pages, a `<details>` disclosure titled "How these names
are grouped" (collapsed by default) shows shared mailing address, merged
LLCs, cohesion explanation, alter-ego matches, and person-name dedups.

For non-operator owner pages: a short single-line variant — "This is a single
owner — no LLC grouping applied." — so readers know absence of the panel is
intentional, not a bug.

## Critical files (as of ship)

- `pipeline/emit.py` — cluster `audit` block construction
- `pipeline/join.py` — per-source `*_max_date` in `meta.json`
- `pipeline/cluster_score.py` — source of cohesion details
- `web/app.js` `renderAuditDisclosure`, `freshnessPill` — landlord page rendering
- `web/index.html` colophon
- `web/style.css` — pill + disclosure styles
