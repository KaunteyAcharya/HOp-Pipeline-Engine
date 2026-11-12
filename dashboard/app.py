"""HostOp Pipeline dashboard: pipeline, draft review, manual task queue, deliverability and analytics.

Run: streamlit run dashboard/app.py -- --demo   (or set HOSTOP_DEMO=1)
"""

from __future__ import annotations

import html
import os
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from hostop.analytics.funnel import STAGES, funnels, weekly_report
from hostop.config import load_config
from hostop.db import init_db, session_scope
from hostop.deliverability.dns_check import check_domain
from hostop.deliverability.warmup import plan
from hostop.models import Contact, Draft, Evidence, Operator, OperatorSource, Score, Task
from hostop.outreach.review import approve, edit, reject
from hostop.outreach.status import EVENTS, log_from_draft
from hostop.scoring.icp import explain
from hostop.settings import get_settings

DEMO = "--demo" in sys.argv or os.environ.get("HOSTOP_DEMO") == "1"
URL = "sqlite:///hostop_demo.db" if DEMO else get_settings().hostop_db_url
CFG = load_config(Path("config/hostop.yaml"))
ACCENT = "#2F6F5E"

st.set_page_config(page_title="HostOp Pipeline", layout="wide")
st.markdown(f"<style>{(Path(__file__).parent / 'style.css').read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True)


@st.cache_resource(show_spinner="Building the SYNTHETIC demo dataset (about 20 seconds, first visit only)...")
def _bootstrap() -> bool:
    if not DEMO:
        init_db(URL)
        return False
    from hostop.demo.bootstrap import ensure_demo_data

    return ensure_demo_data()


_bootstrap()


def esc(v: object) -> str:
    return html.escape(str(v))


def heading(text: str, note: str = "") -> None:
    st.markdown(f'<div class="ho-h">{esc(text)}<small>{esc(note)}</small></div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="ho-note">{esc(text)}</div>', unsafe_allow_html=True)


def stats(items: list[tuple[str, str, str]], bar: float | None = None) -> None:
    cards = "".join(
        f'<div class="ho-stat"><div class="l">{esc(label)}</div><div class="v">{esc(value)}</div>'
        f'<div class="n">{esc(sub)}</div>'
        + (f'<div class="ho-bar"><div style="width:{bar * 100:.0f}%"></div></div>' if bar is not None and i == 0
           else "")
        + "</div>"
        for i, (label, value, sub) in enumerate(items))
    st.markdown(f'<div class="ho-stats">{cards}</div>', unsafe_allow_html=True)


pill = ('<span class="ho-pill demo"><span class="ho-dot"></span>Demo · synthetic data</span>' if DEMO
        else '<span class="ho-pill"><span class="ho-dot" style="color:#2F6F5E"></span>Live data</span>')
st.markdown(
    f'<div class="ho-header"><div><div class="ho-brand">HostOp <span>Pipeline</span></div>'
    f'<div class="ho-sub">Find, score and draft outreach to STR operators with 10–500 listings. '
    f'Nothing is sent from here; every message is reviewed and sent by a person.</div></div>{pill}</div>',
    unsafe_allow_html=True)
if DEMO:
    note("Every operator, contact and number in this demo is SYNTHETIC and generated for illustration.")

tab_pipe, tab_review, tab_queue, tab_deliv, tab_stats = st.tabs(
    ["Pipeline", "Draft review", "Manual queue", "Deliverability", "Analytics"])

# --- Pipeline -----------------------------------------------------------------------------------------
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

    heading("Discovery progress")
    stats([("Resolved operators", f"{total:,}", f"{min(100, total / 10):.0f}% of 1,000 goal"),
           ("Tier A", f"{tiers.get('A', 0):,}", "best fit, contact first"),
           ("Tier B", f"{tiers.get('B', 0):,}", "good fit"),
           ("Sites analysed", f"{analyzed:,}", "operators' own websites"),
           ("Verified contacts", f"{verified:,}", "decision-makers with verified email")],
          bar=min(1.0, total / 1000))

    left, right = st.columns([1, 2], gap="large")
    with left:
        heading("Operators by source", "deduplicated")
        src = pd.DataFrame(by_source, columns=["source", "operators"])
        src["source"] = src["source"].map(lambda x: x.replace("_", " ").capitalize()
                                          .replace("airbnb", "Airbnb"))
        if len(src):
            top = float(src["operators"].max()) * 1.2
            chart = (alt.Chart(src).mark_bar(color=ACCENT, cornerRadiusEnd=3, height=18)
                     .encode(x=alt.X("operators:Q", title=None, scale=alt.Scale(domain=[0, top]),
                                     axis=alt.Axis(grid=False, labels=False, ticks=False, domain=False)),
                             y=alt.Y("source:N", sort="-x", title=None,
                                     axis=alt.Axis(domain=False, ticks=False, labelPadding=8, labelLimit=160,
                                                   labelFont="Inter", labelFontSize=12, labelColor="#18181B")),
                             tooltip=["source", "operators"])
                     .properties(height=40 * len(src)))
            text = chart.mark_text(align="left", dx=6, color="#71717A", font="Inter").encode(
                text=alt.Text("operators:Q", format=","))
            st.altair_chart((chart + text).configure_view(strokeWidth=0), use_container_width=True)
        else:
            note("No operators yet. Run `hostop discover`.")
    with right:
        heading("Operators")
        tier_pick = st.segmented_control("Tier", ["A", "B", "C"], default=["A", "B"], selection_mode="multi",
                                         label_visibility="collapsed")
        df = pd.DataFrame(rows, columns=["id", "name", "domain", "listings", "cities", "pms", "direct_booking",
                                         "tier", "score"])
        df["cities"] = df["cities"].apply(lambda c: ", ".join(c) if isinstance(c, list) else (c or ""))
        view = df[df["tier"].isin(tier_pick or [])]
        st.dataframe(view, use_container_width=True, hide_index=True, height=320, column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "name": "Operator", "domain": "Website", "listings": st.column_config.NumberColumn("Listings"),
            "cities": "Markets", "pms": "PMS", "direct_booking": st.column_config.CheckboxColumn("Direct"),
            "tier": st.column_config.TextColumn("Tier", width="small"),
            "score": st.column_config.NumberColumn("Score", format="%d")})

    heading("Operator detail", "why it scored what it did")
    options = {f"{r.name}  ·  Tier {r.tier}  ·  {r.score:.0f}": int(r.id) for r in view.head(300).itertuples()}
    if options:
        op_id = options[st.selectbox("Operator", list(options), label_visibility="collapsed")]
        with session_scope(URL) as s:
            info = explain(s, op_id)
            contacts = [(c.full_name, c.title, c.email, c.email_source, c.compliance_regime)
                        for c in s.scalars(select(Contact).where(Contact.operator_id == op_id))]
            ev_rows = [(e.id, e.kind, e.claim, e.url)
                       for e in s.scalars(select(Evidence).where(Evidence.operator_id == op_id))]
        if info:
            a, b = st.columns([3, 2], gap="large")
            with a:
                st.markdown(
                    f'<div style="font-size:16px;font-weight:600">{esc(info["operator"])} '
                    f'<span class="ho-tier">{esc(info["tier"])}</span></div>'
                    f'<div class="ho-note">{esc(info["domain"] or "no website")} · {info["total"]:.0f} points</div>',
                    unsafe_allow_html=True)
                for f in info["factors"]:
                    name = str(f["factor"]).replace("_", " ").capitalize().replace("Pms", "PMS")
                    st.markdown(f'<div class="ho-factor"><div>{esc(name)}</div>'
                                f'<div class="pts">+{f["points"]:.0f}</div><div class="why">{esc(f["reason"])}</div>'
                                "</div>", unsafe_allow_html=True)
            with b:
                st.markdown('<div class="ho-h" style="margin-top:0">Contacts</div>', unsafe_allow_html=True)
                if contacts:
                    st.dataframe(pd.DataFrame(contacts, columns=["Name", "Title", "Email", "Source", "Regime"]),
                                 hide_index=True, use_container_width=True)
                else:
                    note("No verified contact yet.")
                with st.expander(f"Evidence ({len(ev_rows)})"):
                    st.dataframe(pd.DataFrame(ev_rows, columns=["ID", "Kind", "Claim", "URL"]), hide_index=True,
                                 use_container_width=True, column_config={"URL": st.column_config.LinkColumn()})

