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

## 2026-08-07 — Demolished redesign, measured (Item 3)

Numbers below are from the 2026-08-07 raw pull (93,440 parcel features →
93,069 addressable parcels, 10,822 demolition permits), so they replace the
May-dataset figures in the planning audit above.

- **The flagged count falls from 8,128 to 6,720.** 8,128 is what the old
  address-only rule produces on today's data (8,342 was the May pull). The new
  rule matches more permits — 8,979 of 10,822, up from address-only — but only
  6,720 parcels survive the vacancy check.
- **SBL carries the join; address is a thin fallback.** 8,560 permits matched
  by padded SBL, 419 by address, 1,843 matched nothing. Where a permit's SBL
  and its address both resolved, they disagreed on only **6** permits — so the
  old address matching was substantially right about *which* parcel, and wrong
  about *what a permit means*.
- **2,020 parcels hold a demolition permit and still assess as improved
  buildings.** These are the false positives the old flag was publishing. 77 of
  them have 2025-or-later permits, which is expected: the permit was pulled and
  the building is genuinely still standing (or was, as of the roll).
- **The vacancy corroboration lags the permit by about a year.** No parcel
  reaches `demolished` on a 2025 or 2026 permit — the assessment roll is roll
  year 2025 and hasn't caught up. The demolished-parcel permit histogram runs
  ...2022: 55, 2023: 53, 2024: 49, then stops. So the freshest demolitions
  render as "permit issued, building present" until the next roll. This is the
  honest reading of the data we have, not a bug, but it means the display is
  structurally a year behind reality.
- **The concern-score contribution nearly vanishes: 172 parcels, down from
  8,128.** 395 parcels have a permit inside the 5-year window; only 172 of those
  also read vacant (the roll lag above). The other 6,548 demolished parcels
  still colour the map dark red but contribute 0 to the score. The +5 term is
  now a rare signal rather than a background hum across 9% of the city.
- **The permit feed is fresher than the May pull suggested.** Max issued date is
  2026-07-13 (the May pull had only 2 permits dated 2026); 77 permits are dated
  2025 or later.
- **MapLibre only carries primitives in feature properties.** A parcel opened
  from the map comes out of `queryRenderedFeatures`, and any object-valued
  property is handed back JSON-stringified — so `demo_permit` arrives as an
  object from owner JSON and as a string from the map. `app.js::demoPermit`
  accepts both rather than the emitter shipping two shapes.
- **361 parcels have no assessment at all** (`LAND_AV` and `TOTAL_AV` both 0),
  exactly the set whose `PROP_CLASS` is also empty. They are excluded from the
  value-based vacancy test on purpose — a blank roll record is silence, not
  evidence of an empty lot.

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

- **The PO-box auto-trust branch trusted boxes with no business in them.**
  18 clusters reach the "n <= 8 owners sharing one PO box → high" rule. Two of
  them contain no business entity at all: PO BOX 90417 Rochester
  (`al-wuhaib-najat-bader-e-h`, three unrelated surnames) and PO BOX 1054
  Williamsville (`ulman-efraim`, five). Both look like a mail drop or an
  escrow/tax-servicer lockbox pooling unrelated homeowners, and both were
  published at high confidence under an evidence string that literally called
  them LLCs. Note that a mortgage escrow address reaches the clustering layer
  precisely because it differs from the property address, so the
  non-self-mail filter does not catch it.

- **The registered-agent detection never counted against anything.** The
  NYS DOS join classifies a mailing address as `registered_agent` at >= 100
  businesses, and the constant's own comment calls that "counter-evidence to
  the 'real shared owner' hypothesis" — but the only place the classification
  was read promoted low → medium on a *clean* address. A pool address could
  not demote. 25 clusters carry the flag; 17 of them shipped at medium
  confidence, including 90 State St Albany (19,467 businesses — the busiest
  filing-service address in New York), 418 Broadway Albany (89,862), 1220 N
  Market St Wilmington (307, a Delaware agent) and 99 Wall St New York
  (2,060). Together 159 parcels across 77 member owners.

### Net effect of the five fixes

