"""Collector interface shared by every discovery source."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class RawOperator:
    """One operator as seen by one source. Never fabricated: every field comes from the source."""

    source: str
    source_key: str
    name: str
    domain: str | None = None
    city: str | None = None
    country: str | None = None
    listing_count: int | None = None
    source_url: str | None = None
    snapshot: str | None = None
    strong_ids: dict[str, str] = field(default_factory=dict)  # e.g. {"airbnb_host": "1234"}
    raw: dict[str, Any] = field(default_factory=dict)
    is_synthetic: bool = False


class Collector(Protocol):
    name: str

    def collect(self) -> Iterable[RawOperator]: ...
