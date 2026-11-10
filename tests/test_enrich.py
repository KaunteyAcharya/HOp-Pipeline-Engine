from pathlib import Path

import httpx
import pytest

from hostop.compliance.optout import is_opt_out, is_suppressed, suppress
from hostop.compliance.regions import classify
from hostop.config import HostOpConfig, load_config
from hostop.db import init_db, session_scope
from hostop.enrich.apollo import ApolloProvider
from hostop.enrich.base import CreditBudget, FoundContact
from hostop.enrich.hunter import HunterProvider
from hostop.enrich.waterfall import enrich_operators, linkedin_search_url
from hostop.models import Contact, Operator, Score

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg() -> HostOpConfig:
    return load_config(ROOT / "config" / "hostop.yaml")


class FakeProvider:
    def __init__(self, name: str, contacts: list[FoundContact], cost: float = 1) -> None:
        self.name, self.contacts, self.cost, self.calls = name, contacts, cost, 0

    def find(self, domain: str, budget: CreditBudget) -> list[FoundContact]:
        self.calls += 1
        budget.spend(self.name, self.cost)
        return self.contacts


def _db(tmp_path: Path, n: int = 1) -> str:
    url = f"sqlite:///{tmp_path / 'e.db'}"
    init_db(url)
    with session_scope(url) as s:
        for i in range(n):
            op = Operator(name=f"Harbor {i}", normalized_name=f"harbor {i}", domain=f"harbor{i}.com", country="US")
            s.add(op)
            s.flush()
            s.add(Score(operator_id=op.id, total=80 - i, tier="A"))
    return url


def test_only_verified_emails_kept_and_waterfall_stops(tmp_path: Path, cfg: HostOpConfig) -> None:
    url = _db(tmp_path)
    p1 = FakeProvider("a", [FoundContact("Guess", "Owner", "guess@harbor0.com", "unverified", "a"),
                            FoundContact("Pat", "Founder", "pat@harbor0.com", "verified", "a")])
    p2 = FakeProvider("b", [FoundContact("X", "Owner", "x@harbor0.com", "verified", "b")])
    with session_scope(url) as s:
        st = enrich_operators(s, cfg, [p1, p2])
        emails = [c.email for c in s.query(Contact).all()]
    assert emails == ["pat@harbor0.com"] and st.dropped_unverified == 1 and p2.calls == 0


def test_no_contact_still_gets_linkedin_search_url(tmp_path: Path, cfg: HostOpConfig) -> None:
    url = _db(tmp_path)
    with session_scope(url) as s:
        enrich_operators(s, cfg, [FakeProvider("a", [])])
        c = s.query(Contact).one()
    assert c.email is None and c.linkedin_search_url and "linkedin.com/search" in c.linkedin_search_url
    assert c.compliance_regime == "CAN-SPAM"


def test_budget_stops_run(tmp_path: Path, cfg: HostOpConfig) -> None:
    url = _db(tmp_path, n=5)
    cfg2 = cfg.model_copy(deep=True)
    cfg2.enrichment.credit_budget_per_run = 2
    p = FakeProvider("a", [])
    with session_scope(url) as s:
        st = enrich_operators(s, cfg2, [p])
    assert p.calls == 2 and st.budget_stopped


def test_suppressed_domain_skipped(tmp_path: Path, cfg: HostOpConfig) -> None:
    url = _db(tmp_path)
    with session_scope(url) as s:
        suppress(s, "Harbor0.com", "do_not_contact")
        p = FakeProvider("a", [])
        st = enrich_operators(s, cfg, [p])
    assert st.suppressed == 1 and p.calls == 0


def test_suppression_email_and_domain(tmp_path: Path) -> None:
    url = _db(tmp_path)
    with session_scope(url) as s:
        assert suppress(s, "Pat@Harbor0.com", "opt_out") and not suppress(s, "pat@harbor0.com", "opt_out")
        assert is_suppressed(s, email="pat@harbor0.com")
        assert not is_suppressed(s, email="sam@harbor0.com")


@pytest.mark.parametrize("text,expected", [("Unsubscribe", True), ("no thanks", True), ("Please remove me", True),
                                           ("Not interested right now", True), ("Sounds good, Tuesday?", False),
                                           ("I know a lot about this", False)])
def test_opt_out_detection(text: str, expected: bool) -> None:
    assert is_opt_out(text) is expected


def test_compliance_regions(cfg: HostOpConfig) -> None:
    assert classify("US", cfg).regime == "CAN-SPAM" and not classify("US", cfg).needs_review
    assert classify("CA", cfg).regime == "CASL" and classify("CA", cfg).needs_review
    assert classify("DE", cfg).regime == "GDPR"
    assert classify(None, cfg).regime == "UNKNOWN"


def test_linkedin_url_is_search_only() -> None:
    assert linkedin_search_url("Harbor Stays").startswith("https://www.linkedin.com/search/results/people/?")


def test_hunter_adapter_filters_by_verification() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v2/domain-search" and req.headers["X-API-KEY"] == "k"
        return httpx.Response(200, json={"data": {"emails": [
            {"value": "a@op.com", "first_name": "A", "position": "Owner", "verification": {"status": "valid"}},
            {"value": "b@op.com", "verification": {"status": "accept_all"}}]}})

    h = HunterProvider("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = h.find("op.com", CreditBudget(5))
    assert [c.email_status for c in out] == ["verified", "accept_all"]


def test_apollo_adapter_search_then_match() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        assert req.headers["x-api-key"] == "k"
        if req.url.path.endswith("api_search"):
            return httpx.Response(200, json={"people": [{"id": "p1", "has_email": True, "title": "Owner"},
                                                        {"id": "p2", "has_email": False}]})
        return httpx.Response(200, json={"person": {"name": "Pat", "email": "pat@op.com", "email_status": "verified"}})

    a = ApolloProvider("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    b = CreditBudget(5)
    out = a.find("op.com", b)
    assert paths == ["/api/v1/mixed_people/api_search", "/api/v1/people/match"]
    assert out[0].email == "pat@op.com" and b.total == 1
