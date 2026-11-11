"""hostop CLI. Nothing in this CLI sends outreach; it drafts, exports and reports."""

from __future__ import annotations

import typer
from rich.console import Console

from hostop.config import load_config
from hostop.db import init_db, session_scope
from hostop.settings import get_settings

app = typer.Typer(help="HostOp Pipeline Engine (drafts for human review; never sends).", no_args_is_help=True)
console = Console()

DEMO_BANNER = "[bold yellow]DEMO MODE: all operators, contacts and results are SYNTHETIC.[/]"
DemoOpt = typer.Option(False, "--demo", help="Use mock adapters and SYNTHETIC data.")


DEMO_DB_URL = "sqlite:///hostop_demo.db"


def db_url(demo: bool) -> str:
    """Demo data lives in its own database so SYNTHETIC rows never mix with real ones."""
    return DEMO_DB_URL if demo else get_settings().hostop_db_url


def _banner(demo: bool) -> None:
    if demo:
        console.print(DEMO_BANNER)


@app.command("init-db")
def init_db_cmd() -> None:
    """Create database tables and validate config."""
    cfg = load_config()
    init_db()
    console.print(f"DB ready. ICP {cfg.icp.min_listings}-{cfg.icp.max_listings} listings "
                  f"(ideal {cfg.icp.ideal_min}-{cfg.icp.ideal_max}).")


def _todo(name: str, demo: bool) -> None:
    _banner(demo)
    console.print(f"[dim]`{name}` is implemented in a later phase.[/]")


@app.command()
def discover(
    demo: bool = DemoOpt,
    web: bool = typer.Option(False, "--web", help="Also run paid web search (Firecrawl credits)."),
) -> None:
    """Collect operators from open datasets, permits, web search and lists."""
    from rich.table import Table

    from hostop.discovery.inside_airbnb import ATTRIBUTION
    from hostop.discovery.pipeline import run_discovery

    _banner(demo)
    cfg = load_config()
    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        stats = run_discovery(s, cfg, demo, web=web)
    table = Table(title="Discovery by source" + (" (SYNTHETIC)" if demo else ""))
    for col in ("source", "records in ICP band", "new operators", "merged into existing", "already loaded"):
        table.add_column(col)
    for src, d in stats["by_source"].items():
        table.add_row(src, str(d["seen"]), str(d["created"]), str(d["merged"]), str(d["skipped_existing"]))
    console.print(table)
    total = stats["operators_total"]
    console.print(f"Resolved operators: [bold]{total}[/] / 1,000 target ({min(100, total / 10):.0f}%). "
                  f"Dedupe rate this run: {stats['dedupe_rate']:.1%}. Growth signals: {stats['growth_signals']}.")
    console.print(f"[dim]{ATTRIBUTION}[/]")


@app.command()
def analyze(
    demo: bool = DemoOpt,
    limit: int = typer.Option(200, help="Max sites per run."),
    refresh: bool = typer.Option(False, help="Re-analyze sites already analyzed."),
) -> None:
    """Analyze operator websites (robots.txt aware, rate-limited, cached)."""
    from sqlalchemy import select

    from hostop.analyze.site_analyzer import crawl_site, store_findings
    from hostop.models import Operator
    from hostop.net.fetcher import Fetcher, PoliteFetcher

    _banner(demo)
    cfg = load_config()
    url = db_url(demo)
    init_db(url)
    fetcher: Fetcher
    if demo:
        from hostop.demo.mock_web import MockFetcher

        fetcher = MockFetcher(cfg.fetch.blocked_domains)
    else:
        fetcher = PoliteFetcher(get_settings().hostop_user_agent, cfg.fetch.blocked_domains,
                                cfg.fetch.min_delay_seconds, cache_ttl_hours=cfg.fetch.cache_ttl_hours,
                                timeout=cfg.fetch.timeout_seconds)
    done = skipped = 0
    with session_scope(url) as s:
        q = select(Operator).where(Operator.domain.is_not(None))
        if not refresh:
            q = q.where(Operator.analyzed_at.is_(None))
        for op in s.scalars(q.limit(limit)).all():
            f = crawl_site(op.domain or "", fetcher, cfg.pms_tech)
            if f.skipped and not f.pages and not f.pms:
                skipped += 1
                console.print(f"[dim]skip {op.domain}: {f.skipped[0]}[/]")
                continue
            store_findings(s, op, f, synthetic=op.is_synthetic)
            done += 1
    console.print(f"Analyzed {done} operator sites, skipped {skipped}.")