# --- Draft review -------------------------------------------------------------------------------------
with tab_review:
    with session_scope(URL) as s:
        counts = dict(s.execute(select(Draft.status, func.count()).group_by(Draft.status)).tuples().all())
    heading("Draft review")
    note("Edits are re-validated. A draft with validation errors cannot be approved.")
    labels = {k: f"{k.replace('_', ' ').capitalize()} ({counts.get(k, 0)})"
              for k in ("pending", "needs_fix", "approved", "edited", "rejected")}
    status_pick = st.segmented_control("Status", list(labels), default="pending", format_func=labels.get,
                                       label_visibility="collapsed") or "pending"
    with session_scope(URL) as s:
        drafts = s.execute(
            select(Draft.id, Operator.name, Draft.channel, Draft.hook_id, Draft.subject, Draft.body,
                   Draft.validation_errors, Draft.brief)
            .join(Operator, Operator.id == Draft.operator_id).where(Draft.status == status_pick)
            .order_by(Draft.operator_id, Draft.channel).limit(100)).all()
    if not drafts:
        note("Nothing here.")
    for d_id, op_name, channel, hook, subject, body, errors, brief in drafts:
        with st.expander(f"{op_name}  ·  {channel.replace('_', ' ')}  ·  #{d_id}"):
            if errors:
                st.error("  \n".join(map(str, errors)))
            new_subject = (st.text_input("Subject", subject or "", key=f"s{d_id}")
                           if channel.startswith("email") else None)
            new_body = st.text_area("Message", body, height=220, key=f"b{d_id}")
            ev_ids = ", ".join(f"#{e}" for e in (brief or {}).get("evidence_ids", [])) or "none"
            note(f"Hook {hook} · evidence used: {ev_ids}")
            b1, b2, b3, _ = st.columns([1, 1, 1, 4])
            changed = new_body != body or (new_subject is not None and new_subject != (subject or ""))
            with session_scope(URL) as s:
                if b1.button("Approve", key=f"a{d_id}", type="primary"):
                    try:
                        if changed:
                            st.info(f"Saved edit: {edit(s, d_id, new_body, CFG, subject=new_subject).status}")
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
    heading("Manual queue")
    note("LinkedIn and Instagram are sent by hand. Open the profile, paste the approved text, then log the result.")
    day = st.date_input("Due on or before", date.today())
    with session_scope(URL) as s:
        tasks = s.execute(
            select(Task.id, Task.draft_id, Task.channel, Task.due_date, Operator.name, Operator.instagram_handle,
                   Draft.body)
            .join(Draft, Draft.id == Task.draft_id).join(Operator, Operator.id == Draft.operator_id)
            .where(Task.status == "todo", Task.due_date <= day.isoformat()).order_by(Task.due_date)
            .limit(60)).all()
    note(f"{len(tasks)} open tasks")
    for t_id, draft_id, channel, due, op_name, ig, body in tasks:
        with st.expander(f"{due}  ·  {channel.replace('_', ' ')}  ·  {op_name}"):
            st.code(body, language=None, wrap_lines=True)
            if channel == "instagram_dm" and ig:
                st.markdown(f"[Open instagram.com/{ig}](https://www.instagram.com/{ig}/)")
            c1, c2, _ = st.columns([2, 1, 4])
            ev = c1.selectbox("Result", EVENTS, key=f"ev{t_id}", label_visibility="collapsed")
            if c2.button("Log", key=f"lg{t_id}", type="primary"):
                with session_scope(URL) as s:
                    log_from_draft(s, draft_id, ev)
                st.success(f"Logged {ev}")

