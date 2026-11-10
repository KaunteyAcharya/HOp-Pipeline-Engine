"""HostOp Pipeline dashboard (read-only preview; full review/queue pages arrive in Phase 8).

Run: streamlit run dashboard/app.py -- --demo
"""

from __future__ import annotations

import sys

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from hostop.db import init_db, session_scope
from hostop.models import Contact, Evidence, Operator, OperatorSource, Score
from hostop.scoring.icp import explain
from hostop.settings import get_settings

DEMO = "--demo" in sys.argv
URL = "sqlite:///hostop_demo.db" if DEMO else get_settings().hostop_db_url
init_db(URL)

st.set_page_config(page_title="HostOp Pipeline", layout="wide")
st.title("HostOp Pipeline Engine")
if DEMO:
    st.warning("DEMO MODE: every operator, contact and number on this page is SYNTHETIC.")
st.caption("Nothing here sends outreach. Drafts are for human review only.")

with session_scope(URL) as s:
    total = s.scalar(select(func.count(Operator.id))) or 0
    by_source = s.execute(select(OperatorSource.source, func.count(func.distinct(OperatorSource.operator_id)))
                          .group_by(OperatorSource.source)).all()
    tiers = dict(s.execute(select(Score.tier, func.count()).group_by(Score.tier)).tuples().all())
    analyzed = s.scalar(select(func.count(Operator.id)).where(Operator.analyzed_at.is_not(None))) or 0
    verified = s.scalar(select(func.count(Contact.id)).where(Contact.email_status == "verified")) or 0
    rows = s.execute(
        select(Operator.id, Operator.name, Operator.domain, Operator.listing_count, Operator.cities, Operator.pms,
               Operator.direct_booking, Score.tier, Score.total)
        .join(Score, Score.operator_id == Operator.id, isouter=True)
        .order_by(Score.total.desc().nulls_last()).limit(2000)).all()

st.subheader("Discovery progress")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Resolved operators", f"{total:,}", f"{min(100, total / 10):.0f}% of 1,000")
c2.metric("Tier A", tiers.get("A", 0))
c3.metric("Tier B", tiers.get("B", 0))
c4.metric("Sites analyzed", analyzed)
c5.metric("Verified contacts", verified)
st.progress(min(1.0, total / 1000))
st.bar_chart(pd.DataFrame(by_source, columns=["source", "operators"]).set_index("source"))
st.caption("Operators per source (deduplicated; one operator can appear in several sources).")

st.subheader("Operators")
df = pd.DataFrame(rows, columns=["id", "name", "domain", "listings", "cities", "pms", "direct_booking", "tier",
                                 "score"])
tier_pick = st.multiselect("Tier", ["A", "B", "C"], default=["A", "B"])
view = df[df["tier"].isin(tier_pick)]
st.dataframe(view, use_container_width=True, hide_index=True)

st.subheader("Operator detail")
op_id = st.number_input("Operator id", min_value=1, value=int(view["id"].iloc[0]) if len(view) else 1)
with session_scope(URL) as s:
    info = explain(s, int(op_id))
    contacts = s.scalars(select(Contact).where(Contact.operator_id == int(op_id))).all()
    evidence = s.scalars(select(Evidence).where(Evidence.operator_id == int(op_id))).all()
    contact_rows = [(c.full_name, c.title, c.email, c.email_source, c.compliance_regime, c.linkedin_search_url)
                    for c in contacts]
    ev_rows = [(e.id, e.kind, e.claim, e.url) for e in evidence]
if info:
    st.markdown(f"**{info['operator']}** {info['domain'] or ''}: **{info['total']} pts, Tier {info['tier']}**")
    for f in info["factors"]:
        with st.expander(f"{f['factor']}: +{f['points']} ({f['reason']})"):
            for e in f["evidence"]:
                st.write(f"#{e['id']} {e['claim']}", e["url"] or "")
    st.markdown("**Contacts**")
    st.dataframe(pd.DataFrame(contact_rows, columns=["name", "title", "email", "source", "regime", "linkedin_search"]),
                 hide_index=True, use_container_width=True)
    st.markdown("**All evidence**")
    st.dataframe(pd.DataFrame(ev_rows, columns=["id", "kind", "claim", "url"]), hide_index=True,
                 use_container_width=True)
else:
    st.info("No operator with that id.")
