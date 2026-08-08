# Decisions

Choices made and why, with rejected alternatives. Newest first.

## 2026-08-08 — Duplicated hedges are trimmed at the conditional site, not the permanent one

Two cautions were each rendered twice inside one panel. Where a hedge appeared
both in a bottom disclaimer that always renders and in a conditional element (an
expandable audit disclosure, a sub-note shown only for un-clustered owners), the
sentence was removed from the conditional element.

Taken: keep the copy that cannot be missed. A reader who never expands the audit
disclosure still gets the full caveat; a reader who does gets it once instead of
twice.

Rejected: keeping it in the disclosure and trimming the disclaimer. The
disclosure is collapsed by default, so that would let a reader reach the bottom
of the operator view having never seen the caveat.

Rejected: leaving both. Verbatim repetition inside one view is the specific tell
this pass exists to remove, and the repetition carried no new information.

## 2026-08-08 — Search results order addresses first, owners second

Owner names now match in the same search box as addresses, which needs a rule
for mixing two kinds of hit in twelve rows.

Rejected: rank purely by match position (prefix beats mid-string) across both
kinds. It reads well in the abstract and fails on this data — address rows begin
with a house number, so "main" is a mid-string match for "100 Main St" and a
prefix match for "Mainsail Holdings LLC", and the LLC displaces the whole street.

Taken: addresses first, owners after, prefix matches first within each kind.
This is an address lookup that also knows owner names, not a general search.
The one wrinkle is that a common street word would fill all twelve rows with
addresses and hide a matching landlord, so owners keep a floor of three rows
whenever any owner matches. "clover" lands on ten Cloverdale addresses plus
Clover Homesource LLC and Lucky Penny Four Leaf Clover.

Rejected: a second index file for owners. Extending `address_index.json` costs
+4.5MB on a file already being fetched, against a second request and a second
scan for the same data.

## 2026-08-08 — The tablet colophon keeps its clipped tail

Between 481 and 880px the colophon spans the full width under an opaque 360px
panel, so its last field is covered — at 844px it reads "311 data through 20".
Ending the box at the panel edge (`right: 360px`) does fix that, and was tried:
the narrower box wraps the footer from two lines to three (79px tall), and at
`bottom: 0` it then grows up into the legend at `bottom: 44px`. On a 844×390
landscape window that trades a clipped date fragment for a footer eating a
fifth of the screen and colliding with the key.

Padding the box instead of narrowing it does nothing — the children are nowrap
flex items and overflow the padding.

Left as is. The refresh date is also in the masthead, which is where a reader
looks for it, and the sources line is attribution this tool should not drop to
save 25px.

## 2026-08-08 — "Demo" is a column head, not a card label

The desktop table head stays "Demo" because that column is 40px wide. The
stacked card carries `data-label="Demolished"`, which is what that attribute is
for — it exists only to feed the mobile `::before`. Reading "Demo —" on a card
with room for the word invites "demonstration".

Rejected: overriding the text in CSS with
`td[data-label="Demo"]::before { content: "Demolished" }`. That hides a string
the reader sees inside a selector that matches on a different string.

## 2026-08-08 — The info tip flips rather than shrinks

When the tip would cross the bottom edge it is placed above its button instead.
The alternative was to cap its height and let it scroll, which turns a
two-line explanation into a scroll container. Horizontal placement now clamps
against the tip's measured width rather than the hard-coded 220px, and keeps an
8px margin off both edges.

It is also dismissed on window resize and on panel scroll. The tip is absolutely
positioned against the viewport with no reflow of its own, so following its
button would mean tracking it; dismissing is the honest answer to "the thing
this explains just moved".

## 2026-08-08 — Safe-area insets stay inert

`index.html` deliberately keeps `viewport-fit` unset. Without it the page is
letterboxed into the safe area, which means no fixed element can end up under a
notch or a home indicator — the correct outcome, reached by not opting in.
Adding `viewport-fit=cover` would put the burden on every bottom-pinned element
here (sheet, colophon, legend, chip, reopen pill) and cannot be verified
without a notched device.

## 2026-08-08 — The tablet band gets wrapping, not a wider panel

Between 481 and 880px the five board pills and the two kind-toggle tabs are
allowed to size to their content and wrap to a second line. The obvious
alternative was to widen `#panel` past 360px so the labels fit on one line.
That trades map for text in the band where the map is already down to 400px,
and 360px is a value the desktop pass set deliberately — a responsive fix
should not quietly re-open it.

Rejected: extending the ≤480px horizontal-scroll treatment up into this band.
A scrolling row hides options behind a gesture; on a 768px screen there is
room to simply show them.

