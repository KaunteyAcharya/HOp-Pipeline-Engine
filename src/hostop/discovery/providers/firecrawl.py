"""Firecrawl search adapter.

Contract verified against https://docs.firecrawl.dev/api-reference/endpoint/search on 2026-11-10:
POST https://api.firecrawl.dev/v2/search, Authorization: Bearer <key>, body {query, limit, excludeDomains},
response {success, data: {web: [{url, title, description}]}, creditsUsed}.
"""

from __future__ import annotations

import httpx

from hostop.discovery.providers.base import SearchHit

API_URL = "https://api.firecrawl.dev/v2/search"


class FirecrawlSearch:
    name = "firecrawl"

    def __init__(self, api_key: str, exclude_domains: list[str], client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("FIRECRAWL_API_KEY is not set")
        self.api_key, self.exclude = api_key, exclude_domains
        self.client = client or httpx.Client(timeout=60)
        self.credits_used = 0

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        r = self.client.post(API_URL, headers={"Authorization": f"Bearer {self.api_key}"},
                             json={"query": query, "limit": limit, "excludeDomains": self.exclude})
        r.raise_for_status()
        body = r.json()
        self.credits_used += int(body.get("creditsUsed") or 0)
        web = (body.get("data") or {}).get("web") or []
        return [SearchHit(url=h.get("url", ""), title=h.get("title", ""), description=h.get("description", ""))
                for h in web if h.get("url")]
