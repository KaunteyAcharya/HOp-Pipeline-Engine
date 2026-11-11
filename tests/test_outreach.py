import csv
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hostop.config import HostOpConfig, load_config
from hostop.crm.attio import AttioClient, AttioConfig
from hostop.db import init_db, session_scope
from hostop.deliverability.dns_check import check_domain
from hostop.deliverability.warmup import plan
from hostop.models import Contact, Draft, Operator, OutreachEvent, Suppression, Task
from hostop.outreach.export import export_email_sequences
from hostop.outreach.queues import build_queue
from hostop.outreach.review import approve, edit
from hostop.outreach.status import log_from_draft

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg() -> HostOpConfig:
    return load_config(ROOT / "config" / "hostop.yaml")


def _seed(url: str, cfg: HostOpConfig, n: int = 1, regime: str = "CAN-SPAM", synthetic: bool = True) -> None:
    with session_scope(url) as s:
        for i in range(n):
            op = Operator(name=f"Harbor {i}", normalized_name=f"harbor {i}", domain=f"h{i}.example",
                          instagram_handle=f"h{i}", is_synthetic=synthetic)
            s.add(op)
            s.flush()
            c = Contact(operator_id=op.id, full_name="Pat Sample", email=f"pat@h{i}.example", email_status="verified",
                        compliance_regime=regime, is_synthetic=synthetic)
            s.add(c)
            s.flush()
            for ch in ("email_1", "email_2", "email_3", "linkedin_note", "instagram_dm"):
                body = f"Hi Pat.\n\n{cfg.sender.opt_out_line}" if ch.startswith("email") else "Hi Pat."
                s.add(Draft(operator_id=op.id, contact_id=c.id, channel=ch, body=body, subject="hello",
                            hook_id="general-1", status="approved", is_synthetic=synthetic, brief={}))


@pytest.fixture()
def url(tmp_path: Path) -> str:
    u = f"sqlite:///{tmp_path / 'o.db'}"
    init_db(u)
    return u


# --- review ----------------------------------------------------------------------------------------

def test_approve_blocks_invalid_and_edit_revalidates(url: str, cfg: HostOpConfig) -> None:
    _seed(url, cfg)
    with session_scope(url) as s:
        d = s.query(Draft).filter(Draft.channel == "email_2").one()
        edit(s, d.id, "We guarantee results.", cfg)
        assert d.status == "needs_fix"
        with pytest.raises(ValueError):
            approve(s, d.id)
        edit(s, d.id, f"Short note.\n\n{cfg.sender.opt_out_line}", cfg)
        assert d.status == "edited"


# --- export ----------------------------------------------------------------------------------------