Replaying the new classification over the emitted clusters with their member
lists held fixed moves 44 of 2,204 clusters (2%): high 1,330 → 1,321, medium
855 → 847, low 19 → 36. Seventeen mediums drop to low (the registered-agent
pools), fourteen highs drop to medium (organization pairs that were posing as
alter-egos, plus the two person-only PO boxes), and eight mediums rise to high
— genuine person + LLC alter-egos that the trailing-initial bug had hidden.
Owner-level membership will shift a little further once the `&`/"and" merge is
applied at the next full run.

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

## 2026-08-07 — Pipeline bug hunt (Item 4)

- **Socrata paging without `$order` silently dropped 8,956 code violations
  (3.6%) from today's pull.** `fetch.py::_socrata` requested `$limit`/`$offset`
  windows with no `$order`. SODA gives an unordered query no stable row order,
  so consecutive windows get sliced out of differently-sorted result sets: the
  total row count comes out exactly right (250,586, matching
  `select count(1)` on the server) while 8,956 distinct `uniquekey`s are absent
  and 8,956 other rows appear twice. The exact-duplicate row count and the
  missing-key count matching at 8,956 is the fingerprint. Verified by pulling
  all 250,586 `uniquekey`s from the server *with* `$order=:id` and diffing
  against the local file. The 311 (4 pages) and demolition (1 page) pulls
  happened to come through intact — it is luck, not a property of those
  datasets. Fixed by sending `$order=:id` on every page.
- **ArcGIS paging advanced the offset by the page size it asked for, not the
  page size it got.** `resultRecordCount` is a ceiling: a server is free to
  return fewer rows and set `exceededTransferLimit`, and every row in the
  shortfall would have been skipped. Latent, not triggered: the NYS
  Clearinghouse layer reports `maxRecordCount: 50000`, well above the
  ARC_PAGE=1000 we request, so it returns full pages. Today's parcel pull is
  complete — `returnCountOnly` on the live service reports exactly 93,440
  features for `MUNI_NAME='Buffalo'`, matching `raw/parcels.geojson`.
- **The code-violation SBL fallback was documented but never implemented.**
  `join.py`'s module docstring has always described the violations join as "by
  normalized address (then SBL fallback)"; `_join_violations` only ever tried
  the address. 228,379 of 250,586 violations carry a usable 16-char `sbl`, and
  on the 2026-08-07 pull the fallback recovers 18,589 of the 21,460 rows the
  address join misses — 7.4% of the whole feed, previously absent from every
  owner's portfolio and concern score. Only 73 of 229,126 address matches
  disagree with the row's SBL, so address-first/SBL-second is safe; only 2,871
  violations now match nothing at all.
- **SBL matching is shared between the violations and demolitions joins**
  (`_sbl_lookup`). Source feeds carry the 16-char base SBL; the parcel roll
  carries base+4-digit sub-parcel suffix for 93,079 parcels and the bare
  16-char form for 354, so both spellings are tried. Values under 16 chars are
  truncated junk (16,131 violations have a 5-char `sbl`) and are rejected —
  padding them would manufacture matches.
- **17-char SBLs never match, and are left that way.** 252 violations and 22
  demolition permits carry a 16-char base plus a trailing letter
  (`1114300011003000A`) — a sub-parcel designation the roll doesn't use.
  Truncating to `[:16]` and padding would match a real parcel for about half
  of them, but that collapses a sub-parcel onto its base parcel on a guess, so
  it isn't done.
- **Every map pin sat off-centre because the centroid averaged the ring's
  closing vertex twice.** GeoJSON repeats a polygon's first vertex to close
  the ring, and `_build_parcel_records` took a plain mean over the raw vertex
  list — so the duplicated corner got double weight, pulling the pin toward it
  by roughly a fifth of the way on a four-corner lot. All 93,440 parcel
  geometries have closed rings, so all of them were affected: median
  correction 2.5m, p99 6.3m, max 34.8m. Small next to a city block, but
  systematic and free to fix.
- **`--no-fetch` against an empty cache died on a bare `FileNotFoundError`**
  raised from inside `join_all`, naming one file and offering no way forward.
  It now preflights all four raw inputs, lists every missing one, and points
  at the command that produces them.
