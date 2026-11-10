"""Discovery orchestration: run collectors, resolve entities, compute growth, record the run."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hostop.config import HostOpConfig
from hostop.discovery.base import Collector
from hostop.discovery.growth import compute_growth
from hostop.discovery.inside_airbnb import InsideAirbnbCollector
from hostop.discovery.permits import PermitCollector, load_mapping
from hostop.models import Operator, Run, utcnow
from hostop.resolve.entity_resolution import resolve


def build_collectors(cfg: HostOpConfig, demo: bool) -> list[Collector]:
    lo, hi = cfg.icp.min_listings, cfg.icp.max_listings
    if demo:
        from hostop.demo.seed import DEMO_DIR, generate

        root = generate(DEMO_DIR)
        return [
            InsideAirbnbCollector(root / "inside_airbnb", lo, hi, synthetic=True),
            PermitCollector(load_mapping(root / "permit_mapping.yaml"), lo, hi, base_dir=root, synthetic=True),
        ]
    collectors: list[Collector] = [InsideAirbnbCollector(Path("data/inside_airbnb"), lo, hi)]
    for mapping in sorted(Path("config/permit_mappings").glob("*.yaml")):
        collectors.append(PermitCollector(load_mapping(mapping), lo, hi))
    return collectors


def run_discovery(session: Session, cfg: HostOpConfig, demo: bool,
                  collectors: Iterable[Collector] | None = None) -> dict[str, Any]:
    run = Run(command="discover", demo=demo)
    session.add(run)
    totals: dict[str, Any] = {"by_source": {}}
    for c in collectors if collectors is not None else build_collectors(cfg, demo):
        stats = resolve(session, c.collect())
        for src, d in stats.by_source.items():
            agg = totals["by_source"].setdefault(src, {"seen": 0, "created": 0, "merged": 0, "skipped_existing": 0})
            for k, v in d.items():
                agg[k] += v
    totals["growth_signals"] = compute_growth(session)
    totals["operators_total"] = session.scalar(select(func.count(Operator.id))) or 0
    seen = sum(d["seen"] - d["skipped_existing"] for d in totals["by_source"].values())
    merged = sum(d["merged"] for d in totals["by_source"].values())
    totals["new_records"] = seen
    totals["dedupe_rate"] = round(merged / seen, 3) if seen else 0.0
    run.stats, run.finished_at = totals, utcnow()
    return totals
