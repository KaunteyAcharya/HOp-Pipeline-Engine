"""Builds the SYNTHETIC demo database from scratch (used by hosted demos such as Streamlit Community Cloud).

Leaves some drafts pending so the review screen has work in it, approves the rest, builds the manual queue and
adds SYNTHETIC events so analytics has numbers. Never touches a non-demo database.
"""

from __future__ import annotations

from sqlalchemy import func, select

from hostop.cli import DEMO_DB_URL, run_all
from hostop.config import load_config
from hostop.db import init_db, session_scope
from hostop.demo.events import seed_events
from hostop.models import Draft, Operator
from hostop.outreach.queues import build_queue
from hostop.outreach.review import approve


def ensure_demo_data() -> bool:
    """Return True if data was built, False if it already existed."""
    init_db(DEMO_DB_URL)
    with session_scope(DEMO_DB_URL) as s:
        if s.scalar(select(func.count(Operator.id))):
            return False
    run_all(demo=True, web=False)
    with session_scope(DEMO_DB_URL) as s:
        op_ids = sorted({d.operator_id for d in s.scalars(select(Draft).where(Draft.status == "pending"))})
        for d in s.scalars(select(Draft).where(Draft.status == "pending",
                                               Draft.operator_id.in_(op_ids[: len(op_ids) * 2 // 3]))):
            if not d.validation_errors:
                approve(s, d.id)
        build_queue(s, load_config())
        seed_events(s)
    return True