@app.command()
def score(
    demo: bool = DemoOpt,
    explain_id: int = typer.Option(None, "--explain", help="Show the score breakdown for one operator id."),
) -> None:
    """Score operators into tiers A/B/C (or explain one score)."""
    from rich.table import Table

    from hostop.scoring.icp import explain, score_all

    _banner(demo)
    cfg = load_config()
    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        if explain_id is None:
            counts = score_all(s, cfg)
            console.print(f"Tier A: {counts['A']}  Tier B: {counts['B']}  Tier C: {counts['C']}")
            return
        info = explain(s, explain_id)
    if info is None:
        console.print(f"No operator {explain_id}")
        raise typer.Exit(1)
    tag = " (SYNTHETIC)" if info["synthetic"] else ""
    console.print(f"[bold]{info['operator']}[/]{tag} {info['domain'] or ''}: "
                  f"{info['total']} pts, Tier {info['tier']}")
    table = Table("factor", "points", "reason", "evidence")
    for f in info["factors"]:
        evs = "\n".join(f"#{e['id']} {e['claim']} {e['url'] or ''}" for e in f["evidence"])
        table.add_row(f["factor"], str(f["points"]), f["reason"], evs)
    console.print(table)


@app.command()
def enrich(
    demo: bool = DemoOpt,
    limit: int = typer.Option(50, help="Max operators (Tier A/B, highest score first)."),
) -> None:
    """Find verified contacts within a credit budget (never guesses emails)."""
    from hostop.enrich.base import EnrichmentProvider
    from hostop.enrich.waterfall import enrich_operators

    _banner(demo)
    cfg = load_config()
    st = get_settings()
    providers: list[EnrichmentProvider] = []
    if demo:
        from hostop.enrich.mock import MockProvider

        providers.append(MockProvider())
    else:
        if st.apollo_api_key:
            from hostop.enrich.apollo import ApolloProvider

            providers.append(ApolloProvider(st.apollo_api_key))
        if st.hunter_api_key:
            from hostop.enrich.hunter import HunterProvider

            providers.append(HunterProvider(st.hunter_api_key))
        if not providers:
            console.print("[yellow]No APOLLO_API_KEY or HUNTER_API_KEY set: only LinkedIn search URLs will be "
                          "generated.[/]")
    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        res = enrich_operators(s, cfg, providers, limit=limit)
    console.print(f"Operators processed: {res.operators}; with verified email: {res.with_verified_email}; "
                  f"unverified emails dropped: {res.dropped_unverified}; suppressed: {res.suppressed}.")
    console.print(f"Credits used: {res.credits or 0} (budget {cfg.enrichment.credit_budget_per_run})"
                  + ("; stopped at budget." if res.budget_stopped else ""))


@app.command()
def suppress(
    value: str = typer.Argument(..., help="Email, domain or @handle to add to do-not-contact."),
    reason: str = typer.Option("do_not_contact", help="opt_out | do_not_contact | bounced | customer"),
    demo: bool = DemoOpt,
) -> None:
    """Add an email, domain or handle to the suppression list."""
    from hostop.compliance.optout import suppress as add

    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        added = add(s, value, reason)
    console.print("Added." if added else "Already suppressed.")


