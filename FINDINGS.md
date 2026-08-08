# Findings

Facts about this system discovered while working on it — root causes, surprises,
dead ends. Not a changelog; see git history for that.

## 2026-08-07 — planning audit (pre-implementation)

- **"Demolished" is heavily over-flagged.** 8,342 of 93,069 parcels (~9% of the
  city) carry `demolished=true`. The join (`pipeline/join.py::_join_demolitions`)
  matches only the permit's normalized full address and ignores its `sbl` and
  `issued` fields; permits span 2000–2026 (only ~460 since 2020), and a 2006
  permit flags a parcel exactly like a 2026 one. Every flag adds +5 concern
  score and the dark-red map color.
- **The permit `sbl` field is a usable join key.** Right-padding it with zeros
  to 20 chars matches a current parcel SBL for 8,549 of 10,661 permits that
  carry one. The parcel layer also has corroboration fields: `PROP_CLASS`
  (3xx = vacant land), `LAND_AV` vs `TOTAL_AV`, `YR_BLT`; assessment roll year
  is 2025.
- **The demolition permit feed itself lags** — the current pull contains only
  2 permits dated 2026.
- **Owner matching is exact-string end to end.** No fuzzy matching anywhere:
  suffix canonicalization (`normalize_owner`), shared-mailing-address
  clustering, token-cohesion scoring, person-name signature (frozenset of
  first+last token). Known gap: `&` is stripped to a space while "and" is kept,
  so "A&B LLC" and "A and B LLC" never merge.
- **XSS is mostly covered** by `escapeHtml` (web/app.js:36), applied
  consistently in HTML contexts. Residual weakness: entity escaping inside
  inline `onclick="fn('${escapeHtml(x)}')"` JS-string contexts (app.js:101,
  489, 674, 693, 1086, 1146, 1185) — the browser decodes entities before JS
  parses the attribute, so escaping there is the wrong layer. The effective
  defense is the emitter's slug alphabet, to be verified.
- **The 311 feed is frozen upstream at 2024-05-10.** The pipeline correctly
  anchors its "12-month" complaint window to the feed's own max date, not
  wall-clock today — but any UI copy saying "last 12 months" is misleading.
- **Web vitest suites mock `fetch`** (web/tests/setup.js), so regenerating
  web/data does not break them; string-asserting tests do break when UI copy
  changes.
- **The visual layer has no AI-slop markers**: one functional gradient, no
  emoji, three functional box-shadows, square corners, Hanken Grotesk + IBM
  Plex Mono, reduced-motion respected. The de-slop pass is prose-focused.
- Baseline `meta.json` (2026-05-10): parcels 93,069 · owners 65,089 · clusters
  {high 1330, medium 855, low 19, dropped 4} · violations matched 220,068 ·
  demolitions matched 8,342.
