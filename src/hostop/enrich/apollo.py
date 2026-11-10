"""Apollo.io adapter.

Contract checked against docs.apollo.io on 2026-11-10:
1. POST https://api.apollo.io/api/v1/mixed_people/api_search (header x-api-key), body
   {q_organization_domains_list: [domain], person_titles: [...], per_page}. 0 credits, returns people[]
   with id, first_name, title, has_email, but NO emails. Free accounts need a work-email signup.
2. POST https://api.apollo.io/api/v1/people/match with {id} (reveal_personal_emails=false) returns
   person.email + person.email_status. Consumes credits. We keep only email_status == "verified".
UNVERIFIED: exact credit cost of people/match on your plan and whether the free plan permits API match.
"""

from __future__ import annotations

import httpx

from hostop.enrich.base import DECISION_TITLES, CreditBudget, FoundContact

BASE = "https://api.apollo.io/api/v1"
COST_PER_MATCH = 1.0


class ApolloProvider:
    name = "apollo"

    def __init__(self, api_key: str, client: httpx.Client | None = None, max_matches: int = 2) -> None:
        if not api_key:
            raise ValueError("APOLLO_API_KEY is not set")
        self.max_matches = max_matches
        self.client = client or httpx.Client(timeout=30)
        self.headers = {"x-api-key": api_key, "Content-Type": "application/json", "Cache-Control": "no-cache"}

    def find(self, domain: str, budget: CreditBudget) -> list[FoundContact]:
        r = self.client.post(f"{BASE}/mixed_people/api_search", headers=self.headers,
                             json={"q_organization_domains_list": [domain], "person_titles": DECISION_TITLES,
                                   "per_page": 10})
        r.raise_for_status()
        people = [p for p in r.json().get("people") or [] if p.get("has_email")]
        out: list[FoundContact] = []
        for p in people[: self.max_matches]:
            if not budget.can_spend(COST_PER_MATCH):
                break
            m = self.client.post(f"{BASE}/people/match", headers=self.headers,
                                 params={"reveal_personal_emails": "false", "reveal_phone_number": "false"},
                                 json={"id": p["id"]})
            m.raise_for_status()
            budget.spend(self.name, COST_PER_MATCH)
            person = m.json().get("person") or {}
            out.append(FoundContact(full_name=person.get("name"), title=person.get("title") or p.get("title"),
                                    email=person.get("email"),
                                    email_status=(person.get("email_status") or "unknown").lower(),
                                    source=self.name))
        return out
