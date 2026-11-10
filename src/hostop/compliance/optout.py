"""Suppression / do-not-contact handling and opt-out detection in replies."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from hostop.models import Suppression

OPT_OUT = re.compile(r"^\s*(no|stop|unsubscribe|remove)\b|\b(unsubscribe|remove me|take me off|do not contact|"
                     r"don't contact|stop emailing|not interested|opt[- ]?out)\b", re.I)


def is_opt_out(text: str) -> bool:
    return bool(OPT_OUT.search(text or ""))


def _kind(value: str) -> str:
    if "@" in value:
        return "email"
    if value.startswith("@") or "." not in value:
        return "handle"
    return "domain"


def suppress(s: Session, value: str, reason: str) -> bool:
    v = value.strip().lower()
    if s.scalar(select(Suppression.id).where(Suppression.value == v)):
        return False
    s.add(Suppression(value=v, kind=_kind(v), reason=reason))
    s.flush()
    return True


def is_suppressed(s: Session, email: str | None = None, domain: str | None = None,
                  handle: str | None = None) -> bool:
    values = set()
    if email:
        values.add(email.lower())
        values.add(email.lower().split("@")[-1])
    if domain:
        values.add(domain.lower())
    if handle:
        values.add(handle.lower())
        values.add("@" + handle.lower().lstrip("@"))
    return bool(values) and s.scalar(select(Suppression.id).where(Suppression.value.in_(values))) is not None
