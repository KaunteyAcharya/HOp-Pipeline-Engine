"""Research brief: built ONLY from stored evidence + the HostOp facts allowlist. The LLM sees nothing else."""

from __future__ import annotations

from typing import Any

from hostop.config import HostOpConfig
from hostop.models import Contact, Operator

SEGMENT_PRIORITY = ["hiring", "direct_booking", "multi_market", "listing_growth", "pms", "general"]
EVIDENCE_KINDS = ["listing_count", "site_listing_count", "listing_growth", "direct_booking", "hiring", "pms"]


def segment_for(op: Operator) -> str:
    kinds = {s.kind for s in op.signals}
    if "hiring" in kinds:
        return "hiring"
    if op.direct_booking:
        return "direct_booking"
    if len([c for c in op.cities or [] if c]) >= 2:
        return "multi_market"
    if "listing_growth" in kinds:
        return "listing_growth"
    if op.pms:
        return "pms"
    return "general"


def first_name(contact: Contact | None) -> str | None:
    if not contact or not contact.full_name:
        return None
    return contact.full_name.split()[0]


def build_brief(op: Operator, contact: Contact | None, cfg: HostOpConfig) -> dict[str, Any]:
    facts = [{"id": e.id, "kind": e.kind, "claim": e.claim, "url": e.url}
             for e in op.evidence if e.kind in EVIDENCE_KINDS]
    return {
        "synthetic": op.is_synthetic,
        "operator": {"name": op.name, "domain": op.domain, "cities": op.cities, "listing_count": op.listing_count,
                     "pms": op.pms, "direct_booking": op.direct_booking, "instagram_handle": op.instagram_handle},
        "contact": {"first_name": first_name(contact), "title": contact.title if contact else None},
        "segment": segment_for(op),
        "evidence": facts,
        "hostop_facts": cfg.company.facts,
        "value_props": [v.model_dump() for v in cfg.value_props],
    }
