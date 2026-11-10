"""Mock enrichment returning SYNTHETIC contacts on .example domains only."""

from __future__ import annotations

import hashlib

from hostop.enrich.base import CreditBudget, FoundContact

_FIRST = ["Jordan", "Avery", "Morgan", "Riley", "Quinn", "Parker", "Reese", "Skyler"]
_LAST = ["Sample", "Placeholder", "Testcase", "Demo"]
_TITLES = ["Founder", "Owner", "Director of Operations", "Guest Experience Manager"]


class MockProvider:
    name = "mock"

    def find(self, domain: str, budget: CreditBudget) -> list[FoundContact]:
        if not domain.endswith(".example") or not budget.can_spend(1):
            return []
        budget.spend(self.name, 1)
        h = int(hashlib.md5(("contact:" + domain).encode()).hexdigest(), 16)
        if h % 5 == 0:
            return []  # some operators have no findable contact
        first, last = _FIRST[h % len(_FIRST)], _LAST[h % len(_LAST)]
        status = "verified" if h % 4 else "unverified"  # exercise the verified-only filter
        return [FoundContact(full_name=f"{first} {last} (SYNTHETIC)", title=_TITLES[h % len(_TITLES)],
                             email=f"{first.lower()}@{domain}", email_status=status, source=self.name)]