@app.command()
def draft(
    demo: bool = DemoOpt,
    limit: int = typer.Option(20, help="Max operators to draft for (Tier A/B with contacts)."),
) -> None:
    """Draft messages for human review (validated; never sent)."""
    from hostop.drafting.generator import draft_operators
    from hostop.drafting.llm import LLM, AnthropicLLM

    _banner(demo)
    cfg = load_config()
    llm: LLM
    if demo:
        from hostop.drafting.mock_llm import MockLLM

        llm = MockLLM()
    else:
        st = get_settings()
        llm = AnthropicLLM(st.anthropic_model, st.anthropic_api_key or None)
    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        res = draft_operators(s, cfg, llm, limit=limit)
    console.print(f"Operators: {res.operators}; drafts: {res.drafts} (valid {res.valid}, needs fix {res.invalid}); "
                  f"refused: {res.refused}; suppressed: {res.skipped_suppressed}.")
    for hid, n in sorted(res.by_hook.items()):
        console.print(f"  hook {hid}: {n} drafts")


@app.command()
def export(
    demo: bool = DemoOpt,
    platform: str = typer.Option("instantly", help="instantly | smartlead"),
    list_name: str = typer.Option("tier_ab", help="List name written to each row (for analytics)."),
    include_review: bool = typer.Option(False, help="Include CASL/GDPR/unknown-country contacts."),
    verify: bool = typer.Option(False, help="Re-verify each email before export (Hunter credits)."),
    out: str = typer.Option("exports", help="Output folder."),
) -> None:
    """Export APPROVED email sequences + build/export LinkedIn and Instagram task queues. Never sends."""
    from pathlib import Path

    from hostop.deliverability.verify import HunterVerifier, MockVerifier, Verifier
    from hostop.outreach.export import export_email_sequences
    from hostop.outreach.queues import build_queue, export_queue

    _banner(demo)
    cfg = load_config()
    verifier: Verifier | None = None
    if verify:
        verifier = MockVerifier() if demo else HunterVerifier(get_settings().hunter_api_key)
    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        res = export_email_sequences(s, cfg, platform, Path(out), list_name, include_review, verifier)
        queued = build_queue(s, cfg)
        tasks = export_queue(s, Path(out))
    console.print(f"Email CSV: {res.path} ({res.rows} contacts; skipped: {res.skipped_suppressed} suppressed, "
                  f"{res.skipped_review} need compliance review, {res.skipped_incomplete} incomplete, "
                  f"{res.skipped_failed_verification} failed verification)")
    console.print(f"Task queue: {queued} new tasks scheduled within daily caps -> {tasks}")


@app.command()
def review(
    demo: bool = DemoOpt,
    approve_ids: list[int] = typer.Option([], "--approve", help="Draft id(s) to approve."),
    reject_ids: list[int] = typer.Option([], "--reject", help="Draft id(s) to reject."),
    approve_all_valid: bool = typer.Option(False, help="Approve every pending draft with no validation errors."),
) -> None:
    """Approve or reject drafts (the dashboard does the same with editing)."""
    from sqlalchemy import select

    from hostop.models import Draft
    from hostop.outreach.review import approve, reject

    _banner(demo)
    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        ids = list(approve_ids)
        if approve_all_valid:
            ids += [d.id for d in s.scalars(select(Draft).where(Draft.status == "pending")) if not d.validation_errors]
        for i in ids:
            approve(s, i)
        for i in reject_ids:
            reject(s, i)
    console.print(f"Approved {len(ids)}, rejected {len(reject_ids)}.")


@app.command("log")
def log_cmd(
    draft_id: int = typer.Argument(..., help="Draft id the event relates to."),
    event: str = typer.Argument(..., help="sent | replied | positive | demo_booked | demo_held | opt_out | bounced"),
    list_name: str = typer.Option(None, help="List name for analytics."),
    note: str = typer.Option(None),
    demo: bool = DemoOpt,
) -> None:
    """Log what happened after a human sent a message."""
    from hostop.outreach.status import log_from_draft

    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        ev = log_from_draft(s, draft_id, event, list_name, note)
    console.print(f"Logged {ev.event} on {ev.channel} for operator {ev.operator_id}.")


