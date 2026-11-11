"""Hook variants per segment + draft generation with validate-and-retry. Drafts are never sent by this code."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from hostop.compliance.optout import is_suppressed
from hostop.config import HostOpConfig
from hostop.drafting.brief import build_brief, segment_for
from hostop.drafting.llm import LLM, LLMRefusalError
from hostop.drafting.prompts import DRAFT_SCHEMA, HOOKS_SCHEMA, VOICE, draft_prompt, hooks_prompt
from hostop.drafting.validator import validate
from hostop.models import Contact, Draft, Hook, Operator, Score

CHANNEL_MAP = [("linkedin_note", "linkedin_note"), ("linkedin_followup", "linkedin_followup"),
               ("email_1", "email_1"), ("email_2", "email_2"), ("email_3", "email_3"),
               ("instagram_dm", "instagram_dm")]


def hook_id(segment: str, text: str) -> str:
    return f"{segment}-{hashlib.sha1(text.encode()).hexdigest()[:8]}"


def ensure_hooks(s: Session, segment: str, llm: LLM, cfg: HostOpConfig, example: dict[str, object]) -> list[Hook]:
    existing = s.scalars(select(Hook).where(Hook.segment == segment).order_by(Hook.created_at)).all()
    if len(existing) >= 3:
        return list(existing[:3])
    system, user = hooks_prompt(segment, cfg, example)
    out = llm.complete_json(system, user, HOOKS_SCHEMA)
    hooks = []
    for h in out["hooks"][:3]:
        hid = hook_id(segment, h["text"])
        hook = s.get(Hook, hid) or Hook(id=hid, segment=segment, text=h["text"])
        s.add(hook)
        hooks.append(hook)
    s.flush()
    return hooks


@dataclass
class DraftStats:
    operators: int = 0
    drafts: int = 0
    valid: int = 0
    invalid: int = 0
    refused: int = 0
    skipped_suppressed: int = 0
    by_hook: dict[str, int] = field(default_factory=dict)


def _validate_all(out: dict[str, object], brief: dict[str, object], cfg: HostOpConfig) -> dict[str, list[str]]:
    errs: dict[str, list[str]] = {}
    for key, channel in CHANNEL_MAP:
        subject = str(out["email_subject"]) if channel == "email_1" else None
        e = validate(channel, str(out[key]), brief, cfg, subject=subject)
        if e:
            errs[channel] = e
    used = set(out.get("evidence_ids_used") or [])  # type: ignore[call-overload]
    known = {f["id"] for f in brief["evidence"]}  # type: ignore[attr-defined]
    if used - known:
        errs.setdefault("evidence", []).append(f"cited unknown evidence ids {sorted(used - known)}")
    return errs


def draft_operators(s: Session, cfg: HostOpConfig, llm: LLM, limit: int = 20,
                    tiers: tuple[str, ...] = ("A", "B"), max_attempts: int = 2) -> DraftStats:
    st = DraftStats()
    q = (select(Operator).join(Score, Score.operator_id == Operator.id)
         .where(Score.tier.in_(tiers), Operator.contacts.any(), ~Operator.id.in_(select(Draft.operator_id)))
         .options(selectinload(Operator.evidence), selectinload(Operator.signals), selectinload(Operator.contacts))
         .order_by(Score.total.desc()).limit(limit))
    rotation: dict[str, int] = {}
    for op in s.scalars(q).all():
        contact: Contact | None = next((c for c in op.contacts if c.email), None) or (op.contacts[0]
                                                                                     if op.contacts else None)
        if is_suppressed(s, email=contact.email if contact else None, domain=op.domain, handle=op.instagram_handle):
            st.skipped_suppressed += 1
            continue
        st.operators += 1
        brief = build_brief(op, contact, cfg)
        segment = segment_for(op)
        hooks = ensure_hooks(s, segment, llm, cfg, brief)
        hook = hooks[rotation.get(segment, 0) % len(hooks)]  # round-robin for A/B/C testing
        rotation[segment] = rotation.get(segment, 0) + 1
        feedback: list[str] | None = None
        out: dict[str, object] = {}
        errs: dict[str, list[str]] = {}
        try:
            for _ in range(max_attempts):
                out = llm.complete_json(VOICE, draft_prompt(brief, hook.text, cfg, feedback), DRAFT_SCHEMA)
                for k in ("email_1", "email_2", "email_3"):
                    out[k] = f"{str(out[k]).rstrip()}\n\n{cfg.sender.opt_out_line}"
                errs = _validate_all(out, brief, cfg)
                if not errs:
                    break
                feedback = [f"{ch}: {e}" for ch, es in errs.items() for e in es]
        except LLMRefusalError:
            st.refused += 1
            continue
        for key, channel in CHANNEL_MAP:
            if channel.startswith("email") and not (contact and contact.email):
                continue  # no verified email: no email drafts
            if channel == "instagram_dm" and not op.instagram_handle:
                continue
            ch_errs = errs.get(channel, []) + errs.get("evidence", [])
            s.add(Draft(operator_id=op.id, contact_id=contact.id if contact else None, channel=channel,
                        hook_id=hook.id, subject=str(out["email_subject"]) if channel.startswith("email") else None,
                        body=str(out[key]), brief=brief, validation_errors=ch_errs,
                        status="pending" if not ch_errs else "needs_fix", is_synthetic=op.is_synthetic))
            st.drafts += 1
            st.valid += 0 if ch_errs else 1
            st.invalid += 1 if ch_errs else 0
            st.by_hook[hook.id] = st.by_hook.get(hook.id, 0) + 1
    return st
