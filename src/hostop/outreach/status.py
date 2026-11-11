"""Manual status logging: sent, replied, positive, demo_booked, demo_held (+ opt_out, bounced)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from hostop.compliance.optout import suppress
from hostop.models import Contact, Draft, OutreachEvent, Task

EVENTS = ("sent", "replied", "positive", "demo_booked", "demo_held", "opt_out", "bounced")
CHANNEL_GROUP = {"linkedin_note": "linkedin", "linkedin_followup": "linkedin", "instagram_dm": "instagram",
                 "email_1": "email", "email_2": "email", "email_3": "email"}


def log_event(s: Session, operator_id: int, channel: str, event: str, contact_id: int | None = None,
              hook_id: str | None = None, list_name: str | None = None, note: str | None = None,
              is_synthetic: bool = False) -> OutreachEvent:
    if event not in EVENTS:
        raise ValueError(f"event must be one of {EVENTS}")
    ev = OutreachEvent(operator_id=operator_id, contact_id=contact_id, channel=CHANNEL_GROUP.get(channel, channel),
                       hook_id=hook_id, list_name=list_name, event=event, note=note, is_synthetic=is_synthetic)
    s.add(ev)
    if event in ("opt_out", "bounced") and contact_id:
        c = s.get(Contact, contact_id)
        if c and c.email:
            suppress(s, c.email, event)
    s.flush()
    return ev


def log_from_draft(s: Session, draft_id: int, event: str, list_name: str | None = None,
                   note: str | None = None) -> OutreachEvent:
    d = s.get_one(Draft, draft_id)
    if event == "sent":
        for t in s.query(Task).filter(Task.draft_id == draft_id).all():
            t.status = "done"
    return log_event(s, d.operator_id, d.channel, event, d.contact_id, d.hook_id, list_name, note, d.is_synthetic)
