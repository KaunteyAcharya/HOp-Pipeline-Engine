"""CSV exports of approved email sequences for Instantly / Smartlead import. This module never sends anything.

Column names are plain CSV headers; both tools let you map columns to lead fields and custom variables on
import, so verify the mapping in their UI. Each step's body includes the sender signature and postal address
(CAN-SPAM). Contacts flagged needs_review (CASL / GDPR / unknown country) are excluded unless include_review.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from hostop.compliance.optout import is_suppressed
from hostop.compliance.regions import REVIEW_REGIMES
from hostop.config import HostOpConfig
from hostop.deliverability.verify import Verifier
from hostop.models import Contact, Draft, Operator
from hostop.outreach.review import READY

COLUMNS = ["email", "first_name", "last_name", "company_name", "website", "subject", "email_1", "email_2", "email_3",
           "hook_id", "list_name", "compliance_regime", "is_synthetic"]


def signature(cfg: HostOpConfig) -> str:
    s = cfg.sender
    return f"\n\n{s.name}\n{s.title}, {s.company}\n{s.postal_address}"


@dataclass
class ExportResult:
    path: Path
    rows: int
    skipped_suppressed: int
    skipped_review: int
    skipped_incomplete: int
    skipped_failed_verification: int = 0


def export_email_sequences(s: Session, cfg: HostOpConfig, platform: str, out_dir: Path, list_name: str,
                           include_review: bool = False, verifier: Verifier | None = None) -> ExportResult:
    if platform not in ("instantly", "smartlead"):
        raise ValueError("platform must be instantly or smartlead")
    drafts = s.scalars(select(Draft).where(Draft.channel.like("email_%"), Draft.status.in_(READY))).all()
    by_contact: dict[int, dict[str, Draft]] = defaultdict(dict)
    for d in drafts:
        if d.contact_id:
            by_contact[d.contact_id][d.channel] = d
    synthetic = any(d.is_synthetic for d in drafts)
    real = any(not d.is_synthetic for d in drafts)
    if real and "<" in signature(cfg):
        raise ValueError("fill in sender name, title and postal_address in config/hostop.yaml before exporting")
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = "SYNTHETIC_" if synthetic else ""
    path = out_dir / f"{prefix}{platform}_{list_name}_{date.today().isoformat()}.csv"
    res = ExportResult(path, 0, 0, 0, 0)
    sig = signature(cfg)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for contact_id, steps in by_contact.items():
            c = s.get_one(Contact, contact_id)
            op = s.get_one(Operator, c.operator_id)
            if not c.email or c.email_status != "verified" or set(steps) != {"email_1", "email_2", "email_3"}:
                res.skipped_incomplete += 1
                continue
            if is_suppressed(s, email=c.email, domain=op.domain):
                res.skipped_suppressed += 1
                continue
            if c.compliance_regime in REVIEW_REGIMES and not include_review:
                res.skipped_review += 1
                continue
            if verifier is not None and verifier.status(c.email) != "valid":
                res.skipped_failed_verification += 1
                continue
            parts = (c.full_name or "").replace("(SYNTHETIC)", "").split()
            w.writerow({
                "email": c.email, "first_name": parts[0] if parts else "",
                "last_name": " ".join(parts[1:]), "company_name": op.name, "website": op.domain or "",
                "subject": steps["email_1"].subject or "",
                "email_1": steps["email_1"].body + sig, "email_2": steps["email_2"].body + sig,
                "email_3": steps["email_3"].body + sig, "hook_id": steps["email_1"].hook_id or "",
                "list_name": list_name, "compliance_regime": c.compliance_regime or "",
                "is_synthetic": "SYNTHETIC" if c.is_synthetic else "",
            })
            res.rows += 1
    return res
