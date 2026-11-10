"""Listing-count growth signal between Inside Airbnb snapshots of the same host and city."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from hostop.models import Evidence, OperatorSource, Signal


def compute_growth(session: Session) -> int:
    session.execute(delete(Signal).where(Signal.kind == "listing_growth"))
    session.execute(delete(Evidence).where(Evidence.kind == "listing_growth"))
    series: dict[tuple[int, str], list[tuple[str, int]]] = defaultdict(list)
    rows = session.scalars(select(OperatorSource).where(OperatorSource.source == "inside_airbnb"))
    for src in rows:
        if src.operator_id is None or not src.snapshot:
            continue
        city = src.source_key.split("|")[0]
        series[(src.operator_id, city)].append((src.snapshot, int(src.raw["calculated_host_listings_count"])))
    n = 0
    for (op_id, city), points in series.items():
        if len(points) < 2:
            continue
        points.sort()
        (s0, c0), (s1, c1) = points[0], points[-1]
        if c1 <= c0:
            continue
        ev = Evidence(operator_id=op_id, kind="listing_growth",
                      claim=f"Inside Airbnb {city}: {c0} listings ({s0}) -> {c1} listings ({s1})")
        session.add(ev)
        session.flush()
        session.add(Signal(operator_id=op_id, kind="listing_growth", value=float(c1 - c0),
                           detail=f"{city}: +{c1 - c0} ({s0} to {s1})", evidence_id=ev.id))
        n += 1
    return n
