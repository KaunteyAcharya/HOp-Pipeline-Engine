"""Website analyzer for an operator's own public site (robots.txt aware via the Fetcher).

Pure functions take HTML and return findings; `analyze_operator` fetches a handful of pages and stores
evidence + signals. It only follows links on the operator's own domain, capped at MAX_PAGES.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy import delete
from sqlalchemy.orm import Session

from hostop.models import Evidence, FieldProvenance, Operator, Signal, utcnow
from hostop.net.fetcher import BlockedDomainError, Fetcher

MAX_PAGES = 5
ANALYZER_KINDS = ["pms", "site_listing_count", "direct_booking", "hiring", "page", "social"]
PAGE_KEYWORDS = {
    "about": ["about", "our-story", "who-we-are"],
    "contact": ["contact"],
    "team": ["team", "our-people", "staff", "leadership"],
    "careers": ["careers", "jobs", "join-us", "join-our-team", "employment", "hiring"],
    "owners": ["owners", "property-management", "list-your-property", "homeowners"],
}
HIRING_ROLES = re.compile(
    r"\b(guest (experience|services|relations|communications?)|reservations? (agent|specialist|manager)|"
    r"operations (manager|coordinator|associate)|housekeeping (manager|supervisor)|"
    r"property (manager|coordinator)|front desk|concierge)\b", re.I)
LISTING_COUNT = re.compile(
    r"\b(\d{2,3})\s*\+?\s*(?:luxury\s+|vacation\s+|short[- ]term\s+|rental\s+|unique\s+|beautiful\s+){0,2}"
    r"(?:rentals|properties|homes|listings|units|cabins|condos|villas|cottages)\b", re.I)
BOOKING_HINTS = re.compile(r"\b(book now|check availability|search (properties|rentals)|select dates|"
                           r"arrival|departure|check[- ]in date)\b", re.I)
SOCIAL = {
    "instagram": re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})/?(?:[?#]|$)", re.I),
    "facebook": re.compile(r"facebook\.com/([A-Za-z0-9_.\-]{2,80})/?(?:[?#]|$)", re.I),
    "linkedin": re.compile(r"linkedin\.com/company/([A-Za-z0-9_\-]{2,80})/?(?:[?#]|$)", re.I),
}
IG_RESERVED = {"p", "explore", "accounts", "reel", "reels", "stories", "about", "developer", "legal"}


@dataclass
class SiteFindings:
    pms: dict[str, str] = field(default_factory=dict)  # name -> url where seen
    listing_counts: list[tuple[int, str, str]] = field(default_factory=list)  # (count, snippet, url)
    pages: dict[str, str] = field(default_factory=dict)
    socials: dict[str, str] = field(default_factory=dict)  # platform -> url
    direct_booking: tuple[str, str] | None = None  # (reason, url)
    hiring: list[tuple[str, str]] = field(default_factory=list)  # (role text, url)
    skipped: list[str] = field(default_factory=list)


def detect_pms(html: str, fingerprints: dict[str, list[str]]) -> list[str]:
    low = html.lower()
    return [name for name, fps in fingerprints.items() if any(fp in low for fp in fps)]


def find_listing_counts(text: str) -> list[tuple[int, str]]:
    out = []
    for m in LISTING_COUNT.finditer(text):
        n = int(m.group(1))
        if 2 <= n <= 2000:
            s = max(0, m.start() - 40)
            out.append((n, " ".join(text[s:m.end() + 20].split())))
    return out


def find_pages(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    host = urlparse(base_url).hostname
    pages: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, str(a["href"]))
        if urlparse(href).hostname != host:
            continue
        hay = (urlparse(href).path + " " + a.get_text(" ")).lower()
        for kind, kws in PAGE_KEYWORDS.items():
            if kind not in pages and any(k in hay for k in kws):
                pages[kind] = href.split("#")[0]
    return pages


def find_socials(soup: BeautifulSoup) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        for platform, rx in SOCIAL.items():
            m = rx.search(href)
            if m and platform not in out:
                if platform == "instagram" and m.group(1).lower() in IG_RESERVED:
                    continue
                out[platform] = href
    return out


def instagram_handle(url: str) -> str | None:
    m = SOCIAL["instagram"].search(url)
    return m.group(1) if m else None


def detect_direct_booking(html: str, text: str, pms_found: list[str]) -> str | None:
    low = html.lower()
    has_form = "type=\"date\"" in low or "datepicker" in low or "check-in" in low or "checkin" in low
    if pms_found and BOOKING_HINTS.search(text):
        return f"booking UI + {', '.join(pms_found)} booking engine"
    if has_form and BOOKING_HINTS.search(text):
        return "booking search / date picker on site"
    return None


def analyze_html(html: str, url: str, fingerprints: dict[str, list[str]], f: SiteFindings) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    for name in detect_pms(html, fingerprints):
        f.pms.setdefault(name, url)
    for n, snip in find_listing_counts(text):
        f.listing_counts.append((n, snip, url))
    for k, v in find_socials(soup).items():
        f.socials.setdefault(k, v)
    if f.direct_booking is None:
        reason = detect_direct_booking(html, text, list(f.pms))
        if reason:
            f.direct_booking = (reason, url)
    return soup


def crawl_site(domain: str, fetcher: Fetcher, fingerprints: dict[str, list[str]]) -> SiteFindings:
    f = SiteFindings()
    home = f"https://{domain}/"
    try:
        r = fetcher.get(home)
    except BlockedDomainError as e:
        f.skipped.append(str(e))
        return f
    if not r.ok:
        f.skipped.append(f"{home}: {r.skipped_reason or r.status}")
        return f
    soup = analyze_html(r.text, r.url, fingerprints, f)
    f.pages = find_pages(soup, r.url)
    for kind, url in list(f.pages.items())[: MAX_PAGES - 1]:
        pr = fetcher.get(url)
        if not pr.ok:
            f.skipped.append(f"{url}: {pr.skipped_reason or pr.status}")
            continue
        psoup = analyze_html(pr.text, pr.url, fingerprints, f)
        if kind == "careers":
            seen: set[str] = set()
            for m in HIRING_ROLES.finditer(psoup.get_text(" ")):
                role = m.group(0).lower()
                if role not in seen:
                    seen.add(role)
                    f.hiring.append((m.group(0), pr.url))
    return f


def store_findings(s: Session, op: Operator, f: SiteFindings, synthetic: bool) -> None:
    tag = "SYNTHETIC " if synthetic else ""
    s.execute(delete(Signal).where(Signal.operator_id == op.id, Signal.kind.in_(["hiring", "direct_booking"])))
    s.execute(delete(Evidence).where(Evidence.operator_id == op.id, Evidence.kind.in_(ANALYZER_KINDS)))

    def ev(kind: str, claim: str, url: str | None, snippet: str | None = None) -> Evidence:
        e = Evidence(operator_id=op.id, kind=kind, claim=tag + claim, url=url, snippet=snippet)
        s.add(e)
        s.flush()
        return e

    for name, url in f.pms.items():
        ev("pms", f"Website references {name}", url)
    op.pms = sorted(f.pms)
    if f.listing_counts:
        n, snip, url = max(f.listing_counts, key=lambda x: x[0])
        ev("site_listing_count", f"Website states about {n} properties", url, snip)
        if op.listing_count is None:
            op.listing_count = n
            s.add(FieldProvenance(operator_id=op.id, field="listing_count", value=str(n), source="website",
                                  source_url=url))
    for kind, url in f.pages.items():
        ev("page", f"{kind} page", url)
    for platform, url in f.socials.items():
        ev("social", f"{platform} link in site", url)
        if platform == "instagram":
            op.instagram_handle = instagram_handle(url)
        if platform == "linkedin":
            op.linkedin_company_url = url
    op.direct_booking = f.direct_booking is not None
    if f.direct_booking:
        e = ev("direct_booking", f"Direct booking site: {f.direct_booking[0]}", f.direct_booking[1])
        s.add(Signal(operator_id=op.id, kind="direct_booking", detail=f.direct_booking[0], evidence_id=e.id))
    if f.hiring:
        roles = ", ".join(r for r, _ in f.hiring[:5])
        e = ev("hiring", f"Careers page lists: {roles}", f.hiring[0][1])
        s.add(Signal(operator_id=op.id, kind="hiring", value=float(len(f.hiring)), detail=roles, evidence_id=e.id))
    op.analyzed_at = utcnow()
