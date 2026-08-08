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

## 2026-08-07 — LLC matching audit (Item 2)

Audited against the emitted 2026-05-10 dataset: all 65,089 owner records and
all 2,204 operator clusters (25 high + 25 medium sampled by slug stride, all
19 low read in full, plus every PO-box auto-high, every alter-ego, and every
cluster the NYS DOS join flagged as a registered-agent address).

### Heuristics that checked out clean — no code change

- **Business-suffix canonicalization is complete for this roll.** Every LLC /
  LP / LLP / CORP / INC spelling present collapses correctly. The `\bl ?p\b`
  and `\bl ?l ?p\b` patterns share a prefix and the shorter one runs first,
  but the two-pass rewrite still lands "L L P", "L.L.P." and "LLP" on the same
  key.
- **No accent folding is needed.** Zero of 65,089 owner records contain a
  non-ASCII character. `\w` is Unicode-aware, so a name like "José" would
  survive punctuation stripping and simply not match "Jose" — dead code risk,
  not a live bug.
- **"Trustee" → "Trust" is safe here.** 15 owners spell it "Trustee(s)". No
  normalized key is reachable from both a "Trustee" spelling and a
  differently-owned "Trust" spelling, so the fold merges nothing wrong.
- **`\bl ?p\b` does absorb the tail of a spaced-out acronym**: "H.E.L.P.
  Buffalo Inc" keys as `h e lp buffalo inc`. Cosmetic only — both spellings of
  that owner in the roll produce the identical key, so no split and no merge.
  One owner, three parcels.
- **All 19 low-confidence clusters are correctly labelled.** Each is a genuine
  attorney / property-manager / filing-service pool (617 Main St, 266 Elmwood
  Ave, 1580 Genesee St, …) that the UI should show as weak evidence.
- **The alter-ego rule is sound where a real person is involved.** Spot-checked
  30 of 262; the person + LLC pairs at a shared street address are exactly the
  unmasking signal the site exists to surface.
- **The DOS 30–99 "unknown" band is inert by design.** 74 clusters sit in it.
  It neither rescues nor demotes, which is the intended reading of "we have no
  evidence either way" — no threshold tuning warranted.
- **Co-owner noise suppression never fires on real data.** The most widely
  shared co-owner key appears in 3 distinct operators, well under
  MAX_OPERATORS_PER_CO_OWNER = 5. The keys that reach 3 are church-name
  fragments split out of ADD_OWNER ("In Christ", "Non-Trans", "Baptist
  Church"), not common human names. Total cross-cluster links published: 58
  across 42 clusters. Lowering the threshold would suppress genuine
  two-operator human links and still miss these, so the threshold stays.

### Confirmed defects, fixed

- **`&` and "and" never met.** Punctuation stripping deletes "&" and "+" but
  keeps the spelled-out "and", so "Karim & Karim LLC" and "Karim and Karim
  LLC" were two owners. 17 real pairs in the roll, 34 owners, 69 parcels —
  and, checked exhaustively, no unrelated names collide when "and" is dropped.
  The cohesion scorer already treated "and" as a stopword, so the two layers
  disagreed about whether the word carried identity.

- **Organization names were being read as people.** `_LLC_MARKER_RE`
  recognizes only the abbreviated legal forms, so 150 owner displays ending in
  "Corporation", "Incorporated" or "Company" — and every organization with no
  legal suffix at all — fell through to `_person_signature` and got a bogus
  {first, last} key. Two consequences, both confirmed in the emitted set:
  28 of the 262 alter-ego clusters were pairs of *companies*, not a person and
  an LLC ("Acme Bearings Corporation" + "Acme Bearing Corp"); and four
  organization pairs were merged into one owner because their first and last
  tokens agreed — "St Clare Apartments" with "St Patrick Village Apartments",
  "SRK 2020 Elmwood Associates" with "SRK 770 Elmwood Associates", "St John
  Townhomes II Housing" with "St Martin Village Housing", "Peninsula Property
  Holdings" with "Peninsula Wholesale Holdings".

- **A trailing middle initial made a person unkeyable.** The roll writes
  people both as "Adkins, Cassandra" and as "Adkins Cassandra C". Without the
  comma, `_person_signature` took the last token as the surname, saw a
  one-character initial and returned None — so the two spellings never merged,
  even though the comma form has always ignored middle initials. 8,148 owner
  displays were affected; dropping trailing initials merges person variants in
  133 clusters and splits none.

### Known limitations, measured but deliberately not fixed

- **A two-owner cluster can never score below 0.5.** The cohesion formula is
  "fraction of owners sharing the top token", so with n=2 the floor is 1/2 and
  the evidence string reads "1 of 2 owners share 'x'" — which is no evidence.
  Street pairs land in the medium band anyway, so the score is not misleading
  in the UI, but the evidence sentence is weaker than it looks.
- **Business-suffix inconsistency splits 159 owner groups** (325 owners, 990
  parcels) where the same base name appears with and without a suffix, or with
  a different one: "Nightfall Enterprises Inc" vs "Nightfall Enterprises LLC",
  "Madonna of the Streets" vs "Madonna of the Streets Inc". Operator
  clustering already reunites 69 of those groups (478 parcels); 90 groups /
  512 parcels / ~0.55% of all parcels stay split. Not fixed: stripping the
  suffix from the matching key would merge legally distinct entities ("Howlader
  Corp" and "Howlader Inc" are separate filings), and that is a worse error
  than the split for an accountability site.
- **The mailing-address key includes both city and ZIP, and the roll is
  inconsistent about both.** 3842 Harlem Rd 14215 appears as both "BUFFALO"
  and "CHEEKTOWAGA" and forms two separate clusters
  (`m-perets-industries-llc`, `first-services-inc`) at one physical address —
  which also splits the NYS DOS entity count for that address across two keys.
  237 Main St appears under both 14202 and 14203 for the same reason. Dropping
  either component would fix one split and cause another (same street number
  in two towns), so the key is unchanged.
- **The assessment roll truncates owner names at 30 characters.** "Niagara
  Frontier Transportatio", "Geleynse Whelchel Family Livin", "Highland
  Properties of Bflo.In". These split at the owner level and are re-joined
  only by the operator layer.
