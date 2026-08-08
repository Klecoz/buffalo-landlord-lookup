# Decisions

Choices made and why, with rejected alternatives. Newest first.

## 2026-08-07 — Drop the conjunction "and" from owner keys

`normalize_owner` deletes the standalone token "and", matching what
punctuation stripping already does to "&" and "+". Measured across all 65,089
owner records: 17 groups merge, every one of them a genuine `&`/"and" spelling
pair of the same owner ("Karim & Karim LLC" / "Karim and Karim LLC",
"Zenner & Ritter Inc" / "Zenner and Ritter Inc"), 34 owners and 69 parcels in
total, with zero collateral merges of unrelated names. Rejected: canonicalizing
"&" → "and" instead (same merges, but every existing key changes and the "+"
spelling still misses); leaving the gap open (it is a pure false split, and
"and" was already a cohesion stopword, so the two layers disagreed).

## 2026-08-07 — Demolished = permit + currently-vacant parcel

Redefine `demolished` as: a demolition permit matches the parcel (SBL-first,
address fallback) AND the 2025 assessment roll reads vacant (`PROP_CLASS` 3xx
or `TOTAL_AV <= LAND_AV`). Concern-score bump only when the permit is <5 years
old. Rejected: keeping the permit-only flag (9% of the city flagged, mostly
decades-old); pulling a new "completed demolitions" dataset (none is published);
inferring completion from permit fees/inspections (fragile, complex).

## 2026-08-07 — Single atomic deploy at the end of the effort

The demolished redesign changes the data schema (`demo_permit`), so data and
site must ship together; deploying either alone renders wrong. Rejected:
deploying the data refresh as soon as it lands (would pair new data with a
frontend that doesn't render the new fields).

## 2026-08-07 — Pipeline-logic fixes land before the dataset refresh

The full fetch+join+emit+deploy cycle is expensive (~hours end to end for 67k
files), so matching/demolition fixes merge first and the cycle runs once.
Raw-data download is prefetched in parallel since it doesn't depend on pipeline
logic; if the bug hunt finds a fetch bug, affected datasets are refetched.

## 2026-08-07 — Simplicity over abstraction (standing)

No fuzzy matching, no config systems, no frameworks/bundlers, no module splits
unless they clearly read better. Thresholds are hardcoded with comments.