# --- Deliverability -----------------------------------------------------------------------------------
with tab_deliv:
    left, right = st.columns(2, gap="large")
    with left:
        heading("DNS check", "read-only lookup")
        note("Checks MX, SPF, DKIM and DMARC for a sending domain.")
        dom = st.text_input("Sending domain", placeholder="send.yourdomain.com", label_visibility="collapsed")
        if st.button("Check domain", type="primary") and dom:
            rep = check_domain(dom.strip())
            (st.success if rep.ok else st.error)("All checks passed" if rep.ok else "Issues found")
            for issue in rep.issues:
                st.markdown(f"- {issue}")
            with st.expander("Raw records"):
                st.json(asdict(rep))
    with right:
        heading("Warm-up plan")
        c1, c2, c3 = st.columns(3)
        n_dom = c1.number_input("Domains", 1, 20, 2)
        n_inb = c2.number_input("Inboxes each", 1, 3, 2)
        start = c3.date_input("Start", date.today())
        seen: set[tuple[int, str, int]] = set()
        weeks = []
        for r in plan(int(n_dom), int(n_inb), start):
            if (r.week, r.phase, r.cold_per_inbox) not in seen:
                seen.add((r.week, r.phase, r.cold_per_inbox))
                weeks.append({"Week": r.week, "From": r.day.isoformat(), "Phase": r.phase,
                              "Cold / inbox / day": r.cold_per_inbox, "Cold / day total": r.total_cold})
        st.dataframe(pd.DataFrame(weeks), hide_index=True, use_container_width=True)

# --- Analytics ----------------------------------------------------------------------------------------
with tab_stats:
    heading("Funnel", "from logged events only")
    note("Every rate shows its sample size. Denominators under 30 are flagged as small samples. Nothing is "
         "projected forward.")
    by = st.segmented_control("Group by", ["channel", "segment", "hook_id", "list_name"], default="channel",
                              format_func=lambda x: {"hook_id": "hook", "list_name": "list"}.get(x, x),
                              label_visibility="collapsed") or "channel"
    with session_scope(URL) as s:
        fs = funnels(s, by)
        report_md = weekly_report(s, synthetic=DEMO)
    if not fs:
        note("No events logged yet. Use the Manual queue tab or `hostop log`.")
    else:
        rows_f = []
        for f in fs:
            r = f.rate("replied", "sent")
            rows_f.append({"group": f.group, **{k.replace("_", " "): f.counts[k] for k in STAGES},
                           "reply rate": r.fmt().replace(" SMALL SAMPLE", ""), "small sample": r.small})
        st.dataframe(pd.DataFrame(rows_f), hide_index=True, use_container_width=True,
                     column_config={"small sample": st.column_config.CheckboxColumn()})
    st.download_button("Download weekly report", report_md,
                       file_name="SYNTHETIC_weekly_report.md" if DEMO else "weekly_report.md")
