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
    "llc", "inc", "corp", "co", "lp", "llp", "ltd", "trust",
    # Conjunctions / articles
    "the", "of", "and",
    # Generic real-estate biz tokens — present across unrelated landlords,
    # so they'd fake cohesion if left in. Drop so identity tokens drive score.
    "holdings", "holding", "properties", "property", "realty", "rentals",
    "rental", "investments", "investment", "group", "enterprises",
    "enterprise", "management", "mgmt", "associates", "partners",
    "partnership", "real", "estate",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LLC_MARKER_RE = re.compile(r"\b(llc|inc|corp|lp|llp|ltd|co|trust)\b", re.IGNORECASE)


def _tokenize_for_stem(name: str) -> list[str]:
    tokens = _TOKEN_RE.findall(name.lower())
    return [t for t in tokens if t not in _STEM_STOPWORDS and len(t) >= 2]


def name_stem_cohesion(owner_names: list[str]) -> tuple[float, str]:
    """Score how much a cluster's owner names look like one family.

    Returns (score in 0.0–1.0, evidence_string). Score = fraction of owners
    sharing the most common distinctive token. Higher = tighter family.
    """
    n = len(owner_names)
    if n == 0:
        return (0.0, "empty cluster")
    if n == 1:
        return (1.0, "single owner")

    token_owner_counts: Counter[str] = Counter()
    for name in owner_names:
        for t in set(_tokenize_for_stem(name)):
            token_owner_counts[t] += 1

    if not token_owner_counts:
        return (0.0, "no distinctive tokens")

    # Best = highest coverage; longer token wins ties (more identity-bearing).
    token, count = max(
        token_owner_counts.items(),
        key=lambda kv: (kv[1], len(kv[0])),
    )
    score = count / n
    evidence = f"{count} of {n} owners share '{token}'"
    return (score, evidence)


def classify_cluster(owner_names: list[str], address_kind: str) -> dict:
    """Decide whether to keep a cluster and at what confidence.

    address_kind: "po_box" | "street". PO boxes are a stronger identity
    signal than street addresses, so the thresholds are looser.
    Returns {action: "keep"|"drop", confidence: "high"|"medium"|"low",
             evidence: str}.
    """
    n = len(owner_names)
    score, evidence = name_stem_cohesion(owner_names)
    is_po = address_kind == "po_box"

    if is_po and score >= 0.5:
        return {"action": "keep", "confidence": "high", "evidence": evidence}
    if is_po and n <= 8:
        return {
            "action": "keep", "confidence": "high",
            "evidence": f"{n} LLC{'s' if n != 1 else ''} sharing one PO box",
        }
    if not is_po and score >= 0.6:
        return {"action": "keep", "confidence": "high", "evidence": evidence}
    if not is_po and score >= 0.3:
        return {"action": "keep", "confidence": "medium", "evidence": evidence}
    if n > 30 and score < 0.3:
        return {
            "action": "drop", "confidence": "low",
            "evidence": f"{n} unrelated owners at one address — likely agent or property manager",
        }
    if score >= 0.2:
        return {"action": "keep", "confidence": "medium", "evidence": evidence}
    return {"action": "keep", "confidence": "low", "evidence": evidence}


def address_kind_from_key(mail_key: str) -> str:
    """Mail keys come from normalize_mail_address: 'PO BOX 1234 | AMHERST | …'
    or '100 MAIN ST | BUFFALO | …'."""
    return "po_box" if mail_key.startswith("PO BOX ") else "street"


# --- Person-name dedup ---------------------------------------------------

def _is_llc_like(name: str) -> bool:
    return bool(_LLC_MARKER_RE.search(name))


def _person_signature(name: str) -> Optional[frozenset[str]]:
    """Return {first_token, last_token} (uppercased), or None.

    Handles "SMITH, JOHN", "SMITH, JOHN A", "JOHN SMITH", "JOHN A SMITH".
    Doesn't try to disambiguate first-vs-last when comma is absent — the
    set form makes ordering irrelevant for matching.
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
