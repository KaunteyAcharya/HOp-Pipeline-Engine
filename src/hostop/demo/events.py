"""SYNTHETIC outreach events for the demo dashboard and report. Refuses to touch non-synthetic drafts.

The probabilities below are arbitrary demo knobs, not benchmarks or expected results.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hostop.models import Draft, OutreachEvent
from hostop.outreach.status import CHANNEL_GROUP

FIRST_TOUCH = ("email_1", "linkedin_note", "instagram_dm")


def seed_events(s: Session, seed: int = 7, now: datetime | None = None) -> int:
    if s.scalar(select(OutreachEvent.id).where(OutreachEvent.note == "SYNTHETIC demo event").limit(1)):
        return 0
    now = now or datetime.now(UTC)
    rng = random.Random(seed)
    drafts = s.scalars(select(Draft).where(Draft.channel.in_(FIRST_TOUCH), Draft.is_synthetic.is_(True))).all()
    n = 0
    for d in drafts:
        when = now - timedelta(days=rng.randint(0, 20), hours=rng.randint(0, 23))
        chain = ["sent"]
        if rng.random() < 0.15:
            chain.append("replied")
            if rng.random() < 0.4:
                chain.append("positive")
                if rng.random() < 0.5:
                    chain.append("demo_booked")
                    if rng.random() < 0.7:
                        chain.append("demo_held")
        for i, ev in enumerate(chain):
            s.add(OutreachEvent(operator_id=d.operator_id, contact_id=d.contact_id,
                                channel=CHANNEL_GROUP.get(d.channel, d.channel), hook_id=d.hook_id,
                                list_name="tier_ab", event=ev, note="SYNTHETIC demo event", is_synthetic=True,
                                occurred_at=when + timedelta(days=i * 2)))
            n += 1
    return n
