# Decisions

Choices made and why, with rejected alternatives. Newest first.

## 2026-08-08 — The legend shows two keys, not one five-step ramp

`s0`-`s3` are buckets of a violation count; `s4` means "demolition permit and
the assessment roll now reads vacant". Those are different kinds of value, and
the old legend rendered them as one continuous scale with one tick row, which
is what made the labels collide — `demolished` needs roughly as much width as
the three numeric ticks combined.

The ramp and its ticks now share a `repeat(4, 34px)` grid so each bucket label
sits under its swatch, and the demolished swatch sits on its own row with the
existing "permit + vacant lot" definition beside it rather than beneath.

Rejected: shrinking the tick font until four labels fit. It keeps the
false claim that demolished is the top of a severity scale, and 9px mono on a
translucent plate is not readable.

Rejected: labelling only the two endpoints. That drops `5+` and `11+`, which
are the thresholds a reader actually needs to interpret the map.

## 2026-08-08 — Click targets carry data attributes, not inline handlers

Every `onclick="fn('${escapeHtml(x)}')"` template is gone; the value lives in
a `data-*` attribute and `showPanel` binds the listener after injecting the
HTML, reusing the pattern already there for "Highlight on map".

The audit found nothing exploitable — the interpolated values were slugs
(`[a-z0-9-]` by pipeline construction), parcel ids, and two hardcoded scope
literals. The change is about where the guarantee lives. HTML entity escaping
is the wrong defense inside a JS-string context (the browser decodes entities
before the JS parser sees them), so those sites were relying on a property of
the *data* rather than of the *code*. Parcel ids in particular are copied
verbatim from the assessment roll's SBL field with no pipeline test pinning
their alphabet.

Rejected: one delegated listener on `#panel` dispatching by selector. It
would have replaced the existing per-render wiring for leaderboard rows and
LLC lists too — a rebuild of the event system for no correctness gain.

Rejected: leaving the slug sites alone with a comment stating the invariant
(the option the plan allowed). The comment now states the invariant *and*
there are no exceptions to remember.
## 2026-08-08 — One view token guards all three async views

A single module-level `_viewToken`, bumped on entry to `selectParcel`,
`openPortfolio`, and `openOperator` and compared after every await. A stale
resume returns silently.

Rejected: `AbortController` per view. It would need plumbing through three
fetch sites and still wouldn't cover the non-fetch resume points
(`loadDossiers`, the map-idle wait), so the token comparison would have to
exist anyway.

Sharing one counter across all three views is deliberate: navigating to an
owner should cancel a pending parcel selection, which is what the shared
counter gives for free.
## 2026-08-08 — Deep-linked parcels are found via the address index

`selectParcel` falls back to the centroid in `state.addressIndex` and
re-queries the map source after an idle wait, rather than reading the dossier
out of a smaller side-channel. This matters for any reload or shared link,
since every map click rewrites the address bar to `#/parcel/:id`.

The alternative was to render what the address index already holds (address,
owner slug, coordinates) and skip the map entirely. Rejected: the dossier
needs violation counts, 311 counts, value, and `demo_permit`, which live only
in `properties.geojson`. Serving a partial dossier for deep links and a full
one for map clicks would make the same URL render two different pages
depending on how you got there.

The idle wait is capped at 5s so a wedged tile request degrades to the
not-found panel instead of hanging the route.
## 2026-08-07 — Violations join gets an SBL fallback, address stays primary

`_join_violations` now tries the row's `sbl` when the normalized address
matches no parcel. This recovers 18,589 violations (7.4% of the feed) that
were absent from every owner portfolio and concern score.

Address stays the primary key rather than moving to SBL-first the way
`_join_demolitions` works. The two feeds differ: 228,379 of 250,586
violations carry a usable 16-char SBL, but the address is populated on all
but 62 rows and already matches 229,126 of them, and only 73 address matches
disagree with the row's SBL. Reordering would rewrite a quarter of a million
existing matches to chase 73 disagreements. Demolitions went SBL-first for
the opposite reason — its address field is a single `stname` string and its
SBL is the more reliable key.

Rejected: matching the 17-char SBLs (a 16-char base plus a trailing letter,
252 violations and 22 permits) by truncating to `[:16]`. That would match a
real parcel for about half of them, but it collapses a sub-parcel onto its
base parcel on a guess about what the letter means.

Note for the next refresh: this raises published violation counts for many
owners and reorders the leaderboards. The change is a fix, not a
re-weighting — the rows were always in the source.

## 2026-08-07 — Slugs are capped at 120 characters

`_slugify` truncates. A slug is a filename, filesystems cap names at 255
bytes, and an over-long owner name would abort the entire emit partway
through writing 65k portfolios. The assessment roll truncates owner names at
30 characters and the longest real slug is 46, so this is unreachable today —
but the input is third-party and the failure is total rather than local.

120 leaves room for the `.json.tmp` suffix with margin. Collisions the cap
introduces need no new machinery: both slug paths already dedup.

Rejected: hashing long names (unreadable slugs, and the URL is user-facing);
raising the cap to 255 minus the suffix (a slug that long is unusable in a
URL anyway, and the roll never produces one).

