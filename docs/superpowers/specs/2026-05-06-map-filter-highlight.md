> **Status:** Shipped — see git log around 2026-05 (`feat: map filter — highlight an owner or operator's parcels`). This file is kept for historical context only and is NOT a live roadmap item.

# Map Filter — Highlight an Owner or Operator's Parcels

## Context

Buffalo Landlord Lookup surfaces operator/owner portfolios as text counts ("INCT Holdings + 11 LLCs / 312 properties / 930 open violations"). The LLC-unmasking feature exposed how concentrated certain operators' holdings are, but the user cannot *see* the constellation today. This change adds a "Highlight on map" toggle on owner-portfolio and operator views that dims every other parcel and fits the map to the highlighted constellation. Smallest effort, biggest visual payoff.

## Architecture

- **One pipeline change**: each feature in `web/data/properties.geojson` already carries `owner_slug`. Add `operator_slug` populated from the existing `owner_to_operator` mapping in `pipeline/emit.py`. While we're touching emit, also add `owner_slug` to `address_index.json` entries so the frontend can compute owner-mode bbox without scanning all 93k features.
- **Frontend**: state lives on `state.mapFilter = { kind, slug, label } | null`. No data refetch — pure MapLibre `setFilter` against the in-memory parcel source.
- **No backend, no new artifacts.**

## Map layer behavior

When `state.mapFilter` is null → behavior unchanged.

When set:
1. Show a new layer `parcels-dim-fill` (added once at map-init, hidden by default) drawn *below* `parcels-fill`. Flat dark gray, low opacity. Acts as the "everything else is dimmed" backdrop.
2. Apply `setFilter` to existing layers `parcels-fill` and `parcels-outline` so they render only matching features.
3. Fit map bounds to matching features by walking in-memory data (`address_index` for owner mode; the loaded operator's `properties` array for operator mode). Cap zoom at 17.
4. `parcels-selected` (orange click ring) keeps drawing on top.

When cleared: reset filters to all polygons, hide dim layer, preserve user's pan/zoom.

## UI

- **"Highlight on map" button** in:
  - `renderPortfolio()` — between the operator CTA and the property table.
  - `renderOperator()` — between the stat tiles and the constituent-LLCs section.
  - Label flips to "✓ Highlighted on map" with `.cta.toggled` style when active for the current view.
- **Filter chip** (`#filter-chip`) in `index.html`, positioned near the search box. Reads "Showing only [Label] · N parcels · Clear ✕". Click anywhere clears the filter.

## Files to modify

- `pipeline/emit.py` — add `operator_slug` to each `properties.geojson` feature; add `owner_slug` to each `address_index.json` entry.
- `web/app.js` — `state.mapFilter`, `applyMapFilter()`, `clearMapFilter()`, `_highlightedBbox()`, the toggle buttons in the two render fns, chip wiring, the `parcels-dim-fill` layer in `initMap()`.
- `web/index.html` — `<div id="filter-chip" class="hidden">`.
- `web/style.css` — `#filter-chip`, `.cta.toggled`.

## Existing utilities to reuse

- `_build_operator_clusters()` returns `owner_to_operator` already in scope at the feature-builder loop in `emit()`.
- `state.addressIndex` in `app.js` — already loaded on boot; gains `owner_slug` per entry.
- The operator portfolio JSON loaded by `openOperator()` already contains `lat/lng` per parcel; reused for operator-mode bbox.
- The `#reopen-panel` chip style language for `#filter-chip`'s look.

## Verification

1. `pytest` — all 58 still green (purely additive pipeline change).
2. `.venv/bin/python run.py --no-fetch` — emit runs in ~30s. Spot-check `properties.geojson` features for non-null `operator_slug` on parcels owned by a clustered owner (e.g., JLT, NADM, INCT).
3. `python3 -m http.server 8000` → click Operators tab → INCT Holdings → "Highlight on map" → 312 parcels lit, rest dim, map flies to fit, chip shows "Showing only INCT Holdings … · 312 parcels".
4. Switch operators (Allentown) → highlight migrates.
5. Open an owner portfolio (JLT) → highlight on map → drops to JLT's 71 parcels.
6. Search a random address while filtered → dossier opens, filter persists.
7. Clear chip → default coloring restored.

## Out of scope

- Multi-filter / compare two operators on one map.
- Lasso / draw-region filtering.
- Animated transitions when filter changes.
- Persisting filter across reloads.
- Per-parcel hover tooltips.
