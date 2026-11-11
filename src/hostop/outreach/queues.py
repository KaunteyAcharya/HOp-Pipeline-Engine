"""Manual LinkedIn / Instagram task queues with daily caps. A human performs every task; nothing is automated."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from hostop.compliance.optout import is_suppressed
from hostop.config import HostOpConfig
from hostop.models import Contact, Draft, Operator, Task
from hostop.outreach.review import READY

CHANNEL_CAP = {"linkedin_note": "linkedin_connect", "linkedin_followup": "linkedin_message",
               "instagram_dm": "instagram_dm"}


def build_queue(s: Session, cfg: HostOpConfig, start: date | None = None, workdays_only: bool = True) -> int:
    """Schedule approved LinkedIn/Instagram drafts into dated tasks respecting per-channel daily caps."""
    start = start or date.today()
    used: Counter[tuple[str, str]] = Counter(
        (t.channel, t.due_date) for t in s.scalars(select(Task).where(Task.status == "todo")))
    queued = {t.draft_id for t in s.scalars(select(Task))}
    drafts = s.scalars(select(Draft).where(Draft.channel.in_(["linkedin_note", "instagram_dm"]),
                                           Draft.status.in_(READY)).order_by(Draft.id)).all()
    n = 0
    for d in drafts:
        if d.id in queued:
            continue
        op = s.get_one(Operator, d.operator_id)
        email = s.get_one(Contact, d.contact_id).email if d.contact_id else None
        if is_suppressed(s, email=email, domain=op.domain, handle=op.instagram_handle):
            continue
        cap = cfg.outreach.daily_caps.get(CHANNEL_CAP[d.channel], 10)
        day = start
        while True:
            if workdays_only and day.weekday() >= 5:
                day += timedelta(days=1)
                continue
            if used[(d.channel, day.isoformat())] < cap:
                break
            day += timedelta(days=1)
        used[(d.channel, day.isoformat())] += 1
        s.add(Task(draft_id=d.id, channel=d.channel, due_date=day.isoformat()))
        n += 1
    s.flush()
    return n


def export_queue(s: Session, out_dir: Path, day: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    q = select(Task).where(Task.status == "todo").order_by(Task.due_date, Task.channel)
    if day:
        q = q.where(Task.due_date == day)
    tasks = s.scalars(q).all()
    synthetic = False
    path = out_dir / f"tasks_{day or 'all'}.csv"
    rows = []
    for t in tasks:
        d = s.get_one(Draft, t.draft_id)
        op = s.get_one(Operator, d.operator_id)
        c = s.get(Contact, d.contact_id) if d.contact_id else None
        synthetic = synthetic or d.is_synthetic
        target = (f"https://www.instagram.com/{op.instagram_handle}/" if t.channel == "instagram_dm"
                  else (c.linkedin_search_url if c else ""))
        rows.append({"task_id": t.id, "due": t.due_date, "channel": t.channel, "operator": op.name,
                     "contact": c.full_name if c else "", "open_manually": target, "message": d.body,
                     "hook_id": d.hook_id, "is_synthetic": "SYNTHETIC" if d.is_synthetic else ""})
    if synthetic:
        path = path.with_name("SYNTHETIC_" + path.name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["task_id", "due", "channel", "operator", "contact", "open_manually",
                                           "message", "hook_id", "is_synthetic"])
        w.writeheader()
        w.writerows(rows)
    return path
