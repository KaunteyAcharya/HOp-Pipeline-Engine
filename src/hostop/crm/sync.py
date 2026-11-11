"""Build CRM rows from the pipeline, then either write CSV (default, safe) or push to Attio."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from hostop.crm.attio import AttioClient
from hostop.models import Contact, Operator, OutreachEvent, Score

STAGE_ORDER = ["new", "contacted", "replied", "positive", "demo_booked", "demo_held"]
EVENT_TO_STAGE = {"sent": "contacted", "replied": "replied", "positive": "positive", "demo_booked": "demo_booked",
                  "demo_held": "demo_held"}


@dataclass
class CrmRow:
    operator_id: int
    company: str
    domain: str
    tier: str
    score: float
    stage: str
    contact_name: str
    contact_email: str
    note: str
    is_synthetic: bool


def build_rows(s: Session, tiers: tuple[str, ...] = ("A", "B")) -> list[CrmRow]:
    rows = []
    q = (select(Operator, Score).join(Score, Score.operator_id == Operator.id)
         .where(Score.tier.in_(tiers), Operator.domain.is_not(None)))
    for op, sc in s.execute(q).tuples():
        events = s.scalars(select(OutreachEvent.event).where(OutreachEvent.operator_id == op.id)).all()
        stages = [EVENT_TO_STAGE[e] for e in events if e in EVENT_TO_STAGE]
        stage = max(stages, key=STAGE_ORDER.index) if stages else "new"
        c = s.scalars(select(Contact).where(Contact.operator_id == op.id, Contact.email.is_not(None))).first()
        why = "; ".join(f"{f['factor']}: {f['reason']}" for f in sc.breakdown)
        rows.append(CrmRow(op.id, op.name, op.domain or "", sc.tier, sc.total, stage,
                           c.full_name or "" if c else "", c.email or "" if c else "",
                           f"Tier {sc.tier} ({sc.total:.0f} pts). {why}", op.is_synthetic))
    return rows


def write_csv(rows: list[CrmRow], path: Path) -> Path:
    if any(r.is_synthetic for r in rows):
        path = path.with_name("SYNTHETIC_" + path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["company", "domain", "tier", "score", "stage", "contact_name", "contact_email", "note",
                    "is_synthetic"])
        for r in rows:
            w.writerow([r.company, r.domain, r.tier, r.score, r.stage, r.contact_name, r.contact_email, r.note,
                        "SYNTHETIC" if r.is_synthetic else ""])
    return path


def push_to_attio(rows: list[CrmRow], client: AttioClient) -> int:
    n = 0
    for r in rows:
        if r.is_synthetic:
            continue  # never push synthetic data into a real CRM
        rid = client.upsert_company(r.company, r.domain)
        if r.contact_email:
            client.upsert_person(r.contact_email, r.contact_name or None, r.domain)
        client.set_stage(rid, r.stage)
        client.add_note("companies", rid, "HostOp pipeline score", r.note)
        n += 1
    return n
