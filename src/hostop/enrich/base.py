"""Enrichment provider interface + credit budget."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

DECISION_TITLES = ["owner", "founder", "co-founder", "ceo", "president", "managing director", "principal",
                   "coo", "director of operations", "general manager", "head of operations"]


class BudgetExceededError(Exception):
    pass


@dataclass
class CreditBudget:
    limit: float
    spent: dict[str, float] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return sum(self.spent.values())

    def can_spend(self, amount: float) -> bool:
        return self.total + amount <= self.limit

    def spend(self, provider: str, amount: float) -> None:
        if not self.can_spend(amount):
            raise BudgetExceededError(f"credit budget {self.limit} would be exceeded")
        self.spent[provider] = self.spent.get(provider, 0) + amount


@dataclass
class FoundContact:
    full_name: str | None
    title: str | None
    email: str | None
    email_status: str  # provider status, normalized: "verified" or something else
    source: str


class EnrichmentProvider(Protocol):
    name: str

    def find(self, domain: str, budget: CreditBudget) -> list[FoundContact]: ...


def is_decision_maker(title: str | None) -> bool:
    t = (title or "").lower()
    return any(k in t for k in DECISION_TITLES)
