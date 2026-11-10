"""ICP fit scoring -> Tier A/B/C. Every awarded point cites the evidence rows that justify it."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from hostop.config import HostOpConfig
from hostop.models import Operator, Score


@dataclass
class Factor:
    factor: str
    points: float
    reason: str
    evidence_ids: list[int] = field(default_factory=list)


def _ev(op: Operator, *kinds: str) -> list[int]:
    return [e.id for e in op.evidence if e.kind in kinds]


def score_operator(op: Operator, cfg: HostOpConfig) -> tuple[float, str, list[Factor]]:
    w, icp = cfg.scoring.weights, cfg.icp
    factors: list[Factor] = []
    n = op.listing_count
    count_ev = _ev(op, "listing_count", "site_listing_count")
    out_of_icp = False
    if n is None:
        factors.append(Factor("listing_band", 0, "listing count unknown"))
    elif icp.ideal_min <= n <= icp.ideal_max:
        factors.append(Factor("listing_band", w.get("ideal_band", 0),
                              f"{n} listings, inside ideal band {icp.ideal_min}-{icp.ideal_max}", count_ev))
    elif icp.min_listings <= n <= icp.max_listings:
        factors.append(Factor("listing_band", w.get("icp_band", 0),
                              f"{n} listings, inside ICP {icp.min_listings}-{icp.max_listings}", count_ev))
    else:
        out_of_icp = True
        factors.append(Factor("listing_band", 0, f"{n} listings, OUTSIDE ICP "
                                                 f"{icp.min_listings}-{icp.max_listings}", count_ev))

    cities = [c for c in (op.cities or []) if c]
    if len(cities) >= icp.multi_market_min_cities:
        factors.append(Factor("multi_market", w.get("multi_market", 0), f"present in {', '.join(sorted(cities))}",
                              _ev(op, "listing_count")))
    if op.direct_booking:
        factors.append(Factor("direct_booking", w.get("direct_booking", 0), "own direct-booking site detected",
                              _ev(op, "direct_booking")))
    if op.pms:
        factors.append(Factor("pms_detected", w.get("pms_detected", 0),
                              f"site references {', '.join(op.pms)} (HostOp integration status not verified)",
                              _ev(op, "pms")))
    hiring = [s for s in op.signals if s.kind == "hiring"]
    if hiring:
        factors.append(Factor("hiring", w.get("hiring", 0), f"hiring: {hiring[0].detail}", _ev(op, "hiring")))
    growth = [s for s in op.signals if s.kind == "listing_growth"]
    if growth:
        factors.append(Factor("listing_growth", w.get("listing_growth", 0),
                              "; ".join(s.detail or "" for s in growth), _ev(op, "listing_growth")))
    if op.domain:
        factors.append(Factor("has_website", w.get("has_website", 0), f"website {op.domain}", _ev(op, "page")))

    total = min(100.0, sum(f.points for f in factors))
    if out_of_icp:
        tier = "C"
    elif total >= cfg.scoring.tiers.get("A", 60):
        tier = "A"
    elif total >= cfg.scoring.tiers.get("B", 35):
        tier = "B"
    else:
        tier = "C"
    return total, tier, factors


def score_all(s: Session, cfg: HostOpConfig) -> dict[str, int]:
    s.execute(delete(Score))
    counts = {"A": 0, "B": 0, "C": 0}
    ops = s.scalars(select(Operator).options(selectinload(Operator.evidence), selectinload(Operator.signals)))
    for op in ops:
        total, tier, factors = score_operator(op, cfg)
        s.add(Score(operator_id=op.id, total=total, tier=tier, breakdown=[asdict(f) for f in factors]))
        counts[tier] += 1
    return counts


def explain(s: Session, operator_id: int) -> dict[str, Any] | None:
    op = s.get(Operator, operator_id)
    if op is None:
        return None
    sc = s.scalars(select(Score).where(Score.operator_id == operator_id)).first()
    ev = {e.id: e for e in op.evidence}
    rows = []
    for f in (sc.breakdown if sc else []):
        rows.append({**f, "evidence": [{"id": i, "claim": ev[i].claim, "url": ev[i].url}
                                       for i in f["evidence_ids"] if i in ev]})
    return {"operator": op.name, "domain": op.domain, "synthetic": op.is_synthetic,
            "total": sc.total if sc else None, "tier": sc.tier if sc else None, "factors": rows}
