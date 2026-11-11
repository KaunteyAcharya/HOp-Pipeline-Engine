from pathlib import Path
from typing import Any

import pytest

from hostop.config import HostOpConfig, load_config
from hostop.db import init_db, session_scope
from hostop.drafting.generator import draft_operators
from hostop.drafting.mock_llm import MockLLM
from hostop.drafting.validator import allowed_numbers, validate
from hostop.models import Contact, Draft, Evidence, Hook, Operator, Score, Signal

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg() -> HostOpConfig:
    return load_config(ROOT / "config" / "hostop.yaml")


BRIEF: dict[str, Any] = {"operator": {"listing_count": 42},
                         "evidence": [{"id": 1, "claim": "inside_airbnb: 42 listings in Austin"}],
                         "hostop_facts": ["the founder scaled his own rental arbitrage business to 400+ units"]}


def _email(cfg: HostOpConfig, body: str) -> str:
    return f"{body}\n\n{cfg.sender.opt_out_line}"


# --- validator ---------------------------------------------------------------------------------

def test_clean_email_passes(cfg: HostOpConfig) -> None:
    body = _email(cfg, "Hi Pat, you run 42 listings in Austin. HostOp puts check-in and ID verification in one flow.")
    assert validate("email_1", body, BRIEF, cfg, subject="check-in at harbor") == []


@pytest.mark.parametrize("text,needle", [
    ("I hope this email finds you well.", "banned phrase"),
    ("Loved your recent post about guests.", "fake familiarity"),
    ("We cut damage costs by 37 percent.", "unsupported"),
    ("Trusted by leading operators across the US.", "social proof"),
    ("HostOp integrates with Guesty out of the box.", "PMS integration"),
    ("Hi [First Name], quick note.", "placeholder"),
    ("We guarantee more upsell revenue.", "guarantee"),
])
def test_validator_rejects(cfg: HostOpConfig, text: str, needle: str) -> None:
    errs = validate("email_1", _email(cfg, text), BRIEF, cfg, subject="hello")
    assert any(needle in e for e in errs), errs


def test_numbers_must_come_from_brief(cfg: HostOpConfig) -> None:
    assert "400" in allowed_numbers(BRIEF) and "42" in allowed_numbers(BRIEF)
    assert validate("linkedin_note", "Saw your 42 listings.", BRIEF, cfg) == []
    assert any("unsupported number: 75" in e for e in validate("linkedin_note", "Saw your 75 homes.", BRIEF, cfg))


def test_missing_opt_out_and_length(cfg: HostOpConfig) -> None:
    errs = validate("email_2", "word " * 95, BRIEF, cfg)
    assert any("missing opt-out" in e for e in errs) and any("too long" in e for e in errs)
    assert any("too long" in e for e in validate("linkedin_note", "a" * 301, BRIEF, cfg))
    assert any("missing subject" in e for e in validate("email_1", _email(cfg, "Hi"), BRIEF, cfg))


# --- generator -----------------------------------------------------------------------------------

class BadThenGoodLLM(MockLLM):
    """First draft attempt contains an invented stat; second attempt is clean."""

    def __init__(self) -> None:
        self.draft_calls = 0
        self.prompts: list[str] = []

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        out = super().complete_json(system, user, schema)
        if "hooks" in schema["properties"]:
            return out
        self.draft_calls += 1
        self.prompts.append(user)
        if self.draft_calls == 1:
            out["email_1"] = "Operators like you save 30% with HostOp."
        return out


def _seed(url: str) -> None:
    with session_scope(url) as s:
        op = Operator(name="Harbor Stays", normalized_name="harbor stays", domain="harbor.example", listing_count=42,
                      cities=["Austin"], direct_booking=True, instagram_handle="harbor_stays", is_synthetic=True)
        s.add(op)
        s.flush()
        s.add_all([Score(operator_id=op.id, total=70, tier="A"),
                   Evidence(operator_id=op.id, kind="listing_count", claim="42 listings in Austin", url="u"),
                   Signal(operator_id=op.id, kind="direct_booking"),
                   Contact(operator_id=op.id, full_name="Pat Sample", title="Owner", email="pat@harbor.example",
                           email_status="verified", is_synthetic=True)])


def test_generator_retries_with_feedback_and_stores_valid_drafts(tmp_path: Path, cfg: HostOpConfig) -> None:
    url = f"sqlite:///{tmp_path / 'g.db'}"
    init_db(url)
    _seed(url)
    llm = BadThenGoodLLM()
    with session_scope(url) as s:
        st = draft_operators(s, cfg, llm)
        drafts = s.query(Draft).all()
        assert s.query(Hook).count() == 3
    assert llm.draft_calls == 2 and "failed validation" in llm.prompts[1]
    assert st.invalid == 0 and {d.channel for d in drafts} == {"linkedin_note", "linkedin_followup", "email_1",
                                                              "email_2", "email_3", "instagram_dm"}
    assert all(d.is_synthetic and d.hook_id for d in drafts)
    assert all(cfg.sender.opt_out_line in d.body for d in drafts if d.channel.startswith("email"))


def test_generator_marks_needs_fix_when_still_invalid(tmp_path: Path, cfg: HostOpConfig) -> None:
    class AlwaysBad(BadThenGoodLLM):
        def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
            out = MockLLM.complete_json(self, system, user, schema)
            if "hooks" not in schema["properties"]:
                out["email_1"] = "Trusted by 500 operators."
            return out

    url = f"sqlite:///{tmp_path / 'b.db'}"
    init_db(url)
    _seed(url)
    with session_scope(url) as s:
        draft_operators(s, cfg, AlwaysBad())
        bad = s.query(Draft).filter(Draft.channel == "email_1").one()
    assert bad.status == "needs_fix" and bad.validation_errors


def test_no_email_drafts_without_verified_email(tmp_path: Path, cfg: HostOpConfig) -> None:
    url = f"sqlite:///{tmp_path / 'n.db'}"
    init_db(url)
    _seed(url)
    with session_scope(url) as s:
        c = s.query(Contact).one()
        c.email, c.email_status = None, None
    with session_scope(url) as s:
        draft_operators(s, cfg, MockLLM())
        assert not s.query(Draft).filter(Draft.channel.like("email%")).count()
