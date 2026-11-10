from pathlib import Path

import httpx
import pytest

from hostop.analyze.site_analyzer import (
    crawl_site,
    detect_direct_booking,
    detect_pms,
    find_listing_counts,
    instagram_handle,
)
from hostop.config import Geography
from hostop.demo.mock_web import MockFetcher
from hostop.discovery.providers.firecrawl import FirecrawlSearch
from hostop.discovery.providers.mock import MockSearch
from hostop.discovery.web_search import ListImportCollector, WebSearchCollector, title_to_name
from hostop.net.fetcher import BlockedDomainError, PoliteFetcher, is_blocked

BLOCKED = ["airbnb.com", "vrbo.com", "linkedin.com", "instagram.com", "facebook.com"]
FP = {"Guesty": ["guesty.com"], "Hostaway": ["hostaway"]}


def _fetcher(tmp_path: Path, handler: object) -> PoliteFetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return PoliteFetcher("TestBot/1.0", BLOCKED, min_delay=0, cache_dir=tmp_path / "c", client=client,
                         sleep=lambda _s: None)


# --- fetcher --------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["https://www.airbnb.com/rooms/1", "airbnb.com", "https://de.linkedin.com/in/x",
                                 "https://www.instagram.com/x", "https://vrbo.com"])
def test_blocklist_refuses(tmp_path: Path, url: str) -> None:
    assert is_blocked(url, BLOCKED)
    with pytest.raises(BlockedDomainError):
        _fetcher(tmp_path, lambda r: httpx.Response(200)).get(url)


def test_not_blocked_lookalike() -> None:
    assert not is_blocked("https://notairbnb.com", BLOCKED)


def test_robots_disallow_and_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="<html>hi</html>", headers={"content-type": "text/html"})

    f = _fetcher(tmp_path, handler)
    assert f.get("https://op.com/private/x").skipped_reason == "disallowed by robots.txt"
    first = f.get("https://op.com/")
    second = f.get("https://op.com/")
    assert first.ok and not first.from_cache and second.from_cache
    assert calls.count("/") == 1 and calls.count("/robots.txt") == 1


def test_robots_unreachable_skips(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert _fetcher(tmp_path, handler).get("https://op.com/").skipped_reason == "robots.txt unreachable"


def test_robots_404_allows(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="ok", headers={"content-type": "text/html"})

    assert _fetcher(tmp_path, handler).get("https://op.com/").ok


# --- analyzer -------------------------------------------------------------------------------------

def test_detect_pms_and_listing_counts() -> None:
    assert detect_pms('<script src="https://app.guesty.com/x.js">', FP) == ["Guesty"]
    counts = find_listing_counts("We manage 85+ vacation rentals across Tennessee and 2024 guests")
    assert [c for c, _ in counts] == [85]


def test_direct_booking_needs_ui() -> None:
    assert detect_direct_booking("<p>hi</p>", "Welcome", []) is None
    assert detect_direct_booking('<input type="date">', "Check availability", []) is not None


def test_instagram_handle() -> None:
    assert instagram_handle("https://www.instagram.com/harbor_stays/") == "harbor_stays"


def test_crawl_site_with_mock_fetcher() -> None:
    fetcher = MockFetcher(BLOCKED)
    f = crawl_site("harborstays.example", fetcher, {"Hostaway": ["hostaway"], "Guesty": ["guesty"],
                                                    "Lodgify": ["lodgify"], "OwnerRez": ["ownerrez"],
                                                    "Streamline": ["streamlinevrs"]})
    assert {"about", "careers", "contact"} <= set(f.pages)
    assert f.listing_counts  # about page states a count
    assert all(u.startswith("https://harborstays.example") for u in fetcher.calls)


# --- web search + lists ---------------------------------------------------------------------------

def test_web_search_filters_directories_and_dedupes() -> None:
    geos = [Geography(country="US", city="Austin"), Geography(country="US", city="Austin")]
    out = list(WebSearchCollector(MockSearch(), geos, BLOCKED, synthetic=True).collect())
    assert out and all(r.domain and r.domain.endswith(".example") for r in out)
    assert len({r.domain for r in out}) == len(out)
    assert all(r.is_synthetic for r in out)


def test_title_to_name() -> None:
    assert title_to_name("Harbor Stays | Nashville Vacation Rentals") == "Harbor Stays"


def test_firecrawl_adapter_parses_v2_shape() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v2/search" and req.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, json={"success": True, "creditsUsed": 2,
                                         "data": {"web": [{"url": "https://op.com", "title": "Op"}]}})

    fc = FirecrawlSearch("k", BLOCKED, client=httpx.Client(transport=httpx.MockTransport(handler)))
    hits = fc.search("q")
    assert hits[0].url == "https://op.com" and fc.credits_used == 2


def test_list_import(tmp_path: Path) -> None:
    p = tmp_path / "vrma_sponsors.csv"
    p.write_text("name,domain,city,country,source_url\nHarbor Stays,harborstays.com,Austin,US,https://x\n,,,,\n")
    out = list(ListImportCollector(p).collect())
    assert len(out) == 1 and out[0].domain == "harborstays.com" and out[0].raw["list_name"] == "vrma_sponsors"