@app.command("dns-check")
def dns_check_cmd(
    domains: list[str] = typer.Argument(..., help="Sending domains to check."),
    selector: list[str] = typer.Option([], help="DKIM selector(s) from your email provider."),
) -> None:
    """Check SPF, DKIM, DMARC and MX for sending domains."""
    from hostop.deliverability.dns_check import check_domain

    for d in domains:
        r = check_domain(d, selectors=selector or None)
        status = "[green]OK[/]" if r.ok else "[red]ISSUES[/]"
        console.print(f"{status} {r.domain}  SPF={'yes' if r.spf else 'no'}  DMARC={r.dmarc_policy or 'none'}  "
                      f"DKIM={','.join(r.dkim_selectors) or 'none'}  MX={len(r.mx)}")
        for issue in r.issues:
            console.print(f"   - {issue}")


@app.command()
def warmup(
    domains: int = typer.Option(3, help="Number of sending domains."),
    inboxes: int = typer.Option(2, help="Inboxes per domain (max 3)."),
    weeks: int = typer.Option(6),
) -> None:
    """Print a conservative warm-up and ramp schedule."""
    from datetime import date

    from hostop.deliverability.warmup import plan, to_markdown

    console.print(to_markdown(plan(domains, inboxes, date.today(), weeks=weeks)))


@app.command()
def crm(
    demo: bool = DemoOpt,
    attio: bool = typer.Option(False, "--attio", help="Push to Attio (real data only). Default writes CSV."),
    list_slug: str = typer.Option("hostop_pipeline", help="Attio list slug holding pipeline stage."),
    stage_attribute: str = typer.Option("stage", help="Attio status attribute slug on that list."),
    out: str = typer.Option("exports/crm_companies.csv"),
) -> None:
    """Sync Tier A/B companies, contacts, stage and score notes to a CRM CSV or Attio."""
    from pathlib import Path

    from hostop.crm.attio import AttioClient, AttioConfig
    from hostop.crm.sync import build_rows, push_to_attio, write_csv

    _banner(demo)
    url = db_url(demo)
    init_db(url)
    with session_scope(url) as s:
        rows = build_rows(s)
    if attio:
        if demo:
            console.print("[red]Refusing to push SYNTHETIC demo data to Attio.[/]")
            raise typer.Exit(1)
        client = AttioClient(AttioConfig(get_settings().attio_api_key, list_slug, stage_attribute))
        console.print(f"Pushed {push_to_attio(rows, client)} companies to Attio.")
    else:
        console.print(f"Wrote {len(rows)} rows to {write_csv(rows, Path(out))}")


@app.command()
def serve(demo: bool = DemoOpt, port: int = typer.Option(8000)) -> None:
    """Run the FastAPI hooks for n8n."""
    import os

    import uvicorn

    if demo:
        os.environ["HOSTOP_DEMO"] = "1"
    uvicorn.run("hostop.api.app:app", host="127.0.0.1", port=port)


@app.command()
def report(demo: bool = DemoOpt) -> None:
    """Write reports/weekly_report.md."""
    _todo("report", demo)


@app.command()
def dashboard(demo: bool = DemoOpt) -> None:
    """Launch the Streamlit dashboard."""
    import subprocess
    import sys

    _banner(demo)
    cmd = [sys.executable, "-m", "streamlit", "run", "dashboard/app.py"]
    subprocess.run([*cmd, "--", "--demo"] if demo else cmd, check=False)


@app.command("run-all")
def run_all(demo: bool = DemoOpt) -> None:
    """discover -> analyze -> score -> enrich -> draft -> export -> report."""
    _todo("run-all", demo)


if __name__ == "__main__":
    app()
