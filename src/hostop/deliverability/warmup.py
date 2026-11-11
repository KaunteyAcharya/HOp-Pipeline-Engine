"""Warm-up schedule planner. Produces a plan; the warm-up itself runs in your sending tool.

Conservative defaults: start at 5 cold emails/inbox/day after 14 days of tool warm-up, add 3/day per week,
cap at 30/inbox/day. These are common practitioner heuristics, not guarantees; adjust to your bounce/spam data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class WarmupDay:
    day: date
    week: int
    phase: str
    cold_per_inbox: int
    inboxes: int

    @property
    def total_cold(self) -> int:
        return self.cold_per_inbox * self.inboxes


def plan(domains: int, inboxes_per_domain: int, start: date, weeks: int = 6, warmup_only_days: int = 14,
         start_volume: int = 5, weekly_increase: int = 3, cap: int = 30) -> list[WarmupDay]:
    if inboxes_per_domain > 3:
        raise ValueError("keep to 3 inboxes per sending domain or fewer")
    inboxes = domains * inboxes_per_domain
    days = []
    for i in range(weeks * 7):
        d = start + timedelta(days=i)
        if i < warmup_only_days:
            days.append(WarmupDay(d, i // 7 + 1, "warm-up only", 0, inboxes))
            continue
        week_live = (i - warmup_only_days) // 7
        vol = min(cap, start_volume + weekly_increase * week_live)
        weekend = d.weekday() >= 5
        days.append(WarmupDay(d, i // 7 + 1, "weekend (warm-up only)" if weekend else "cold + warm-up",
                              0 if weekend else vol, inboxes))
    return days


def to_markdown(rows: list[WarmupDay]) -> str:
    lines = ["| week | first day | phase | cold/inbox/day | inboxes | cold/day total |", "|---|---|---|---|---|---|"]
    seen: set[tuple[int, str, int]] = set()
    for r in rows:
        key = (r.week, r.phase, r.cold_per_inbox)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"| {r.week} | {r.day.isoformat()} | {r.phase} | {r.cold_per_inbox} | {r.inboxes} | "
                     f"{r.total_cold} |")
    return "\n".join(lines)
