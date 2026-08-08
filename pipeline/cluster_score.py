"""Score and classify operator clusters built from shared mailing addresses.

Drives the high/medium/low/drop decision that replaces the older flat
">30 owners → drop" cutoff in emit.py. Cohesion comes from how much the
names within a cluster look like one operator's family of LLCs ("ACME 1
LLC", "ACME 2 LLC") versus a service address pooling unrelated owners.

Also dedups person-name variants WITHIN a cluster — safe because the
shared mailing address corroborates the merge. Across clusters, persons
with the same signature stay separate.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Optional


# Tokens that don't carry identity signal — drop before computing cohesion.
# Be conservative: business-form words ("llc", "corp") are universal noise
# and would otherwise fake a 100% cohesion score across any cluster.
_STEM_STOPWORDS = frozenset({
    # Business form
    "llc", "inc", "corp", "corporation", "corporations", "co", "lp", "llp",
    "ltd", "trust",
    # Conjunctions / articles
    "the", "of", "and",
    # Generic real-estate biz tokens — present across unrelated landlords,
    # so they'd fake cohesion if left in. Drop so identity tokens drive score.
    "holdings", "holding", "properties", "property", "realty", "rentals",
    "rental", "investments", "investment", "group", "enterprises",
    "enterprise", "management", "mgmt", "associates", "partners",
    "partnership", "real", "estate",
    # Generic descriptors that recur across unrelated operators. Audited
    # against the live operator index — each was selected as the
    # "distinctive" cohesion token in 6+ unrelated clusters before being
    # dropped here.
    "development", "developments", "apartments", "apartment", "housing",
    "community", "communities", "construction", "international",
    # Geographic noise — street suffixes, state/region tokens, and Buffalo-
    # specific names that show up in many unrelated owner names (e.g.
    # "Elm Street LLC" + "Main Street LLC" would otherwise fake cohesion
    # via "street").
    "street", "st", "road", "rd", "avenue", "ave", "lane", "drive", "blvd",
    "buffalo", "main", "ny", "wny",
    # Personal-name suffixes / honorifics — not identity. "md" is the
    # Bangladeshi-American naming particle (Md. = Mohammad), which appears
    # in ~100 unrelated owner records here.
    "jr", "sr", "ii", "iii", "iv", "md",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LLC_MARKER_RE = re.compile(r"\b(llc|inc|corp|lp|llp|ltd|co|trust)\b", re.IGNORECASE)


def _tokenize_for_stem(name: str) -> list[str]:
    tokens = _TOKEN_RE.findall(name.lower())
    return [t for t in tokens if t not in _STEM_STOPWORDS and len(t) >= 2]


def cohesion_details(owner_names: list[str]) -> dict:
    """Structured form of cohesion analysis.

    Returns dict with: score (0.0–1.0), distinctive_token (str|None),
    explanation (str), owner_count (int). Used by emit.py to build the
    per-cluster audit block surfaced in the UI.
    """
    n = len(owner_names)
    if n == 0:
        return {"score": 0.0, "distinctive_token": None,
                "explanation": "empty cluster", "owner_count": 0}
    if n == 1:
        return {"score": 1.0, "distinctive_token": None,
                "explanation": "single owner", "owner_count": 1}

    token_owner_counts: Counter[str] = Counter()
    for name in owner_names:
        for t in set(_tokenize_for_stem(name)):
            token_owner_counts[t] += 1

    if not token_owner_counts:
        return {"score": 0.0, "distinctive_token": None,
                "explanation": "no distinctive tokens", "owner_count": n}

    # Sort by token before taking the max: `max` returns the first maximal
    # item, and Counter iterates in insertion order, which comes from the
    # `set(...)` above — a per-process hash order. Without this, a cluster
    # whose top tokens tie (e.g. "Zoll, Sean" -> zoll/sean) picks a different
    # winner on every run, and the evidence string it prints flaps with it.
    token, count = max(
        sorted(token_owner_counts.items()),
        key=lambda kv: (kv[1], len(kv[0])),
    )
    return {
        "score": count / n,
        "distinctive_token": token,
        "explanation": f"{count} of {n} owners share '{token}'",
        "owner_count": n,
    }


def name_stem_cohesion(owner_names: list[str]) -> tuple[float, str]:
    """Score how much a cluster's owner names look like one family.

    Returns (score in 0.0–1.0, evidence_string). Score = fraction of owners
    sharing the most common distinctive token. Higher = tighter family.

    Thin wrapper around cohesion_details — kept for back-compat with
    classify_cluster and existing tests.
    """
    d = cohesion_details(owner_names)
    return (d["score"], d["explanation"])


def classify_cluster(owner_names: list[str], address_kind: str) -> dict:
    """Decide whether to keep a cluster and at what confidence.

    address_kind: "po_box" | "street". PO boxes are a stronger identity
    signal than street addresses, so the thresholds are looser.
    Returns {action, confidence, evidence, pattern}. `pattern` is one of
    {"alter_ego", None} — surfaced in the per-cluster audit block.
    """
    n = len(owner_names)
    score, evidence = name_stem_cohesion(owner_names)
    is_po = address_kind == "po_box"

    # Alter-ego pattern: exactly one person + one LLC sharing a street
    # address. The classic LLC-unmasking signal — a resident owns an LLC
    # that holds (probably) their property. Cohesion is structurally
    # uninformative here (only 2 owners, different name spaces), so promote
    # to high directly. PO-box pairs are already covered by the n<=8 branch.
    if not is_po and n == 2:
        llc_count = sum(1 for name in owner_names if _is_llc_like(name))
        person_count = sum(
            1 for name in owner_names
            if not _is_llc_like(name) and _person_signature(name) is not None
        )
        if llc_count == 1 and person_count == 1:
            return {
                "action": "keep", "confidence": "high",
                "evidence": "person + LLC at shared street address — alter-ego pattern",
                "pattern": "alter_ego",
            }

    if is_po and score >= 0.5:
        return {"action": "keep", "confidence": "high",
                "evidence": evidence, "pattern": None}
    # A small PO box is trustworthy because businesses don't share one
    # casually. A box holding nothing but natural persons is a different
    # animal — a mail drop or an escrow/tax servicer's lockbox, which pools
    # unrelated homeowners — so require at least one actual business entity
    # before making the claim this evidence string makes.
    if is_po and n <= 8 and any(_is_llc_like(name) for name in owner_names):
        return {
            "action": "keep", "confidence": "high",
            "evidence": f"{n} LLC{'s' if n != 1 else ''} sharing one PO box",
            "pattern": None,
        }
    if not is_po and score >= 0.6:
        return {"action": "keep", "confidence": "high",
                "evidence": evidence, "pattern": None}
    if not is_po and score >= 0.3:
        return {"action": "keep", "confidence": "medium",
                "evidence": evidence, "pattern": None}
    if n > 30 and score < 0.3:
        return {
            "action": "drop", "confidence": "low",
            "evidence": f"{n} unrelated owners at one address — likely agent or property manager",
            "pattern": None,
        }
    if score >= 0.2:
        return {"action": "keep", "confidence": "medium",
                "evidence": evidence, "pattern": None}
    return {"action": "keep", "confidence": "low",
            "evidence": evidence, "pattern": None}


def address_kind_from_key(mail_key: str) -> str:
    """Mail keys come from normalize_mail_address: 'PO BOX 1234 | AMHERST | …'
    or '100 MAIN ST | BUFFALO | …'."""
    return "po_box" if mail_key.startswith("PO BOX ") else "street"


# --- Service-address classification (NYS DOS join) -----------------------

# A street address that registers at least this many distinct NY business
# entities (per the NYS DOS dos_process_address field) is treated as a
# registered-agent / filing-service address — counter-evidence to the
# 'real shared owner' hypothesis. 100 is a starting point; tune from the
# observed distribution emitted by pipeline/nys_dos.histogram.
REGISTERED_AGENT_THRESHOLD = 100

# A street address with FEWER than this many entities is unlikely to be a
# registered-agent service (real ones have hundreds-to-thousands). Below
# the bar, we read the address as positive evidence of a real shared
# owner — even if the cluster has more LLCs than the DOS index records,
# because dormant or out-of-state LLCs may not show up in DOS at all.
SHARED_OWNER_THRESHOLD = 30


def classify_service_address(
    nys_dos_entity_count: int,
    address_kind: str,
) -> str:
    """Label the cluster's mailing address against the NYS DOS index.

    Returns one of:
      "registered_agent" — address registers >= REGISTERED_AGENT_THRESHOLD
                           NY entities; probably CSC, Cogency, or a law
                           firm / CPA pool.
      "shared_owner"     — street address with < SHARED_OWNER_THRESHOLD
                           entities; too few to be a true filing service,
                           consistent with a real shared owner.
      "unknown"          — middle range, or PO boxes (DOS process-address
                           is a *street* field, so PO boxes never match
                           and the absence is uninformative).
    """
    if nys_dos_entity_count >= REGISTERED_AGENT_THRESHOLD:
        return "registered_agent"
    if address_kind == "street" and nys_dos_entity_count < SHARED_OWNER_THRESHOLD:
        return "shared_owner"
    return "unknown"


# --- Person-name dedup ---------------------------------------------------

def _is_llc_like(name: str) -> bool:
    return bool(_LLC_MARKER_RE.search(name))


# A name ending in one of these is an organization, so first+last token is
# not a person signature. _LLC_MARKER_RE only catches the abbreviated forms,
# which leaves "Acme Bearings Corporation" looking like a person named
# {ACME, CORPORATION} — enough to fake the alter-ego (person + LLC) pattern,
# and enough to merge two unrelated organizations whose first and last tokens
# agree ("St Clare Apartments" / "St Patrick Village Apartments").
#
# Business vocabulary only. "Church" is deliberately absent: the roll holds
# four correct church-name merges under the old rule and no incorrect one.
_ORG_TAIL_TOKENS = frozenset({
    # Legal forms, including the long spellings normalize_owner canonicalizes
    "llc", "inc", "corp", "corporation", "corporations", "incorporated",
    "co", "company", "lp", "llp", "ltd", "limited", "trust",
    # Generic business nouns that end an organization's name
    "holdings", "holding", "properties", "property", "realty", "rentals",
    "rental", "investments", "investment", "group", "enterprises",
    "enterprise", "management", "mgmt", "associates", "partners",
    "partnership", "development", "developments", "apartments", "apartment",
    "housing", "ministries", "fund",
})


def _person_signature(name: str) -> Optional[frozenset[str]]:
    """Return {first_token, last_token} (uppercased), or None.

    Handles "SMITH, JOHN", "SMITH, JOHN A", "JOHN SMITH", "JOHN A SMITH".
    Doesn't try to disambiguate first-vs-last when comma is absent — the
    set form makes ordering irrelevant for matching. Returns None for names
    that end in organization vocabulary; the comma form is unambiguously
    "LAST, FIRST" and needs no such guard.
    """
    cleaned = re.sub(r"[^\w\s,]", " ", name).strip()
    if not cleaned:
        return None
    if "," in cleaned:
        last_part, first_part = (p.strip() for p in cleaned.split(",", 1))
        last_toks = last_part.split()
        first_toks = first_part.split()
        if not last_toks or not first_toks:
            return None
        first = first_toks[0]
        last = last_toks[0]
    else:
        toks = cleaned.split()
        if len(toks) < 2:
            return None
        if toks[-1].lower() in _ORG_TAIL_TOKENS:
            return None
        # "SMITH JOHN A" is the roll's other spelling of "SMITH, JOHN A" —
        # last name first, middle initial trailing. Drop trailing initials
        # so it keys the same as the comma form, which already ignores them.
        while len(toks) > 2 and len(toks[-1]) == 1:
            toks.pop()
        first, last = toks[0], toks[-1]
    if len(first) < 2 or len(last) < 2:
        return None
    return frozenset({first.upper(), last.upper()})


def dedup_persons_in_cluster(owners_block: list[dict]) -> list[dict]:
    """Merge person-name variants WITHIN a cluster.

    Input: owners block from emit.py — list of {slug, display, properties, ...}.
    Output: [{canonical, variants[], slugs[], property_count}], LLCs preserved
    as singletons. Order roughly follows input order (stable for testing).
    """
    groups: list[dict] = []
    sig_to_idx: dict[frozenset[str], int] = {}

    for o in owners_block:
        display = o.get("display", "")
        prop_count = o.get("properties", 0)
        slug = o.get("slug", "")

        if _is_llc_like(display):
            groups.append({
                "canonical": display, "variants": [],
                "slugs": [slug], "property_count": prop_count,
            })
            continue

        sig = _person_signature(display)
        if sig is None:
            groups.append({
                "canonical": display, "variants": [],
                "slugs": [slug], "property_count": prop_count,
            })
            continue

        if sig in sig_to_idx:
            g = groups[sig_to_idx[sig]]
            g["variants"].append(display)
            g["slugs"].append(slug)
            g["property_count"] += prop_count
        else:
            sig_to_idx[sig] = len(groups)
            groups.append({
                "canonical": display, "variants": [],
                "slugs": [slug], "property_count": prop_count,
            })

    return groups