- **An unreadable NYS DOS cache aborted the whole pipeline run.**
  `fetch_and_build_index` treated a fresh-by-mtime file as readable and let
  `json.load`'s `JSONDecodeError` (or a `KeyError` on `payload["index"]` for
  an older payload shape) escape. A truncated cache is exactly what an
  interrupted write leaves behind, and the file is derived data, so it now
  warns and re-fetches. Clock skew is not treated as an error: a cache with a
  future mtime reads as fresh, which is the harmless direction — the next
  scheduled refresh corrects it, and `--force-dos-refresh` overrides.
- **The per-owner violation-type tally was computed from the trimmed dossier
  list, not the full violation set.** `join_all` trims each parcel's
  `violations` to the 25 most recent to bound JSON size, and emit's
  `violation_type_counts` looped over that trimmed list — so 13,333 of 247,715
  matched violations (5.4%) never reached the tally. The loss is not spread
  evenly: it falls entirely on the 1,269 parcels with more than 25 violations
  (up to 241 on one), which are precisely the parcels behind the leaderboard
  entries the tally annotates, and it always drops the *oldest* rows. Now
  tallied in `_join_violations` as the rows go by, before the trim.
- **An over-long owner name would have aborted the entire emit.** A slug is a
  filename and every filesystem we target caps a name at 255 bytes; `_slugify`
  applied no cap, so one long name would raise `ENAMETOOLONG` partway through
  writing 65k owner portfolios, leaving `web/data/` half-written. Not
  reachable from the current source — the assessment roll truncates owner
  names at 30 characters, and the longest real slug is 46 — but the input is
  third-party data and the failure is total, so slugs are now capped at 120
  characters. Collisions the cap could introduce go through the same dedup as
  every other collision.
- **A malformed permit date would have scored as recent.** Both the
  "latest permit wins" pick and the `DEMO_SCORE_YEARS` recency gate order
  `issued` as a plain string, and any non-ISO value sorts above every real
  date (`"not-a-date" > "2021-08-07"`), so it would have won the +5 concern
  bonus. Today's feed is clean — all 10,822 permits parse as `YYYY-MM-DD`,
  spanning 2000-01-03 to 2026-07-13 with none empty and none in the future —
  so this was latent. Malformed values are now blanked at the join and the
  gate checks the shape before trusting the comparison.

### Suspects cleared

- **THE SLUG ALPHABET IS SAFE.** `_slugify` emits strictly `[a-z0-9-]` for
  *any* input, by construction: `re.sub(r"[^a-z0-9]+", "-", name.lower())`
  replaces every character outside the class, the only other character it can
  introduce is the hyphen, and the `or "unknown"` fallback rules out empty.
  Verified against all 65,074 real `owner_norm` values (which produce owner
  slugs) and all 67,455 raw `PRIMARY_OWNER` values (which produce operator
  labels): zero characters outside the alphabet in either set. Also verified
  against adversarial inputs — quote-and-script-tag injections, path
  traversal, NUL and newline, Greek, Cyrillic, an RTL override, a dotted
  capital I (whose `.lower()` yields a combining mark), and emoji.
  **Item 6 may rely on this: a slug interpolated into an inline `onclick`
  cannot carry a quote, angle bracket, backslash, or whitespace.** The
  guarantee is now pinned by tests at both `_slugify` and `emit()` output.
- **Slug collisions are possible but cannot silently overwrite.** Distinct
  names really can collapse to one slug — accents are the cheapest case
  (`josé` and `josë` both give `jos`), and 2,133 groups of raw owner names
  collide, though almost all are punctuation variants of one entity
  ("Klopman Ventures Inc." / "Klopman Ventures, Inc."). Both the owner path
  (`emit()`) and the operator path (`_slugify_unique`) already resolve them
  with a `-2`, `-3` suffix, and the loop re-checks each candidate so a suffix
  can't steal a slug a real name would have earned. Across the 65,074 real
  `owner_norm` values there are **zero** collisions, so no suffix is currently
  in play. The assignment order follows the parcel feed's order, which is
  stable for a given `parcels.geojson` but not pinned across refetches
  (the ArcGIS query sends no `orderByFields`) — moot while collisions are zero.
