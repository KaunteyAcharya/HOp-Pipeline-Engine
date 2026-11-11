"""Funnel analytics from manually logged OutreachEvents.

Rules: every rate is shown with its numerator and denominator; rates with a denominator under
SMALL_SAMPLE are flagged and come with a 95% Wilson interval; nothing is projected or extrapolated.
A contact counts once per stage per group (dedup on operator/contact), so a resend does not inflate n.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hostop.models import Contact, Draft, Operator, OutreachEvent, Score, Task

STAGES = ("sent", "replied", "positive", "demo_booked", "demo_held")
SMALL_SAMPLE = 30


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


@dataclass
class Rate:
    k: int
    n: int

    @property
    def small(self) -> bool:
        return self.n < SMALL_SAMPLE

    def fmt(self) -> str:
        if self.n == 0:
            return "n/a (n=0)"
        lo, hi = wilson(self.k, self.n)
        s = f"{self.k}/{self.n} = {self.k / self.n:.0%}"
        return s + (f" [95% CI {lo:.0%}-{hi:.0%}] SMALL SAMPLE" if self.small else "")


@dataclass
class Funnel:
    group: str
    counts: dict[str, int] = field(default_factory=dict)

    def rate(self, num: str, den: str) -> Rate:
        return Rate(self.counts.get(num, 0), self.counts.get(den, 0))


def funnels(s: Session, by: str, since: datetime | None = None) -> list[Funnel]:
    """by: channel | hook_id | list_name | segment."""
    q = select(OutreachEvent)
    if since is not None:
        q = q.where(OutreachEvent.occurred_at >= since)
    seen: dict[str, dict[str, set[tuple[int, int | None]]]] = defaultdict(lambda: defaultdict(set))
    for e in s.scalars(q):
        if e.event not in STAGES:
            continue
        key = (e.hook_id or "unknown").rsplit("-", 1)[0] if by == "segment" else (getattr(e, by) or "unknown")
        seen[key][e.event].add((e.operator_id, e.contact_id))
    return [Funnel(g, {st: len(v[st]) for st in STAGES}) for g, v in sorted(seen.items())]


def pipeline_snapshot(s: Session) -> dict[str, int]:
    def count(q: object) -> int:
        return int(s.scalar(q) or 0)  # type: ignore[call-overload]

    return {
        "operators": count(select(func.count(Operator.id))),
        "tier_a": count(select(func.count(Score.id)).where(Score.tier == "A")),
        "tier_b": count(select(func.count(Score.id)).where(Score.tier == "B")),
        "verified_contacts": count(select(func.count(Contact.id)).where(Contact.email_status == "verified")),
        "drafts_pending": count(select(func.count(Draft.id)).where(Draft.status == "pending")),
        "drafts_needs_fix": count(select(func.count(Draft.id)).where(Draft.status == "needs_fix")),
        "drafts_ready": count(select(func.count(Draft.id)).where(Draft.status.in_(("approved", "edited")))),
        "tasks_open": count(select(func.count(Task.id)).where(Task.status == "todo")),
        "opt_outs": count(select(func.count(OutreachEvent.id)).where(OutreachEvent.event == "opt_out")),
        "bounces": count(select(func.count(OutreachEvent.id)).where(OutreachEvent.event == "bounced")),
    }


def _table(fs: list[Funnel], label: str) -> list[str]:
    if not fs:
        return ["_No events logged in this window._", ""]
    out = [f"| {label} | sent | replied | reply rate | positive / replied | demos booked | held |",
           "|---|---|---|---|---|---|---|"]
    for f in fs:
        c = f.counts
        out.append(f"| {f.group} | {c['sent']} | {c['replied']} | {f.rate('replied', 'sent').fmt()} | "
                   f"{f.rate('positive', 'replied').fmt()} | {c['demo_booked']} | {c['demo_held']} |")
    return [*out, ""]


def weekly_report(s: Session, synthetic: bool, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=7)
    snap = pipeline_snapshot(s)
    lines = ["# HostOp weekly outbound report", ""]
    if synthetic:
        lines += ["> **SYNTHETIC DEMO DATA.** Every operator, contact and event below is fabricated for the demo.",
                  "> None of these numbers describe real outreach results.", ""]
    lines += [f"Generated {now:%Y-%m-%d %H:%M} UTC. Window: last 7 days ({since:%Y-%m-%d} to {now:%Y-%m-%d}) "
              "and all time.", "",
              "**How to read this.** Rates show numerator/denominator. Any rate with a denominator under "
              f"{SMALL_SAMPLE} is flagged SMALL SAMPLE with a 95% Wilson interval; treat it as noise, not a "
              "trend. No figure here is projected forward.", "",
              "## Pipeline", "", "| metric | count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in snap.items()] + [""]
    for title, window in (("Last 7 days", since), ("All time", None)):
        lines += [f"## {title}", ""]
        for by, label in (("channel", "channel"), ("segment", "segment"), ("hook_id", "hook"),
                          ("list_name", "list")):
            lines += [f"### By {label}", "", *_table(funnels(s, by, window), label)]
    lines += ["## Notes for the reviewer", "",
              "- Events are logged by hand (`hostop log`) or via the reply webhook; unlogged sends are invisible.",
              "- Positive replies are only those a human marked positive.",
              "- Compare hooks only once each has 30+ sends; before that, keep rotating evenly.", ""]
    return "\n".join(lines)
