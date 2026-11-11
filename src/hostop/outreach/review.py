"""Human review of drafts: approve / edit / reject. Only approved or edited drafts can be exported or queued."""

from __future__ import annotations

from sqlalchemy.orm import Session

from hostop.config import HostOpConfig
from hostop.drafting.validator import validate
from hostop.models import Draft

READY = ("approved", "edited")


def approve(s: Session, draft_id: int) -> Draft:
    d = s.get_one(Draft, draft_id)
    if d.validation_errors:
        raise ValueError(f"draft {draft_id} has validation errors; edit it first: {d.validation_errors}")
    d.status = "approved"
    return d


def reject(s: Session, draft_id: int) -> Draft:
    d = s.get_one(Draft, draft_id)
    d.status = "rejected"
    return d


def edit(s: Session, draft_id: int, body: str, cfg: HostOpConfig, subject: str | None = None) -> Draft:
    """Human edits are re-validated; an edit that fails validation stays in needs_fix."""
    d = s.get_one(Draft, draft_id)
    d.body = body
    if subject is not None:
        d.subject = subject
    d.validation_errors = validate(d.channel, body, d.brief, cfg, subject=d.subject if d.channel == "email_1" else None)
    d.status = "edited" if not d.validation_errors else "needs_fix"
    return d