- **The 12-month 311 window is correct, including the leap-day branch.** The
  window is anchored on the dataset's max `open_date` (frozen at 2024-05-10,
  since the feed stopped updating) rather than today. `anchor.replace(year=...)`
  raises only for a Feb-29 anchor, so the `day=28` fallback fires only then;
  every other date takes the plain path and lands on the same calendar day a
  year earlier. The boundary is inclusive.
- **Per-parcel violation and complaint counts are taken before the trim to
  25.** The counters increment inside the join loops; `join_all` trims the
  dossier lists afterwards. Confirmed by test. (The type *tally* was the
  exception — see the fix above.)
- **Address-index collisions are deterministic and order-independent.** An
  exact normalized address always beats another parcel's no-street-type
  alias regardless of arrival order, because the alias is only written when
  the key is free while the exact key overwrites. Genuinely identical
  addresses (condos) are last-write-wins — arbitrary, but fixed for a given
  input file.
- **Socrata paging handles a row count that is an exact multiple of
  PAGE_SIZE.** The extra request returns zero rows and terminates; no loop,
  no lost tail. The 311 `$where` needs no escaping — neither `DPIS` nor
  `Buffalo Municipal Housing Authority` contains an apostrophe, and `requests`
  URL-encodes the clause. A literal containing one would need doubling.
- **Atomic writes do protect the prior cache.** A failed write leaves the
  previous file byte-for-byte intact and removes the `.tmp` sibling, so a
  broken refetch can't strand a `--no-fetch` run.
- **`_join_311`'s dead client-side filter.** `HOUSING_311_KEYWORDS` and
  `_is_housing_311` are unreferenced — the subject filter moved server-side
  into the `$where`. All 195,004 rows are DPIS (191,728) or BMHA (3,276).
  Left in place; removing dead code is Item 10's call, not a correctness fix.
- **`oldest_violation` is a misnomer, and unused.** It is the *minimum* of
  each parcel's *latest* violation date across the owner's portfolio, which
  is not "the owner's oldest violation". It is emitted in every owner file
  and read by nothing in `web/`.
- **Coordinate precision is not rounded anywhere.** `properties.geojson`
  ships full float geometry straight from ArcGIS, which is most of its 65MB.
  A correctness non-issue; flagged as payload weight for whoever owns the
  emit-size question.
- **`web/data/owners/` accumulates orphans across runs.** emit writes files
  but never removes ones the current run didn't produce, so slugs from an
  older normalization survive. Today's run leaves 72 orphan owner files and 7
  orphan operator files (~45KB) — all from before the Item-2 change that drops
  "and" from `owner_norm` (`adam-mickiewicz-library-and`,
  `andrews-robert-i-and`, …). Harmless to the frontend, which only requests
  slugs named in `properties.geojson`, but they do get uploaded on deploy.
  Left alone here: pruning the directory is an emit change a later item owns.
- **`fetch.py` has no retry.** Timeouts are generous (180s Socrata, 240s
  ArcGIS) but a single transient failure aborts the whole fetch. The atomic
  writes mean the previous cache survives intact, so the recovery is just
  re-running — noted as a robustness gap, not a correctness bug.
- **The ArcGIS query sends no `orderByFields`.** The layer reports
  `supportsPagination: true` and returned exactly the 93,440 features
  `returnCountOnly` promises, so paging is stable in practice. Unlike SODA,
  ArcGIS orders by the OID field by default when paginating. Left as is; the
  consequence if it ever drifts is a reshuffled parcel feed, which only
  matters for slug-collision tie-breaks (currently zero).
- **`parcel_id` is unique across all 93,069 parcel records** (0 duplicates, 0
  empty), so `emit`'s `by_id` map can't drop a parcel or double-count one into
  an owner's aggregate. The 20-char SBL is unique across all 93,440 raw
  features too.

## 2026-08-08 — Dataset refresh (Item 5)

Full canonical run (fetch → NYS DOS refresh → join → emit) with all Item 2–4
fixes in place, 1,214s end to end. `web/data/` is not versioned, so the counts
live here:

- parcels 93,069 (May: 93,069) · owners 65,072 (May: 65,089)
- violations 250,586 total, **247,696 matched (98.8%)** — May matched 220,068;
  the jump is Item 4's SBL fallback + ordered paging recovering rows that were
  always in the source, plus ~3 months of new data
  (`code_violations_max_date` 2026-07-24)
