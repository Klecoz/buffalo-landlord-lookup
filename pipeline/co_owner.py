"""Parse ADD_OWNER strings into stable co-owner keys, and decide which
keys are too common to be useful cross-cluster link evidence.

Reuses _person_signature and _is_llc_like from cluster_score.py — same
human-name handling we already trust for in-cluster person dedup.
"""

from __future__ import annotations

from typing import Optional

from cluster_score import _is_llc_like, _person_signature


# A co-owner key appearing in MORE than this many distinct operators is
# treated as common-name noise (e.g. "Smith, John" across the whole city)
# and excluded from the cross-cluster link surface. Stays as raw evidence
# in the per-cluster co_owners list — only suppressed from linked_operators.
MAX_OPERATORS_PER_CO_OWNER = 5


def parse_co_owner(raw: str) -> Optional[dict]:
    """Return {"key": frozenset, "display": str} or None for unkeyable input.

    None when:
    - empty / whitespace
    - looks like an LLC / corp / inc (caller wants humans only)
    - cannot extract a (first, last) pair (single-token names, garbage)
    """
    if not raw or not raw.strip():
        return None
    if _is_llc_like(raw):
        return None
    sig = _person_signature(raw)
    if sig is None:
        return None
    return {"key": sig, "display": raw.strip()}


def suppress_common_names(
    index: dict[frozenset, list],
) -> dict[frozenset, list]:
    """Drop entries whose value-list length exceeds MAX_OPERATORS_PER_CO_OWNER.

    `index` maps co-owner key → list of appearances (e.g. operator slugs).
    Returns a filtered shallow copy. Lengths AT the threshold are kept;
    only strictly greater is dropped.
    """
    return {k: v for k, v in index.items() if len(v) <= MAX_OPERATORS_PER_CO_OWNER}
