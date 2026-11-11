"""Prompts and JSON schemas for hook and draft generation."""

from __future__ import annotations

import json
from typing import Any

from hostop.config import HostOpConfig

VOICE = """You write outbound messages for HostOp's first GTM hire to send personally, after human review.
Voice: plain, specific, human. Short sentences. No hype, no buzzwords, no exclamation marks.
Rules you must follow:
- Use ONLY facts in the brief. Operator facts come from `evidence`; HostOp facts come from `hostop_facts`.
- Do not invent numbers, customers, results, testimonials, integrations, or prior contact. Do not claim HostOp
  integrates with any PMS. Do not pretend to know the reader personally.
- Only use a number if it appears in the brief.
- Do not write an opt-out line or a signature; they are added automatically.
- The ask is a short demo with HostOp's founder."""


def hooks_prompt(segment: str, cfg: HostOpConfig, example_brief: dict[str, Any]) -> tuple[str, str]:
    user = (f"Segment: {segment}\nWrite 3 distinct opening hooks (one sentence each, under 25 words) for STR "
            f"operators in this segment. Each hook connects an observable fact type to a HostOp capability.\n"
            f"Use placeholders only as plain words like 'your team', never brackets.\n"
            f"HostOp facts: {json.dumps(cfg.company.facts)}\nExample brief:\n{json.dumps(example_brief)}")
    return VOICE, user


HOOKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"hooks": {"type": "array", "items": {
        "type": "object",
        "properties": {"angle": {"type": "string"}, "text": {"type": "string"}},
        "required": ["angle", "text"], "additionalProperties": False}}},
    "required": ["hooks"], "additionalProperties": False,
}


def draft_prompt(brief: dict[str, Any], hook_text: str, cfg: HostOpConfig, feedback: list[str] | None = None) -> str:
    lim = cfg.limits
    parts = [
        f"Brief (the only facts you may use):\n{json.dumps(brief, default=str)}",
        f"Opening angle to use: {hook_text}",
        f"Write: linkedin_note (max {lim.linkedin_note_chars - 20} characters, no pitch, just why you're connecting); "
        f"linkedin_followup (after they accept, under 80 words); email_subject (under 50 chars, lowercase is fine); "
        f"email_1 (max {lim.email_words - 20} words); email_2 and email_3 (short follow-ups, max 50 words each, "
        f"each adds one new specific point, never 'just following up'); "
        f"instagram_dm (max {lim.instagram_dm_chars - 100} characters, casual); evidence_ids_used (ids you relied on).",
        "Greet by first name if present, otherwise 'Hi there'.",
    ]
    if feedback:
        parts.append("Your previous attempt failed validation. Fix all of these:\n- " + "\n- ".join(feedback))
    return "\n\n".join(parts)


DRAFT_FIELDS = ["linkedin_note", "linkedin_followup", "email_subject", "email_1", "email_2", "email_3",
                "instagram_dm"]
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {**{f: {"type": "string"} for f in DRAFT_FIELDS},
                   "evidence_ids_used": {"type": "array", "items": {"type": "integer"}}},
    "required": [*DRAFT_FIELDS, "evidence_ids_used"],
    "additionalProperties": False,
}