def test_export_only_complete_unsuppressed_sequences(url: str, cfg: HostOpConfig, tmp_path: Path) -> None:
    _seed(url, cfg, n=3)
    with session_scope(url) as s:
        s.add(Suppression(value="h1.example", kind="domain", reason="customer"))
        s.query(Draft).filter(Draft.channel == "email_3", Draft.operator_id == 3).one().status = "pending"
        res = export_email_sequences(s, cfg, "instantly", tmp_path / "out", "t")
    assert res.rows == 1 and res.skipped_suppressed == 1 and res.skipped_incomplete == 1
    assert res.path.name.startswith("SYNTHETIC_")
    with open(res.path, encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["email"] == "pat@h0.example" and cfg.sender.postal_address in row["email_1"]
    assert row["is_synthetic"] == "SYNTHETIC"


def test_export_excludes_review_regimes_by_default(url: str, cfg: HostOpConfig, tmp_path: Path) -> None:
    _seed(url, cfg, regime="GDPR")
    with session_scope(url) as s:
        assert export_email_sequences(s, cfg, "smartlead", tmp_path, "t").skipped_review == 1
        assert export_email_sequences(s, cfg, "smartlead", tmp_path, "t", include_review=True).rows == 1


def test_export_refuses_real_data_with_placeholder_sender(url: str, cfg: HostOpConfig, tmp_path: Path) -> None:
    _seed(url, cfg, synthetic=False)
    with session_scope(url) as s, pytest.raises(ValueError, match="sender"):
        export_email_sequences(s, cfg, "instantly", tmp_path, "t")


# --- queues + status -------------------------------------------------------------------------------

def test_queue_respects_daily_caps_and_skips_weekends(url: str, cfg: HostOpConfig) -> None:
    c2 = cfg.model_copy(deep=True)
    c2.outreach.daily_caps["linkedin_connect"] = 2
    _seed(url, c2, n=5)
    monday = date(2026, 11, 13)  # a Friday actually; weekends must be skipped
    with session_scope(url) as s:
        build_queue(s, c2, start=monday)
        days = [t.due_date for t in s.query(Task).filter(Task.channel == "linkedin_note").order_by(Task.due_date)]
    assert days == ["2026-11-13", "2026-11-13", "2026-11-16", "2026-11-16", "2026-11-17"]


def test_log_sent_closes_task_and_opt_out_suppresses(url: str, cfg: HostOpConfig) -> None:
    _seed(url, cfg)
    with session_scope(url) as s:
        build_queue(s, cfg)
        note = s.query(Draft).filter(Draft.channel == "linkedin_note").one()
        log_from_draft(s, note.id, "sent")
        assert s.query(Task).filter(Task.draft_id == note.id).one().status == "done"
        email = s.query(Draft).filter(Draft.channel == "email_1").one()
        log_from_draft(s, email.id, "opt_out")
        assert s.query(Suppression).filter(Suppression.value == "pat@h0.example").count() == 1
        assert {e.channel for e in s.query(OutreachEvent)} == {"linkedin", "email"}
        with pytest.raises(ValueError):
            log_from_draft(s, email.id, "meeting")


# --- deliverability --------------------------------------------------------------------------------

def _resolver(records: dict[tuple[str, str], list[str]]):  # type: ignore[no-untyped-def]
    return lambda name, rtype: records.get((name, rtype), [])


def test_dns_check_healthy_domain() -> None:
    r = check_domain("send.example", _resolver({
        ("send.example", "MX"): ["10 mx.example."],
        ("send.example", "TXT"): ["v=spf1 include:_spf.google.com ~all"],
        ("_dmarc.send.example", "TXT"): ["v=DMARC1; p=none; rua=mailto:d@send.example"],
        ("google._domainkey.send.example", "TXT"): ["v=DKIM1; k=rsa; p=MIIB"],
    }))
    assert r.ok and r.dmarc_policy == "none" and r.dkim_selectors == ["google"]


def test_dns_check_flags_problems() -> None:
    r = check_domain("bad.example", _resolver({
        ("bad.example", "TXT"): ["v=spf1 +all", "v=spf1 include:x ~all"],
        ("_dmarc.bad.example", "TXT"): ["v=DMARC1; p=reject"],
    }))
    text = " ".join(r.issues)
    assert "no MX" in text and "multiple SPF" in text and "rua" in text and "DKIM" in text


def test_warmup_plan() -> None:
    days = plan(2, 2, date(2026, 11, 16), weeks=4)
    assert all(d.cold_per_inbox == 0 for d in days[:14])
    live = [d for d in days[14:] if d.day.weekday() < 5]
    assert live[0].cold_per_inbox == 5 and live[0].total_cold == 20 and max(d.cold_per_inbox for d in days) <= 30
    with pytest.raises(ValueError):
        plan(1, 5, date.today())


# --- Attio -----------------------------------------------------------------------------------------

def test_attio_request_shapes() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        calls.append((req.method, str(req.url), json.loads(req.content or b"{}")))
        return httpx.Response(200, json={"data": {"id": {"record_id": "rec-1"}}})

    client = AttioClient(AttioConfig("k"), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.upsert_company("Harbor", "harbor.com") == "rec-1"
    client.upsert_person("pat@harbor.com", "Pat Lee", "harbor.com")
    client.set_stage("rec-1", "contacted")
    client.add_note("companies", "rec-1", "t", "c")
    assert calls[0][0] == "PUT" and "matching_attribute=domains" in calls[0][1]
    assert calls[0][2] == {"data": {"values": {"name": [{"value": "Harbor"}], "domains": [{"domain": "harbor.com"}]}}}
    assert "matching_attribute=email_addresses" in calls[1][1]
    assert calls[2][1].endswith("/v2/lists/hostop_pipeline/entries")
    assert calls[2][2]["data"]["entry_values"] == {"stage": "contacted"}  # type: ignore[index]
    assert calls[3][0] == "POST" and calls[3][2]["data"]["format"] == "plaintext"  # type: ignore[index]


# --- API -------------------------------------------------------------------------------------------

def test_reply_webhook_auth_and_opt_out(url: str, cfg: HostOpConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    import hostop.api.app as api
    from hostop.settings import get_settings

    _seed(url, cfg)
    monkeypatch.setattr(api, "DB_URL", url)
    monkeypatch.setenv("HOSTOP_API_TOKEN", "secret")
    get_settings.cache_clear()
    client = TestClient(api.app)
    body = {"email": "pat@h0.example", "text": "Please remove me from your list"}
    assert client.post("/webhooks/reply", json=body).status_code == 401
    r = client.post("/webhooks/reply", json=body, headers={"X-HostOp-Token": "secret"}).json()
    assert r == {"logged": ["replied", "opt_out"], "suppressed": True}
    r2 = client.post("/webhooks/reply", headers={"X-HostOp-Token": "secret"},
                     json={"email": "pat@h0.example", "text": "Sounds good, send times"}).json()
    assert r2["suggest_positive"] is True and r2["logged"] == ["replied"]
    get_settings.cache_clear()
