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
def enrich(demo: bool = DemoOpt) -> None:
    """Find verified contacts within a credit budget."""
    _todo("enrich", demo)


@app.command()
def draft(demo: bool = DemoOpt) -> None:
    """Draft messages for human review."""
    _todo("draft", demo)


@app.command()
def export(demo: bool = DemoOpt) -> None:
    """Export approved sequences and task queues."""
    _todo("export", demo)


@app.command()
def report(demo: bool = DemoOpt) -> None:
    """Write reports/weekly_report.md."""
    _todo("report", demo)


@app.command()
def dashboard(demo: bool = DemoOpt) -> None:
    """Launch the Streamlit dashboard."""
    _todo("dashboard", demo)


@app.command("run-all")
def run_all(demo: bool = DemoOpt) -> None:
    """discover -> analyze -> score -> enrich -> draft -> export -> report."""
    _todo("run-all", demo)


if __name__ == "__main__":
    app()
