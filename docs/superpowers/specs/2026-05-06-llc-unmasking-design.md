# LLC Unmasking via Mailing-Address Clustering

## Context

The v1 leaderboards rank by *normalized owner name*. They surface real signal — JLT Real Estate LLC's 314 open violations, NADM's 232 — but they treat each LLC as a distinct entity. In practice, a single operator often holds property under multiple LLCs (JLT Real Estate, JLT Holdings, Smith Properties LLC, etc.). On paper the entities differ; in reality they all mail their tax bills to the same office or PO box.

The NYS parcel layer already includes mailing fields (`MAIL_ADDR`, `MAIL_CITY`, `MAIL_STATE`, `MAIL_ZIP`, `PO_BOX`). Clustering owners by normalized mailing address can merge those entities into a single "operator" view — without scraping the NYS Department of State.

This is not a perfect signal: lawyers, registered agents, and property managers handle mail for many unrelated owners. The design must avoid over-merging.

## Data model — two layers

| Concept | Definition | Source |
|---|---|---|
| **Owner** (existing) | Unique normalized owner-name string. Each parcel has exactly one. | `PRIMARY_OWNER` → `normalize_owner` |
| **Operator** (new) | Cluster of owners sharing a normalized mailing address, that meets clustering rules. May contain 0 or more owners. | mailing-address grouping |

Owners that don't qualify for any operator (solo LLCs, owner-occupied, unmappable) simply have no operator membership. The owner record stays unchanged.

## Clustering rules

Three rules, in order:

1. **Drop generic mailing addresses.** If a normalized mailing address is shared by more than **30 distinct `owner_norm`s**, treat it as a service provider (lawyer, agent, manager) and refuse to cluster on it. Threshold is configurable.
2. **Drop self-mailing parcels from cluster signal.** When a parcel's mailing address equals its `LOC_ADDR` (owner-occupied), the mailing address is not used for clustering. Owner stats still include the parcel.
3. **Require multi-LLC + meaningful size.** A cluster must contain ≥**2** distinct `owner_norm`s **and** ≥**3** total parcels across the cluster.

Operators inherit the existing leaderboard skip-list (city / county / state / federal owners). If a cluster contains a skipped owner_norm, the entire cluster is skipped.

## Mailing-address normalization

New function `normalize_mail_address(addr, city, state, zip_code, po_box)` in `pipeline/normalize.py`:

- PO box variants ("PO Box 123", "P.O. Box 123", "POB 123", "Box 123") → canonical `PO BOX 123`
- Street addresses run through the existing `normalize_address`
- Output is a single key: `"PO BOX 1234 | AMHERST | NY | 14226"` (city/state/zip prevent cross-town collisions when the same street exists in multiple municipalities)
- `normalize_address` already strips apartment/unit identifiers — that's fine; the goal is to merge LLCs that share an office, not to disambiguate suite numbers.

## Operator label

The operator's display string is the most-frequent `owner_display` across the cluster, with a `(+N more LLCs)` suffix. Tie-breaking on owner display: alphabetical. The mailing address itself is shown separately as the *reason* the cluster was formed.

## Pipeline outputs

New artifacts emitted by `pipeline/emit.py`:

```
web/data/
├── operators/<slug>.json     # Per-operator portfolio
├── top_operators.json        # Ranked operators across 4 categories
└── owners/<slug>.json        # (existing) — gains operator_slug field
```

`operators/<slug>.json` shape:
```json
{
  "operator_slug": "...",
  "operator_label": "JLT Real Estate LLC (+2 more LLCs)",
  "mailing_address": "PO BOX 1234 | AMHERST | NY | 14226",
  "owners": [
    { "slug": "jlt-real-estate-llc", "display": "JLT Real Estate LLC", "properties": 71, "open": 314, "all_violations": 732 },
    ...
  ],
  "total_properties": ...,
  "total_open_violations": ...,
  "total_all_violations": ...,
  "total_complaints_311_12mo": ...,
  "properties": [ /* same shape as owner-portfolio properties */ ]
}
```

`top_operators.json` shape mirrors `top_owners.json`: four arrays (`by_open_violations`, `by_all_violations`, `by_properties`, `by_complaints_311`), each with the top 20 operators.

## Frontend integration

Three changes in `web/`:

1. **5th leaderboard tab "Operators"** — defaults to ranking by total open violations. Same row pattern as existing leaderboards; click → operator view.
2. **New operator view** — `renderOperator(operator)` shows label, mailing address, aggregate stats, **constituent LLCs section** (each clickable to its existing owner portfolio), property table. Includes a disclaimer: *"These owners share a mailing address, which often (but not always) means a single operator. Click any LLC to see it on its own."*
3. **Owner-portfolio CTA** — when an owner has an `operator_slug`, show "Same mailing address as N other LLCs →" linking to the operator view. Mirrors the existing portfolio CTA on the parcel dossier.

Hash route `#/operator/<slug>` lives alongside `#/parcel/<id>` and `#/owner/<slug>`. The map is unchanged for v1; "highlight only this operator's parcels on the map" is deferred.

## Files to modify

- `pipeline/normalize.py` — add `normalize_mail_address`
- `pipeline/tests/test_normalize.py` — add cases for PO box variants, composition
- `pipeline/join.py` — capture mailing fields onto each parcel record (`mail_addr`, `mail_city`, `mail_state`, `mail_zip`, `po_box`, `is_owner_occupied`)
- `pipeline/emit.py` — build operator clusters during the existing owner emit loop; emit new artifacts; print top-5 operators sanity check
- `pipeline/tests/test_emit.py` — add clustering-rule cases
- `web/index.html` — no structural changes
- `web/app.js` — operator tab in `renderLeaderboards`, new `renderOperator`, owner-CTA on portfolio, hash route handler
- `web/style.css` — operator-view styles reuse leaderboard / portfolio classes; minor additions for the constituent-LLC sub-list
- `README.md` — note the new "operators" concept and skip thresholds

## Verification

1. `cd pipeline && .venv/bin/pytest` — all green, with new tests for `normalize_mail_address` and clustering rules.
2. `.venv/bin/python run.py --no-fetch` — should regenerate all artifacts in ~30s. Output should include "Top 5 operators by property count" sanity print.
3. `curl localhost:8000/data/top_operators.json | jq '.by_open_violations[0]'` — first row should be a real cluster (mail address visible, ≥2 owners).
4. UI smoke: open `http://localhost:8000`, click "Operators" tab → list renders. Click top operator → operator view with constituent LLCs section visible. Click any LLC in that list → owner portfolio loads. Open an owner who's part of a cluster → CTA "Same mailing address as N other LLCs" present and works.
5. Eyeball top operators: do they look like real operators (consistent name pattern, plausible single mailing address) or do they look like noise (random LLCs at a generic PO box)? If noise dominates, tighten Rule 1's threshold from 30 toward 15.

## Out of scope

- Map filters / "highlight this operator's parcels"
- Cross-county clustering (we only have Buffalo data)
- Person-level merging (e.g., Bob Smith with two different home addresses)
- Visual graph of operator → LLC → property