- 311 max date **2024-05-10 — still frozen upstream, as expected**
- demolitions 10,822 permits → 8,979 matched → **6,720 parcels demolished**
  (2,020 more hold a permit over a still-standing building);
  `demolitions_max_date` 2026-07-13
- clusters 2,200: high 1,318 · medium 846 · low 36 · dropped 4
  (May: 1,330/855/19/4 — shifts match the Item 2 fix projections)
- NYS DOS index rebuilt with ordered paging, `nys_dos_max_date` 2026-08-06;
  26 clusters now flagged at registered-agent addresses
- orphaned owner/operator JSON purged (output dirs cleared before emit);
  exactly 65,072 owner + 2,200 operator files remain

Top-10 leaderboards vs the live May site are stable — same operators, counts
up modestly. Only churn in the open-violations board: SRE Management LLC
dropped out of the top 10, Sokolov 94 LLC entered.

NOT deployed — deploy is a single atomic step at the end of the effort
(frontend schema changes must ship with this data).

## 2026-08-08 — Web bug hunt (Item 6)

### Deep links to a parcel never resolved

`selectParcel` read a parcel's properties from `map.querySourceFeatures`,
which only returns features from tiles already loaded *in the current
viewport*. A `#/parcel/:id` URL opened cold — exactly what the dossier's
"Copy link" button hands out — lands on the default city-wide view, matches
nothing, and rendered "Couldn't load that parcel — try zooming in and
clicking again". Every shared dossier link was broken, and the message
blamed the reader's zoom level for a lookup problem.

The address index already carries a centroid for all 93,069 parcels, so the
parcel can be found by jumping the camera there and re-querying once the map
goes idle. The wait has a 5s ceiling — a wedged tile request must not hang a
route forever.

Reaching the not-found branch now means the id is in neither the rendered
source nor the address index, which is a genuinely unknown parcel.

### A stray "%" in the URL threw an uncaught URIError

`applyHashRoute` fed raw hash segments to `decodeURIComponent`, so
`#/owner/%E0%A4%A` (a truncated escape, easy to produce by hand-editing or by
a link that got cut) threw `URIError: URI malformed` out of the hashchange
handler. The panel kept whatever the previous route had rendered, so the URL
and the panel disagreed with no visible error.

### Stale bookmarks read as a network hiccup

Owner and operator slugs are rebuilt from owner names on every refresh, so
links from before a refresh 404 — a known consequence of the pipeline, not a
transient failure. Both loaders reported "Couldn't load that owner's
portfolio", which invites a pointless retry. A 404 is now separated from a
transport failure and says the record isn't in the current dataset.

### Back to a parcel route left the panel on the owner view

`state.selectedId` stayed set while an owner or operator view was open, and
`applyHashRoute` skips `selectParcel` when the routed id already matches it.
Going parcel → owner → Back therefore restored the `#/parcel/` URL while the
panel still showed the portfolio. Both loaders now release the selection.

### A slow owner fetch could clobber a newer operator view

`openPortfolio` and `openOperator` awaited a fetch with no guard, so on a slow
connection the *earlier* request could resolve last and repaint the panel,
null out `state.lastOperator`, and rewrite the URL back to its own route.
Reproduced by delaying `/owners/` by 700ms and navigating owner → operator.

`selectParcel` already captured a token (`_selectParcelToken`) but never
compared it after awaiting — the guard was dead code. One module-level
`_viewToken` now covers all three views and is compared at every resume
point.

### The leaderboard info tooltip leaked two document listeners per render

`renderLeaderboards` registered document-level `click` and `keydown` handlers
inside its per-button loop, and it re-runs on every tab and kind switch. Ten
switches on a phone added 40 document listeners, each closing over a button
already detached from the DOM. The dismissal handlers are now registered once
at bootstrap; only the per-button click handler is re-bound per render.

### On phones, the button labelled "Open" did not open anything

Closing the sheet collapses it to `sheet-peek`, which is the state where CSS
reveals the reopen pill. Tapping it called `renderLeaderboards`, and
`showPanel` leaves an existing snap class alone — so the sheet stayed at
120px and the pill stayed put. The handler now lifts the sheet to half on
phones.
