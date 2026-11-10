"""Web discovery via a search provider, plus a CSV importer for association / sponsor / member lists."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from pathlib import Path

from hostop.config import Geography
from hostop.discovery.base import RawOperator
from hostop.discovery.providers.base import SearchProvider
from hostop.net.fetcher import is_blocked
from hostop.resolve.normalize import normalize_domain

QUERY_TEMPLATES = [
    "vacation rental management company {city}",
    "short term rental property management {city}",
]
# Directories, OTAs and review sites are not operators.
NON_OPERATOR_DOMAINS = [
    "airbnb.com", "vrbo.com", "booking.com", "expedia.com", "tripadvisor.com", "yelp.com", "facebook.com",
    "linkedin.com", "instagram.com", "google.com", "bbb.org", "zillow.com", "reddit.com", "youtube.com",
    "angi.com", "thumbtack.com", "houfy.com", "evolve.com", "vacasa.com", "wikipedia.org",
]
_TITLE_SPLIT = re.compile(r"\s*[|\-–—:]\s*")


def title_to_name(title: str) -> str:
    parts = [p for p in _TITLE_SPLIT.split(title) if p and p.upper() != "SYNTHETIC"]
    return parts[0].strip() if parts else title.strip()


class WebSearchCollector:
    name = "web_search"

    def __init__(self, provider: SearchProvider, geographies: list[Geography], blocked: list[str],
                 per_query: int = 10, synthetic: bool = False) -> None:
        self.p, self.geos, self.per_query, self.synthetic = provider, geographies, per_query, synthetic
        self.skip = [*blocked, *NON_OPERATOR_DOMAINS]

    def collect(self) -> Iterable[RawOperator]:
        seen: set[str] = set()
        for geo in self.geos:
            for tpl in QUERY_TEMPLATES:
                q = tpl.format(city=geo.city)
                for hit in self.p.search(q, self.per_query):
                    domain = normalize_domain(hit.url)
                    if not domain or domain in seen or is_blocked(hit.url, self.skip):
                        continue
                    seen.add(domain)
                    yield RawOperator(source="web_search", source_key=domain, name=title_to_name(hit.title),
                                      domain=domain, city=geo.city, country=geo.country, source_url=hit.url,
                                      raw={"query": q, "provider": self.p.name, "title": hit.title,
                                           "description": hit.description},
                                      is_synthetic=self.synthetic)


class ListImportCollector:
    """CSV with columns: name, domain (optional), city, country, source_url, list_name (optional)."""

    name = "list_import"

    def __init__(self, path: Path, synthetic: bool = False) -> None:
        self.path, self.synthetic = path, synthetic

    def collect(self) -> Iterable[RawOperator]:
        with open(self.path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                domain = normalize_domain(row.get("domain"))
                yield RawOperator(source="list_import", source_key=f"{self.path.name}|{domain or name.lower()}",
                                  name=name, domain=domain, city=(row.get("city") or None),
                                  country=(row.get("country") or None), source_url=row.get("source_url") or None,
                                  raw={"list_name": row.get("list_name") or self.path.stem, "file": self.path.name},
                                  is_synthetic=self.synthetic)