## 2026-08-08 — Selecting a record promotes the sheet out of peek

`applyHashRoute` bumps a peek sheet to half when the route names a parcel,
owner or operator. Rendering a dossier into a 120px strip showed its address
and nothing else, which reads as the app ignoring the tap.

`/highlight` routes are excluded: that flow drops to peek on purpose so the
highlighted parcels are visible, and it would have fought itself.

Rejected: doing this in `showPanel`. Every re-render goes through it —
including the one `setSnap` triggers when it finds the panel empty — so the
promotion would have fired on renders that are not navigations.

## 2026-08-08 — Crossing the phone breakpoint re-renders the leaderboards

The tab labels have a phone variant chosen at render time, so the breakpoint
has to be re-read when it changes. A `resize` listener that fires only on an
actual crossing (not on every resize tick) re-renders the board.

Rejected: emitting both label variants and switching them with CSS. That puts
two copies of every label and two ⓘ buttons in the DOM, and the ⓘ carries its
text in a `data-info-tip` attribute the popover reads — duplicating it invites
the two copies to drift.

## 2026-08-08 — The filter chip is two boxes, and only the label may truncate

Making the chip a flex row with `.filter-chip-label` as the only shrinking
child fixes the disappearing "✕ Clear" without capping the label length. The
alternative was to truncate the owner name in JS at some character count,
which puts a layout constant in the render path and still guesses wrong at
360px versus 430px.

The chip keeps its whole-surface click handler; the ✕ is an affordance, not
the only target.

## 2026-08-08 — The peek sheet is its own "open" affordance

`#reopen-panel` is now shown on phones only when the panel is fully closed,
positioned at `bottom: 72px` to clear the 60px closed strip. At peek the sheet
already presents its title and a full-width drag handle that opens on tap, so
a second control saying "Open" was duplicating a thing already on screen —
and it was rendering behind the sheet in both states anyway.

Rejected: moving the pill above the sheet at peek. The bottom-left strip
already carries the colophon, the legend and, with a filter on, the chip;
adding a fourth fixed element there to duplicate the handle spends map for
nothing.

Not fixed, deliberately: `.panel-handle` is 28px tall. That clears WCAG 2.5.8
(24px) and it spans the full 390px width, so it is an easy target despite the
height. Growing it to 44px would push `#panel-close` and the panel's top
padding down with it and cost 16px of the 120px peek content — the state where
content is scarcest.

## 2026-08-08 — The accent is scoped to boards that measure harm

`concern: true` is a property of the board, not of the row. The alternative
was to keep the rule global and accept that "top of this list" is worth the
accent whatever the list ranks. That reading does not survive the Value board,
where the leader is a stadium developer and the number is a land assessment.

One accent that means one thing is the whole basis of this palette; spending
it on "biggest" as well as "worst" costs more than it buys.

Not fixed, deliberately: the portfolio view stacks two full-width bordered
CTAs ("Same mailing address as related LLCs" and "Highlight on map") that read
as equals though one navigates and one toggles a map layer. A secondary button
variant would be a second button style in a system that deliberately has one.
Recorded here rather than fixed.

Not fixed, deliberately: `.conf-badge::before` prints "Confidence " ahead of
text that already reads "high-confidence cluster", so the operator view says
"Confidence high-confidence cluster". It is a copy defect and Item 9 owns copy.

## 2026-08-08 — Clickable rows get tabindex, not a wrapped button

Leaderboard rows, LLC rows and property rows are `<li>` and `<tr>` elements
with click listeners. The textbook fix is to put a real `<button>` or `<a>`
inside each row, which is what a screen reader wants to hear. It is also a
`<button>` inside a `<td>` in a table whose columns are the point, and it
would have meant reworking the markup of four render paths and their tests.

They get `tabindex="0"`, `role="button"` on the list items, and a keydown that
forwards Enter/Space to the element's own `click()`. The existing click
listeners stay the single implementation — the keyboard path cannot drift from
the mouse path because it literally calls it.

Rejected: a delegated keydown on `#panel`. The rows are wired per render and
one more listener there would split the wiring across two places.

## 2026-08-08 — Search is a combobox with aria-activedescendant

Arrow keys move a highlight while focus stays in the input, so typing to
refine a query keeps working mid-navigation. A roving tabindex would move
focus into the list and break that.

`.open` on the list and `aria-expanded` on the input are set through one
helper. They were going to drift otherwise: the class is toggled from five
places (input, Escape, selection, outside click, short query) and the tests
assert on the class, so the class had to stay.

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
