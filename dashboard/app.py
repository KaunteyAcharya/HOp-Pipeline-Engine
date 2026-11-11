"""HostOp Pipeline dashboard: pipeline, draft review, manual task queue, deliverability and analytics.

Run: streamlit run dashboard/app.py -- --demo
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from hostop.analytics.funnel import STAGES, funnels, weekly_report
from hostop.config import load_config
from hostop.db import init_db, session_scope
from hostop.deliverability.dns_check import check_domain
from hostop.deliverability.warmup import plan, to_markdown
from hostop.models import Contact, Draft, Evidence, Operator, OperatorSource, Score, Task
from hostop.outreach.review import approve, edit, reject
from hostop.outreach.status import EVENTS, log_from_draft
from hostop.scoring.icp import explain
from hostop.settings import get_settings

DEMO = "--demo" in sys.argv
URL = "sqlite:///hostop_demo.db" if DEMO else get_settings().hostop_db_url
init_db(URL)
CFG = load_config(Path("config/hostop.yaml"))

st.set_page_config(page_title="HostOp Pipeline", layout="wide")
st.title("HostOp Pipeline Engine")
if DEMO:
    st.warning("DEMO MODE: every operator, contact and number on this page is SYNTHETIC.")
st.caption("Nothing here sends outreach. Drafts are for human review only.")

tab_pipe, tab_review, tab_queue, tab_deliv, tab_stats = st.tabs(
    ["Pipeline", "Draft review", "Manual queue", "Deliverability", "Analytics"])
with tab_pipe:

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
        cols = ["name", "title", "email", "source", "regime", "linkedin_search"]
        st.dataframe(pd.DataFrame(contact_rows, columns=cols),
                     hide_index=True, use_container_width=True)
        st.markdown("**All evidence**")
        st.dataframe(pd.DataFrame(ev_rows, columns=["id", "kind", "claim", "url"]), hide_index=True,
                     use_container_width=True)
    else:
        st.info("No operator with that id.")

# --- Draft review -------------------------------------------------------------------------------------
with tab_review:
    st.caption("Approve, edit or reject. Edits are re-validated; drafts with validation errors cannot be approved.")
    status_pick = st.selectbox("Status", ["pending", "needs_fix", "approved", "edited", "rejected"])
    with session_scope(URL) as s:
        drafts = s.execute(
            select(Draft.id, Operator.name, Draft.channel, Draft.hook_id, Draft.subject, Draft.body,
                   Draft.validation_errors, Draft.brief)
            .join(Operator, Operator.id == Draft.operator_id).where(Draft.status == status_pick)
            .order_by(Draft.operator_id, Draft.channel).limit(100)).all()
    st.write(f"{len(drafts)} shown (max 100)")
    for d_id, op_name, channel, hook, subject, body, errors, brief in drafts:
        with st.expander(f"#{d_id} {op_name} / {channel} / {hook}"):
            if errors:
                st.error("; ".join(map(str, errors)))
            new_subject = st.text_input("Subject", subject or "", key=f"s{d_id}") if channel.startswith("email") \
                else None
            new_body = st.text_area("Body", body, height=200, key=f"b{d_id}")
            st.caption("Evidence used: " + ", ".join(f"#{e}" for e in (brief or {}).get("evidence_ids", [])))
            b1, b2, b3 = st.columns(3)
            with session_scope(URL) as s:
                if b1.button("Approve", key=f"a{d_id}"):
                    try:
                        if new_body != body or (new_subject is not None and new_subject != (subject or "")):
                            d = edit(s, d_id, new_body, CFG, subject=new_subject)
                            st.info(f"Saved edit: {d.status}")
                        else:
                            approve(s, d_id)
                            st.success("Approved")
                    except ValueError as exc:
                        st.error(str(exc))
                if b2.button("Save edit", key=f"e{d_id}"):
                    st.info(f"Status: {edit(s, d_id, new_body, CFG, subject=new_subject).status}")
                if b3.button("Reject", key=f"r{d_id}"):
                    reject(s, d_id)
                    st.warning("Rejected")

# --- Manual queue -------------------------------------------------------------------------------------
with tab_queue:
    st.caption("LinkedIn and Instagram are done by hand. Open the link, paste the approved text, then log it here.")
    day = st.date_input("Due on or before", date.today())
    with session_scope(URL) as s:
        tasks = s.execute(
            select(Task.id, Task.draft_id, Task.channel, Task.due_date, Operator.name, Operator.instagram_handle,
                   Draft.body)
            .join(Draft, Draft.id == Task.draft_id).join(Operator, Operator.id == Draft.operator_id)
            .where(Task.status == "todo", Task.due_date <= day.isoformat()).order_by(Task.due_date)
            .limit(60)).all()
    st.write(f"{len(tasks)} open tasks")
    for t_id, draft_id, channel, due, op_name, ig, body in tasks:
        with st.expander(f"{due} {channel}: {op_name}"):
            st.code(body, language=None)
            if channel == "instagram_dm" and ig:
                st.markdown(f"[Open instagram.com/{ig}](https://www.instagram.com/{ig}/)")
            ev = st.selectbox("Log event", EVENTS, key=f"ev{t_id}")
            if st.button("Log", key=f"lg{t_id}"):
                with session_scope(URL) as s:
                    log_from_draft(s, draft_id, ev)
                st.success(f"Logged {ev}")

# --- Deliverability -----------------------------------------------------------------------------------
with tab_deliv:
    st.caption("Read-only DNS lookups and a warm-up schedule. See docs/DELIVERABILITY_CHECKLIST.md.")
    dom = st.text_input("Sending domain", "")
    if dom and st.button("Check DNS"):
        rep = check_domain(dom.strip())
        (st.success if rep.ok else st.error)("Healthy" if rep.ok else "Issues found")
        for issue in rep.issues:
            st.write("- " + issue)
        st.json(asdict(rep))
    c1, c2, c3 = st.columns(3)
    n_dom = c1.number_input("Domains", 1, 20, 2)
    n_inb = c2.number_input("Inboxes per domain", 1, 3, 2)
    start = c3.date_input("Start", date.today())
    st.markdown(to_markdown(plan(int(n_dom), int(n_inb), start)))

# --- Analytics ----------------------------------------------------------------------------------------
with tab_stats:
    st.caption("Counts from logged events only. Denominators under 30 are flagged SMALL SAMPLE. Nothing is "
               "extrapolated.")
    by = st.radio("Group by", ["channel", "segment", "hook_id", "list_name"], horizontal=True)
    with session_scope(URL) as s:
        fs = funnels(s, by)
        report_md = weekly_report(s, synthetic=DEMO)
    if not fs:
        st.info("No events logged yet. Use `hostop log` or the Manual queue tab.")
    else:
        rows_f = []
        for f in fs:
            r = f.rate("replied", "sent")
            rows_f.append({by: f.group, **{k: f.counts[k] for k in STAGES}, "reply rate": r.fmt(),
                           "small sample": r.small})
        st.dataframe(pd.DataFrame(rows_f), hide_index=True, use_container_width=True)
    st.download_button("Download weekly report (markdown)", report_md,
                       file_name="SYNTHETIC_weekly_report.md" if DEMO else "weekly_report.md")
