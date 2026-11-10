"""Hunter.io adapter (free tier works with these endpoints).

Contract checked against https://hunter.io/api-documentation/v2 on 2026-11-10:
GET https://api.hunter.io/v2/domain-search?domain=..&limit=.. with X-API-KEY header.
Response data.emails[] has value, type, confidence, first_name, last_name, position, verification{date,status}.
We keep only emails whose verification.status == "valid". Credit cost per call is an ASSUMPTION
(1 credit per domain search returning results) - confirm on your Hunter plan page.
"""

from __future__ import annotations

import httpx

from hostop.enrich.base import CreditBudget, FoundContact

API = "https://api.hunter.io/v2/domain-search"
COST_PER_SEARCH = 1.0


class HunterProvider:
    name = "hunter"

    def __init__(self, api_key: str, client: httpx.Client | None = None, limit: int = 10) -> None:
        if not api_key:
            raise ValueError("HUNTER_API_KEY is not set")
        self.key, self.limit = api_key, limit
        self.client = client or httpx.Client(timeout=30)

    def find(self, domain: str, budget: CreditBudget) -> list[FoundContact]:
        if not budget.can_spend(COST_PER_SEARCH):
            return []
        r = self.client.get(API, params={"domain": domain, "limit": self.limit, "type": "personal"},
                            headers={"X-API-KEY": self.key})
        r.raise_for_status()
        budget.spend(self.name, COST_PER_SEARCH)
        out = []
        for e in (r.json().get("data") or {}).get("emails") or []:
            status = ((e.get("verification") or {}).get("status") or "").lower()
            name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x) or None
            out.append(FoundContact(full_name=name, title=e.get("position"), email=e.get("value"),
                                    email_status="verified" if status == "valid" else status or "unknown",
                                    source=self.name))
        return out
