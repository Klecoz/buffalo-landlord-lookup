"""Address and owner-name normalization.

These two functions are load-bearing: bugs here silently miscount a
landlord's portfolio. Tested in tests/test_normalize.py.
"""

from __future__ import annotations

import re
from typing import Optional

import usaddress


# --- Owner names ---------------------------------------------------------

# Maps any of these tokens (case-insensitive, after punctuation strip) to a
# canonical token. Order matters for multi-word phrases — longest first.
_OWNER_SUFFIX_CANON: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\blimited liability (company|co)\b"), "llc"),
    (re.compile(r"\bl ?l ?c\b"), "llc"),
    (re.compile(r"\bincorporated\b"), "inc"),
    (re.compile(r"\bcorporation\b"), "corp"),
    (re.compile(r"\bcompany\b"), "co"),
    (re.compile(r"\bl ?p\b"), "lp"),
    (re.compile(r"\bl ?l ?p\b"), "llp"),
    (re.compile(r"\blimited\b"), "ltd"),
    (re.compile(r"\btrustee[s]?\b"), "trust"),
]

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_owner(raw: Optional[str]) -> str:
    """Return a stable, lowercase key for matching owner records.

    "ACME PROPERTIES, L.L.C." and "Acme Properties LLC" both become
    "acme properties llc". Heuristic — does not attempt to merge persons
    with/without middle initials. That limitation is documented in the UI.
    """
    if not raw:
        return ""
    s = raw.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    for pattern, canon in _OWNER_SUFFIX_CANON:
        s = pattern.sub(canon, s)
    s = _WS_RE.sub(" ", s).strip()
    return s


# --- Addresses -----------------------------------------------------------

# Canonical street-type abbreviations. We normalize TO short forms because
# Socrata datasets in Buffalo lean that way.
_STREET_TYPE_CANON = {
    "STREET": "ST",
    "ST": "ST",
    "AVENUE": "AVE",
    "AVE": "AVE",
    "AVE.": "AVE",
    "BOULEVARD": "BLVD",
    "BLVD": "BLVD",
    "ROAD": "RD",
    "RD": "RD",
    "DRIVE": "DR",
    "DR": "DR",
    "PLACE": "PL",
    "PL": "PL",
    "PARKWAY": "PKWY",
    "PKWY": "PKWY",
    "TERRACE": "TER",
    "TER": "TER",
    "COURT": "CT",
    "CT": "CT",
    "LANE": "LN",
    "LN": "LN",
    "CIRCLE": "CIR",
    "CIR": "CIR",
    "HIGHWAY": "HWY",
    "HWY": "HWY",
    "SQUARE": "SQ",
    "SQ": "SQ",
    "TRAIL": "TRL",
    "TRL": "TRL",
    "ALLEY": "ALY",
    "ALY": "ALY",
}

_DIRECTION_CANON = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}


def _canon(token: str, table: dict[str, str]) -> str:
    upper = token.upper().rstrip(".")
    return table.get(upper, upper)


def normalize_address(raw: Optional[str]) -> str:
    """Return a canonical street address (no city/state/zip, no apt).

    "123 North Main Street, Apt 4B" -> "123 N MAIN ST"
    Returns "" for empty input or unparseable garbage.
    """
    if not raw:
        return ""
    try:
        tagged, _ = usaddress.tag(raw)
    except usaddress.RepeatedLabelError:
        # Fallback: best-effort whitespace cleanup
        return _WS_RE.sub(" ", raw.upper()).strip()

    parts: list[str] = []
    if num := tagged.get("AddressNumber"):
        parts.append(num.upper())
    if pre_dir := tagged.get("StreetNamePreDirectional"):
        parts.append(_canon(pre_dir, _DIRECTION_CANON))
    if pre_type := tagged.get("StreetNamePreType"):
        parts.append(_canon(pre_type, _STREET_TYPE_CANON))
    if name := tagged.get("StreetName"):
        parts.append(name.upper())
    if post_type := tagged.get("StreetNamePostType"):
        parts.append(_canon(post_type, _STREET_TYPE_CANON))
    if post_dir := tagged.get("StreetNamePostDirectional"):
        parts.append(_canon(post_dir, _DIRECTION_CANON))

    return " ".join(parts).strip()
