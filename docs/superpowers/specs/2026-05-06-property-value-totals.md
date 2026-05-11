> **Status:** Shipped — see git log around 2026-05 (`feat: total property value per landlord, with new "Value" leaderboard tab`). This file is kept for historical context only and is NOT a live roadmap item.

# Total Property Value per Landlord

## Context

Owner and operator leaderboards rank by counts (properties, violations, complaints). The data also has assessed/market value per parcel, but it isn't surfaced. Total dollar value gives a complementary lens — "who owns the most *valuable* empire in Buffalo?" — and turns the operator-clustering finding from a count statistic into a financial one.

The NYS parcel layer has `TOTAL_AV`, `LAND_AV`, and `FULL_MARKET_VAL` per parcel, with 99.6% non-zero coverage on Buffalo's roll. `TOTAL_AV` and `FULL_MARKET_VAL` are equal here (Buffalo assesses at 100% of market), so we use a single `full_market_val` field.

Citywide stock totals to **$27.8B**.

## Pipeline changes

- `pipeline/join.py` — `_build_parcel_records` adds `full_market_val: int` to each parcel record (defaults to 0 for missing).
- `pipeline/emit.py` —
  - During the per-owner aggregation loop, sum `parcel.full_market_val` into `by_owner[norm].total_value`.
  - In `_build_operator_clusters`, sum `total_value` across constituent owners into the operator's `total_value`.
  - Per-record output (owner portfolios, operator portfolios, leaderboard entries) gains `total_value: int`.
  - Both `top_owners.json` and `top_operators.json` get a new `by_value` ranking, ranked descending by `total_value`.

## Frontend changes

- `web/app.js` — new currency helper `fmtMoney(n)` produces `$28.5M`, `$1.2M`, `$340K`, `$1.2B`.
- New leaderboard tab "Value" alongside existing 4. Tab metadata in the `BOARDS` array adds `{ key: "by_value", label: "Value", stat: "total_value", statLabel: "" }` and renders the stat through `fmtMoney`.
- New stat tile "Portfolio value" on owner portfolio (`renderPortfolio`) and operator view (`renderOperator`), adjacent to the existing tiles. Uses `fmtMoney`.
- Leaderboard rows: sub-line unchanged (kept terse); only the `Value` tab's right-aligned stat shows dollars.

## Tests

- `pipeline/tests/test_emit.py` — extend `_owner_agg` test helper to include FMV; add a clustering test that verifies the operator's `total_value` is the sum across constituent owners.

## Verification

1. `cd pipeline && .venv/bin/pytest` — all green.
2. `.venv/bin/python run.py --no-fetch` — outputs include `by_value` arrays in both `top_owners.json` and `top_operators.json`.
3. `curl localhost:8000/data/top_operators.json | jq '.by_value[0]'` — top result should be a recognizable operator with a multi-tens-of-millions `total_value`.
4. Open a portfolio in the UI; the "Portfolio value" stat displays formatted currency.

## Out of scope

- Per-parcel value display on the map / dossier (could be added cheaply later but not part of this change).
- Land vs. building value breakdown.
- Inflation-adjusted historical values (we only have the current roll).
- Filtering parcels by value range (no slider yet).
