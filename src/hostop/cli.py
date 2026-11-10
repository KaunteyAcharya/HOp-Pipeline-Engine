"""hostop CLI. Nothing in this CLI sends outreach; it drafts, exports and reports."""

from __future__ import annotations

import typer
from rich.console import Console

from hostop.config import load_config
from hostop.db import init_db

app = typer.Typer(help="HostOp Pipeline Engine (drafts for human review; never sends).", no_args_is_help=True)
console = Console()

DEMO_BANNER = "[bold yellow]DEMO MODE: all operators, contacts and results are SYNTHETIC.[/]"
DemoOpt = typer.Option(False, "--demo", help="Use mock adapters and SYNTHETIC data.")


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
def discover(demo: bool = DemoOpt) -> None:
    """Collect operators from open datasets, permits, web search and lists."""
    _todo("discover", demo)


@app.command()
def analyze(demo: bool = DemoOpt) -> None:
    """Analyze operator websites (robots.txt aware)."""
    _todo("analyze", demo)


@app.command()
def score(demo: bool = DemoOpt) -> None:
    """Score operators into tiers A/B/C."""
    _todo("score", demo)


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
