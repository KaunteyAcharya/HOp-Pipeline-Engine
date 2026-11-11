"""FastAPI hooks for n8n. None of these endpoints send outreach.

Auth: every request must carry header X-HostOp-Token == HOSTOP_API_TOKEN.
Demo: set HOSTOP_DEMO=1 to use the demo database and mock LLM.
Run: uvicorn hostop.api.app:app --port 8000
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from hostop.compliance.optout import is_opt_out, suppress
from hostop.config import load_config
from hostop.db import init_db, session_scope
from hostop.models import Contact, Draft, Operator, Score
from hostop.outreach.status import log_event
from hostop.scoring.icp import explain, score_operator
from hostop.settings import get_settings

DEMO = os.environ.get("HOSTOP_DEMO") == "1"
DB_URL = "sqlite:///hostop_demo.db" if DEMO else get_settings().hostop_db_url
POSITIVE_HINTS = ("interested", "sounds good", "happy to chat", "let's talk", "book", "calendar", "demo",
                  "send times", "what times", "tell me more")

app = FastAPI(title="HostOp Pipeline hooks", description="Drafts and logs only. Never sends outreach.")


def auth(x_hostop_token: str = Header(default="")) -> None:
    expected = get_settings().hostop_api_token
    if not expected or (expected == "change-me" and not DEMO):
        raise HTTPException(503, "set HOSTOP_API_TOKEN before exposing the API")
    if x_hostop_token != expected:
        raise HTTPException(401, "bad token")


@app.on_event("startup")
def _startup() -> None:
    init_db(DB_URL)


@app.get("/health")
def health() -> dict[str, Any]:
    with session_scope(DB_URL) as s:
        n = s.scalar(select(func.count(Operator.id))) or 0
    return {"ok": True, "demo": DEMO, "operators": n}


@app.post("/operators/{operator_id}/score", dependencies=[Depends(auth)])
def score_one(operator_id: int) -> dict[str, Any]:
    cfg = load_config()
    with session_scope(DB_URL) as s:
        op = s.scalars(select(Operator).where(Operator.id == operator_id)
                       .options(selectinload(Operator.evidence), selectinload(Operator.signals))).first()
        if op is None:
            raise HTTPException(404, "operator not found")
        total, tier, factors = score_operator(op, cfg)
        s.query(Score).filter(Score.operator_id == operator_id).delete()
        s.add(Score(operator_id=operator_id, total=total, tier=tier, breakdown=[f.__dict__ for f in factors]))
        s.flush()
        return explain(s, operator_id) or {}


@app.post("/operators/{operator_id}/draft", dependencies=[Depends(auth)])
def draft_one(operator_id: int) -> dict[str, Any]:
    """Generate drafts for one operator (status pending/needs_fix). A human approves them later."""
    from hostop.drafting.generator import draft_operators
    from hostop.drafting.llm import LLM, AnthropicLLM
    from hostop.drafting.mock_llm import MockLLM

    cfg = load_config()
    st = get_settings()
    llm: LLM = MockLLM() if DEMO else AnthropicLLM(st.anthropic_model, st.anthropic_api_key or None)
    with session_scope(DB_URL) as s:
        if s.get(Operator, operator_id) is None:
            raise HTTPException(404, "operator not found")
        res = draft_operators(s, cfg, llm, limit=1, only_ids=[operator_id])
        drafts = s.scalars(select(Draft).where(Draft.operator_id == operator_id)).all()
        return {"stats": res.__dict__, "drafts": [{"id": d.id, "channel": d.channel, "status": d.status,
                                                   "hook_id": d.hook_id, "errors": d.validation_errors,
                                                   "body": d.body} for d in drafts]}


class ReplyIn(BaseModel):
    email: str
    text: str
    channel: str = "email"
    hook_id: str | None = None
    list_name: str | None = None
    positive: bool | None = None  # set by a human or a classifier step you trust; else only a suggestion


@app.post("/webhooks/reply", dependencies=[Depends(auth)])
def reply_webhook(body: ReplyIn) -> dict[str, Any]:
    with session_scope(DB_URL) as s:
        c = s.scalars(select(Contact).where(Contact.email == body.email.lower())).first()
        if c is None:
            raise HTTPException(404, "unknown contact")
        log_event(s, c.operator_id, body.channel, "replied", c.id, body.hook_id, body.list_name,
                  note=body.text[:500], is_synthetic=c.is_synthetic)
        if is_opt_out(body.text):
            suppress(s, body.email, "opt_out")
            log_event(s, c.operator_id, body.channel, "opt_out", c.id, body.hook_id, body.list_name,
                      is_synthetic=c.is_synthetic)
            return {"logged": ["replied", "opt_out"], "suppressed": True}
        logged = ["replied"]
        if body.positive:
            log_event(s, c.operator_id, body.channel, "positive", c.id, body.hook_id, body.list_name,
                      is_synthetic=c.is_synthetic)
            logged.append("positive")
        suggested = any(h in body.text.lower() for h in POSITIVE_HINTS)
        return {"logged": logged, "suppressed": False, "suggest_positive": suggested and not body.positive}