## 2026-08-07 — A registered-agent address demotes medium clusters to low

`emit.py` now mirrors its own promotion rule: where a clean NYS DOS check
lifts low → medium, a `registered_agent` classification drops medium → low.
This is the use REGISTERED_AGENT_THRESHOLD was defined for and had never been
put to.

Only medium is touched. A medium cluster is one the shared address is
carrying, and that address has just been discredited; a high cluster's names
already form a family, and a genuine operator may perfectly well file through
an agent. On the emitted set the rule demotes 17 clusters and leaves one high
cluster (93-nyrpt-llc, cohesion 0.6) alone — so it needs no cohesion threshold
of its own, and none is introduced.

Rejected: dropping these clusters outright (the shared address is still a real
fact, and the seven registered-agent clusters already at low are published the
same way); demoting on cohesion score instead of confidence band (identical
result on real data, at the cost of duplicating classify_cluster's 0.6 bar in
a second module).

## 2026-08-07 — PO-box auto-trust requires at least one business entity

The "<= 8 owners sharing one PO box → high confidence" rule now also requires
one member to look like a business. It is the rule's own evidence string ("N
LLCs sharing one PO box") made true, and it demotes exactly the two clusters
in the emitted set that had no business in them at all — both consistent with
a mail drop or an escrow servicer's lockbox rather than a landlord. They stay
published, at medium.

Rejected: lowering the size cap from 8 (the bad cases have 3 and 5 members, so
it would not reach them and would demote good clusters); treating out-of-state
PO boxes as suspect (PO BOX 52427 Atlanta is a genuine corporate family — the
Laidlaw bus companies).

## 2026-08-07 — Trailing middle initials are dropped from person keys

`_person_signature` pops one-character trailing tokens (never below two
tokens) before taking first + last. This makes the space-separated "Adkins
Cassandra C" key the same as the comma form "Adkins, Cassandra", which has
always ignored middle initials.

It follows that "Smith John A" and "Smith John B" now merge inside a cluster.
That is acceptable for the same reason the comma form's behaviour always was:
the merge only ever happens among owners already sharing a mailing address,
which corroborates it. Rejected: keeping the two spellings apart (leaves 8,148
owner records unkeyable and the two name formats inconsistent with each other).

## 2026-08-07 — A name ending in business vocabulary is not a person

`_person_signature` returns None when the last token of a non-comma name is
business vocabulary (legal forms plus generic nouns: holdings, properties,
associates, apartments, housing, management, …). This stops organizations from
faking the alter-ego pattern and from merging with each other on a first+last
token coincidence.

The trade is real and was measured: the guard removes 5 false organization
merges and also 5 correct ones (typo pairs like "Eversmile Trade Corporation" /
"Eversmile Traders Corporation", "Nickel City Property Holding" / "Nickel City
Properties Holding"). It is worth taking because a false merge asserts a
relationship between two landlords that does not exist, while a false split
merely fails to assert one — on an accountability site the first is the worse
error. "Church" is excluded from the list for the opposite reason: the roll
holds four correct church-name merges under it and no incorrect one.

Rejected: extending `_LLC_MARKER_RE` to the long forms instead (fixes the
"Corporation" cases but not the suffix-less organizations, which is where the
worst merges are); an organization-name allowlist or fuzzy comparison (both
out of scope per the simplicity rule).

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

## 2026-08-07 — Demolished = permit + currently-vacant parcel (implemented)

`demolished` is now: a demolition permit matches the parcel (permit SBL
right-padded to 20 chars first, normalized address as fallback) AND the 2025
assessment roll reads vacant (`PROP_CLASS` 3xx, or `TOTAL_AV <= LAND_AV` with
both figures positive). The parcel keeps the latest matching permit as
`demo_permit = {date, via}` regardless of the vacancy answer, so the UI can
distinguish "permit issued, lot now vacant" from "permit issued, building
present". Concern score adds +5 only when the permit is inside a hardcoded
5-year window; older confirmed demolitions stay `demolished` for the map and
the dossier but stop driving the score.

On the 2026-08-07 pull this drops the flag from 8,128 parcels to 6,720, and
drops the score-affected set from 8,128 to 172 (see FINDINGS.md for the full
measurement, including the roll-lag reason the 172 is so small).

Both figures must be positive for the value test: 361 parcels have `LAND_AV`
and `TOTAL_AV` both 0, which is a roll record with no assessment rather than
evidence of a cleared lot, so those only count as vacant if `PROP_CLASS` says
so. Permit `sbl` values shorter than 16 characters (a few dozen 4-6 char
strings) are treated as junk and fall through to the address, rather than
matched on a prefix.

Rejected: keeping the permit-only flag (9% of the city flagged, mostly
decades-old); pulling a new "completed demolitions" dataset (none is
published); inferring completion from permit fees/inspections (fragile,
complex); anchoring the 5-year window to the feed's max date the way the 311
window is anchored (a stale feed would then keep old permits "recent" forever —
the opposite of what a concern signal should do).

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
