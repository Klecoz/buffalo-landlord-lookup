# Decisions

Choices made and why, with rejected alternatives. Newest first.

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
