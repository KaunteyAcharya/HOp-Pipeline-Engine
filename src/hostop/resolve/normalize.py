"""Name and domain normalization used by entity resolution."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_LEGAL = r"\b(llc|l\.l\.c|inc|incorporated|ltd|limited|co|corp|corporation|company|pllc|lp|llp|gmbh|plc|the)\b"
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = _NON_ALNUM.sub(" ", s)
    s = re.sub(_LEGAL, " ", s)
    return _SPACES.sub(" ", s).strip()


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if not v:
        return None
    if "://" not in v:
        v = "http://" + v
    host = urlparse(v).hostname or ""
    host = host.removeprefix("www.")
    return host or None


def is_distinctive(norm_name: str) -> bool:
    """Single short tokens (e.g. Airbnb host first names like 'john') are too ambiguous to fuzzy-merge."""
    tokens = norm_name.split()
    return len(tokens) >= 2 or len(norm_name) >= 10
