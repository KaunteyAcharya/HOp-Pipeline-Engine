"""Mock search provider returning SYNTHETIC results on .example domains (demo + tests)."""

from __future__ import annotations

import hashlib

from hostop.discovery.providers.base import SearchHit

_WORDS = ["Bayview", "Hilltop", "Golden Hour", "Blue Door", "Lowland", "Brightwater", "Fernhill", "Larkspur"]


class MockSearch:
    name = "mock"

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        city = query.rsplit(" ", 1)[-1].title()
        h = int(hashlib.md5(query.encode()).hexdigest(), 16)
        hits = []
        for i in range(min(limit, 6)):
            word = _WORDS[(h + i) % len(_WORDS)]
            slug = f"{word.lower().replace(' ', '')}{city.lower().replace(' ', '')}"
            hits.append(SearchHit(url=f"https://www.{slug}.example/",
                                  title=f"{word} {city} Vacation Rentals | SYNTHETIC",
                                  description=f"SYNTHETIC result for '{query}'"))
        hits.append(SearchHit(url="https://www.airbnb.com/s/x", title="Directory result (should be filtered)"))
        return hits
