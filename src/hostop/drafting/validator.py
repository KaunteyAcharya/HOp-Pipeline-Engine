"""Deterministic draft validator. A draft that fails any check is never marked ready for review-approval.

Checks: banned phrases, fake familiarity, length limits, opt-out line in emails, unsupported claims
(numbers not present in evidence/HostOp facts, testimonial/social-proof language, unverified PMS integration
claims, percentages, guarantees), and unresolved template placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from hostop.config import HostOpConfig

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
PLACEHOLDER = re.compile(r"\{\{|\}\}|\[(?:first ?name|name|company|city)\]|<[A-Z ]{3,}>", re.I)
SOCIAL_PROOF = re.compile(
    r"\b(trusted by|customers like|clients like|our (customers|clients) include|case study|testimonial|"
    r"leading operators|hundreds of operators|thousands of)\b", re.I)
GUARANTEE = re.compile(r"\b(guarantee[sd]?|risk[- ]free|100%)\b", re.I)
PERCENT = re.compile(r"\d+\s*%|\bpercent\b", re.I)


def allowed_numbers(brief: dict[str, Any]) -> set[str]:
    texts: list[str] = [str(f["claim"]) for f in brief.get("evidence", [])]
    texts += [str(x) for x in brief.get("hostop_facts", [])]
    op = brief.get("operator", {})
    if op.get("listing_count") is not None:
        texts.append(str(op["listing_count"]))
    return {n.replace(",", "") for t in texts for n in NUM.findall(t)}


def _contains_any(text: str, phrases: Iterable[str]) -> list[str]:
    low = text.lower()
    return [p for p in phrases if p.lower() in low]


def validate(
    channel: str, text: str, brief: dict[str, Any], cfg: HostOpConfig, subject: str | None = None
) -> list[str]:
    errors: list[str] = []
    full = f"{subject or ''}\n{text}"
    for p in _contains_any(full, cfg.banned_phrases):
        errors.append(f"banned phrase: '{p}'")
    for pat in cfg.fake_familiarity_patterns:
        if re.search(pat, full, re.I):
            errors.append(f"fake familiarity: /{pat}/")
    if PLACEHOLDER.search(full):
        errors.append("unresolved placeholder")
    ok_nums = allowed_numbers(brief)
    for n in NUM.findall(full):
        if n.replace(",", "") not in ok_nums:
            errors.append(f"unsupported number: {n}")
    if SOCIAL_PROOF.search(full):
        errors.append("unsupported claim: social proof / testimonial language")
    if GUARANTEE.search(full) or PERCENT.search(full):
        errors.append("unsupported claim: guarantee or percentage")
    pms_names = "|".join(re.escape(p) for p in cfg.pms_tech)
    if re.search(rf"\b(integrat\w*|syncs?|plugs? into|connects? (to|with))\b[^.]{{0,40}}\b({pms_names})\b", full, re.I):
        errors.append("unsupported claim: HostOp PMS integration is not verified")
    lim = cfg.limits
    if channel == "linkedin_note" and len(text) > lim.linkedin_note_chars:
        errors.append(f"too long: {len(text)} > {lim.linkedin_note_chars} chars")
    if channel == "instagram_dm" and len(text) > lim.instagram_dm_chars:
        errors.append(f"too long: {len(text)} > {lim.instagram_dm_chars} chars")
    if channel.startswith("email"):
        words = len(text.split())
        if words > lim.email_words:
            errors.append(f"too long: {words} > {lim.email_words} words")
        if cfg.sender.opt_out_line.lower() not in text.lower():
            errors.append("missing opt-out line")
        if channel == "email_1" and not (subject or "").strip():
            errors.append("missing subject")
        if subject and len(subject) > 60:
            errors.append("subject over 60 chars")
    if not text.strip():
        errors.append("empty")
    return errors
