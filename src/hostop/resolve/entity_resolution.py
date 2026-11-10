"""Entity resolution: merge RawOperator records from all sources into Operators.

Match order (first hit wins):
  1. strong id (e.g. the same Inside Airbnb host_id seen in another city or snapshot)
  2. exact normalized domain
  3. fuzzy normalized name (rapidfuzz token_sort_ratio >= threshold), only for distinctive names,
     and only when countries do not conflict
Every contributed field value is written to field_provenance with its source.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from hostop.discovery.base import RawOperator
from hostop.models import Evidence, FieldProvenance, Operator, OperatorSource
from hostop.resolve.normalize import is_distinctive, normalize_domain, normalize_name

FUZZY_THRESHOLD = 92


@dataclass
class ResolveStats:
    seen: int = 0
    skipped_existing: int = 0
    created: int = 0
    merged: int = 0
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)

    def bump(self, source: str, key: str) -> None:
        self.by_source.setdefault(source, {"seen": 0, "created": 0, "merged": 0, "skipped_existing": 0})
        self.by_source[source][key] += 1


class Resolver:
    def __init__(self, session: Session, threshold: int = FUZZY_THRESHOLD) -> None:
        self.s = session
        self.threshold = threshold
        self.by_strong: dict[tuple[str, str], int] = {}
        self.by_domain: dict[str, int] = {}
        self.names: dict[int, str] = {}  # operator_id -> normalized name (distinctive only)
        self.countries: dict[int, str | None] = {}
        self.loaded_keys: set[tuple[str, str]] = set(
            (s, k) for s, k in self.s.execute(select(OperatorSource.source, OperatorSource.source_key)))
        self._load_index()

    def _load_index(self) -> None:
        for op in self.s.scalars(select(Operator)):
            self._index_operator(op)
        for src in self.s.scalars(select(OperatorSource).where(OperatorSource.operator_id.is_not(None))):
            for k, v in (src.raw.get("_strong_ids") or {}).items():
                self.by_strong[(k, str(v))] = src.operator_id  # type: ignore[assignment]

    def _index_operator(self, op: Operator) -> None:
        if op.domain:
            self.by_domain[op.domain] = op.id
        if is_distinctive(op.normalized_name):
            self.names[op.id] = op.normalized_name
        self.countries[op.id] = op.country

    def match(self, r: RawOperator, norm: str, domain: str | None) -> int | None:
        for k, v in r.strong_ids.items():
            if (k, v) in self.by_strong:
                return self.by_strong[(k, v)]
        if domain and domain in self.by_domain:
            return self.by_domain[domain]
        if is_distinctive(norm) and self.names:
            hit = process.extractOne(norm, self.names, scorer=fuzz.token_sort_ratio, score_cutoff=self.threshold)
            if hit is not None:
                op_id = int(hit[2])
                c = self.countries.get(op_id)
                if not (c and r.country and c != r.country):
                    return op_id
        return None

    def _prov(self, op_id: int, fld: str, value: object, r: RawOperator) -> None:
        if value in (None, "", []):
            return
        self.s.add(FieldProvenance(operator_id=op_id, field=fld, value=str(value), source=r.source,
                                   source_url=r.source_url))

    def add(self, r: RawOperator, stats: ResolveStats) -> None:
        stats.seen += 1
        stats.bump(r.source, "seen")
        if (r.source, r.source_key) in self.loaded_keys:
            stats.skipped_existing += 1
            stats.bump(r.source, "skipped_existing")
            return
        norm = normalize_name(r.name)
        domain = normalize_domain(r.domain)
        op_id = self.match(r, norm, domain)
        if op_id is None:
            op = Operator(name=r.name, normalized_name=norm, domain=domain, country=r.country,
                          cities=[r.city] if r.city else [], listing_count=r.listing_count,
                          is_synthetic=r.is_synthetic)
            self.s.add(op)
            self.s.flush()
            stats.created += 1
            stats.bump(r.source, "created")
        else:
            op = self.s.get_one(Operator, op_id)
            if domain and not op.domain:
                op.domain = domain
            if r.country and not op.country:
                op.country = r.country
            if r.city and r.city not in op.cities:
                op.cities = [*op.cities, r.city]
            if r.listing_count and (op.listing_count or 0) < r.listing_count:
                op.listing_count = r.listing_count
            # A real source must never be silently merged into a synthetic operator or vice versa.
            op.is_synthetic = op.is_synthetic and r.is_synthetic
            stats.merged += 1
            stats.bump(r.source, "merged")
        raw = dict(r.raw)
        raw["_strong_ids"] = r.strong_ids
        self.s.add(OperatorSource(operator_id=op.id, source=r.source, source_key=r.source_key,
                                  source_url=r.source_url, snapshot=r.snapshot, raw=raw,
                                  is_synthetic=r.is_synthetic))
        for fld, val in (("name", r.name), ("domain", domain), ("city", r.city),
                         ("country", r.country), ("listing_count", r.listing_count)):
            self._prov(op.id, fld, val, r)
        if r.listing_count:
            label = "SYNTHETIC " if r.is_synthetic else ""
            self.s.add(Evidence(operator_id=op.id, kind="listing_count", url=r.source_url,
                                claim=f"{label}{r.source}: {r.listing_count} listings in {r.city or 'unknown city'}"
                                      f"{f' (snapshot {r.snapshot})' if r.snapshot else ''}"))
        for k, v in r.strong_ids.items():
            self.by_strong[(k, v)] = op.id
        self.loaded_keys.add((r.source, r.source_key))
        self._index_operator(op)


def resolve(session: Session, raws: Iterable[RawOperator]) -> ResolveStats:
    stats = ResolveStats()
    resolver = Resolver(session)
    for r in raws:
        resolver.add(r, stats)
    session.flush()
    return stats
