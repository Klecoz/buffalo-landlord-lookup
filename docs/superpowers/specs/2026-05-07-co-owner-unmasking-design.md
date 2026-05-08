# Co-owner Unmasking (Surface-Only)

**Status:** approved design, ready for implementation planning
**Date:** 2026-05-07

## Context

Buffalo Landlord Lookup currently links LLCs into operator clusters using
**only the primary mailing address** of each parcel
(`pipeline/emit.py:_build_operator_clusters`). An audit of the raw data
revealed a clear unused signal: `ADD_OWNER` on parcels.

The NYS GIS parcel layer carries a `PRIMARY_OWNER` field (already used)
*and* an `ADD_OWNER` field that names a secondary owner — typically a
human spouse, partner, or co-investor — populated on **26% of parcels**
(24,362 of 93,440), mostly in `Lastname, Firstname` form. Sample values:
`Walton, Gail`, `Smigiera, Sylvia`, `Ort, Donald E`, `Tempestoso,
Erica`, `Jackson-Molenda, Karen`. The pipeline drops this field today.

When the same human appears as a co-owner on parcels in two operator
clusters seeded by different mailing addresses, that is a meaningful
cross-LLC identity link — exactly the kind of unmasking the project
exists to surface. With Stage 1 of the transparency layer in place
(audit disclosure on operator pages), this is the natural next surface
to extend: feed new evidence into the existing UI rather than create
new chrome.

The cycle is intentionally conservative: **surface the signal, don't
auto-merge**. Co-owners common enough to risk false collisions
(`Smith, John` across many unrelated landlords) get suppressed from
cross-cluster links so the evidence stays defensible.

## Approach

### Pipeline

**Parse `ADD_OWNER` during join.**

In `pipeline/join.py:_build_parcel_records` (around the existing parcel
record construction), capture `ADD_OWNER` from the GeoJSON feature
properties. The record gains a single new field, `add_owner` (raw
string, possibly empty).

**Normalize to a co-owner key.**

Reuse two existing helpers in `pipeline/cluster_score.py`:

- `_is_llc_like(name)` — discard `ADD_OWNER` values that look like
  business entities (`SMITH HOLDINGS LLC` etc.). The signal we want is
  human co-owners, not chained LLCs.
- `_person_signature(name)` — already returns
  `frozenset({first_token, last_token})` for human names, handling
  `Smith, John`, `SMITH, JOHN A`, `John Smith`, and `John A Smith`
  uniformly. This is the co-owner key.

If `_person_signature` returns `None`, the value is unkeyable (single
token, garbage, etc.) — skip.

**Build the global co-owner index in `_build_operator_clusters`.**

After clusters are constructed (`pipeline/emit.py:231` region), make a
single pass over each cluster's parcels and assemble:

```python
co_owner_index: dict[frozenset, list[CoOwnerAppearance]]
# CoOwnerAppearance = {operator_slug, operator_label, parcels: int,
#                       sample_display: str}
```

The `sample_display` is one canonical human-readable form preserved
from the raw data (e.g. `Smith, John A`) — used in UI rendering.

**Attach two new fields to each cluster's `audit` block.**

```jsonc
audit: {
  ...,                              // existing fields from Stage 1
  co_owners: [
    { name: "Smith, John A", parcels: 4 },
    { name: "Doe, Jane", parcels: 1 }
  ],
  linked_operators: [
    {
      co_owner: "Smith, John A",
      operator_slug: "...",
      operator_label: "...",
      parcels: 3
    }
  ]
}
```

Sort `co_owners` by `parcels` descending; sort `linked_operators` by
`parcels` descending. Limit each to a reasonable cap (e.g. top 10) to
bound JSON size.

**Common-name suppression for `linked_operators`.**

Any co-owner key appearing in more than **5 distinct operators** is
suppressed from `linked_operators` (it stays in `co_owners` as raw
evidence). This is the noise floor: `Smith, John`-class names across
the whole city would otherwise produce a misleading rats' nest of
links. Threshold lives as a module constant
(`MAX_OPERATORS_PER_CO_OWNER = 5`) so it's easy to revisit.

### Frontend

Extend `renderAuditDisclosure` in `web/app.js`. Inside the existing
`<details class="audit-details">` block, after the Member list and
before the audit-foot, render two new sections **only when populated**:

- **"Co-owners on record"** — `<li>` per entry showing
  `<strong>{name}</strong> <span class="sub">({parcels} parcel{s})</span>`.
- **"Linked operators (via shared co-owner)"** — `<li>` per entry
  showing the other operator's label as a clickable link
  (`onclick="window.openOperator('slug')"`), with the linking co-owner
  as a sub-label.

Reuse the existing `.audit-list` / `.audit-key` / `.sub` styles. No new
CSS classes if avoidable. Empty arrays render nothing (no "no
co-owners on record" placeholder).

Operator pages only this cycle.

## Out of scope

- Auto-merging clusters on co-owner match (deferred — revisit after
  observing how the surface-only signal performs).
- Adding `ADD_MAIL_ADDR` as a clustering seed (separate cycle).
- Demolition `applicant` mining (signal-to-noise too poor for a first
  pass — 76% of values are demolition contractors, not owners).
- Co-owner surfacing on single-owner portfolio pages.
- A project-wide "top co-owners" overview.

## Verification

**Tests** (`pipeline/tests/test_emit.py` and possibly a new
`pipeline/tests/test_co_owner.py` if the indexing logic moves into its
own module):

- Co-owner key normalization handles `Smith, John`, `SMITH, JOHN A`,
  `John Smith`, `John A Smith` uniformly via `_person_signature`.
- `ADD_OWNER` values matching `_is_llc_like` are skipped.
- A fixture with `ADD_OWNER = "John"` (single-token) is unkeyable and
  skipped without error.
- Common-name suppression: a fixture where co-owner key X appears in 6
  distinct operators — confirm X does NOT appear in any
  `linked_operators` field, but DOES appear in the per-cluster
  `co_owners` field.
- Cross-cluster linking: a fixture with 2 clusters seeded by different
  mailing addresses, both carrying `ADD_OWNER = "Smith, John A"` — both
  clusters end up referencing each other in `linked_operators`.

**End-to-end:**
- `python pipeline/run.py` — completes; `meta.json` unchanged in shape;
  at least some `web/data/operators/*.json` files contain a non-empty
  `audit.co_owners`.
- Browser smoke (operator with multi-LLC ownership): expand the audit
  disclosure, confirm "Co-owners on record" appears with parcel counts;
  for an operator that shares a co-owner with another, confirm
  "Linked operators" shows clickable links.

## Critical files

- `pipeline/join.py` — `_build_parcel_records` carries `add_owner` into
  parcel records.
- `pipeline/emit.py` — `_build_operator_clusters` builds the co-owner
  index and attaches `co_owners` / `linked_operators` to each cluster
  audit block.
- `pipeline/co_owner.py` (new, optional) — extract the indexing logic
  here if it grows beyond a small inline block.
- `pipeline/cluster_score.py` — read-only; supplier of
  `_person_signature` and `_is_llc_like`.
- `web/app.js` — `renderAuditDisclosure` gains two new render sections.

## Status

Spec approved. Hand off to `superpowers:writing-plans` to produce the
implementation plan.
