"""Contact enrichment waterfall.

Rules: verified emails only; never guess or pattern-generate emails; stop at the first provider that yields
a verified decision-maker; respect a per-run credit budget; skip suppressed operators/contacts; always
attach a LinkedIn *search URL* for manual lookup (we never fetch LinkedIn).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote_plus

from sqlalchemy import select
from sqlalchemy.orm import Session

from hostop.compliance.optout import is_suppressed
from hostop.compliance.regions import classify
from hostop.config import HostOpConfig
from hostop.enrich.base import BudgetExceededError, CreditBudget, EnrichmentProvider, is_decision_maker
from hostop.models import Contact, CreditLedger, Operator, Score


def linkedin_search_url(company: str, title_hint: str = "owner OR founder OR operations") -> str:
    return ("https://www.linkedin.com/search/results/people/?keywords="
            + quote_plus(f'"{company}" {title_hint}'))


@dataclass
class EnrichStats:
    operators: int = 0
    with_verified_email: int = 0
    dropped_unverified: int = 0
    suppressed: int = 0
    budget_stopped: bool = False
    credits: dict[str, float] = field(default_factory=dict)


def enrich_operators(s: Session, cfg: HostOpConfig, providers: list[EnrichmentProvider], limit: int = 50,
                     tiers: tuple[str, ...] = ("A", "B"), run_id: int | None = None) -> EnrichStats:
    budget = CreditBudget(cfg.enrichment.credit_budget_per_run)
    st = EnrichStats()
    q = (select(Operator).join(Score, Score.operator_id == Operator.id)
         .where(Score.tier.in_(tiers), Operator.domain.is_not(None), ~Operator.contacts.any())
         .order_by(Score.total.desc()).limit(limit))
    for op in s.scalars(q).all():
        if is_suppressed(s, domain=op.domain, handle=op.instagram_handle):
            st.suppressed += 1
            continue
        st.operators += 1
        flag = classify(op.country, cfg)
        kept = dm_found = False
        for p in providers:
            try:
                found = p.find(op.domain or "", budget)
            except BudgetExceededError:
                st.budget_stopped = True
                break
            for c in found:
                if c.email_status != "verified" or not c.email:
                    st.dropped_unverified += 1
                    continue
                if is_suppressed(s, email=c.email):
                    st.suppressed += 1
                    continue
                s.add(Contact(operator_id=op.id, full_name=c.full_name, title=c.title, email=c.email.lower(),
                              email_status="verified", email_source=c.source, country=op.country,
                              compliance_regime=flag.regime, lawful_basis_note=flag.note,
                              linkedin_search_url=linkedin_search_url(op.name), is_synthetic=op.is_synthetic))
                kept = True
                dm_found = dm_found or is_decision_maker(c.title)
            if dm_found:
                break
        if kept:
            st.with_verified_email += 1
        else:
            # No verified email: still give the human a manual LinkedIn lookup path.
            s.add(Contact(operator_id=op.id, linkedin_search_url=linkedin_search_url(op.name), country=op.country,
                          compliance_regime=flag.regime, lawful_basis_note=flag.note, is_synthetic=op.is_synthetic))
        if not budget.can_spend(1):
            st.budget_stopped = True
            break
    for provider, credits in budget.spent.items():
        s.add(CreditLedger(run_id=run_id, provider=provider, credits=credits, note="enrich run"))
    st.credits = dict(budget.spent)
    return st
