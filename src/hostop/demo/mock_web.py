"""Mock fetcher serving SYNTHETIC HTML for *.example domains. Never touches the network."""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from hostop.net.fetcher import BlockedDomainError, FetchResult, is_blocked

_PMS_SNIPPETS = [
    '<script src="https://booking.hostaway.com/widget.js"></script>',
    '<iframe src="https://app.guesty.com/booking"></iframe>',
    '<script src="https://cdn.lodgify.com/booking.js"></script>',
    '<a href="https://secure.ownerrez.com/book">Book</a>',
    '<script src="https://api.streamlinevrs.com/x.js"></script>',
    "",
    "",
]


class MockFetcher:
    def __init__(self, blocked_domains: list[str]) -> None:
        self.blocked = blocked_domains
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResult:
        if is_blocked(url, self.blocked):
            raise BlockedDomainError(url)
        self.calls.append(url)
        host = urlparse(url).hostname or ""
        if not host.endswith(".example"):
            return FetchResult(url, 0, "", skipped_reason="mock fetcher only serves .example")
        h = int(hashlib.md5(host.encode()).hexdigest(), 16)
        path = urlparse(url).path
        name = host.split(".")[-2] if host.count(".") else host
        if path.startswith("/careers"):
            roles = ["Guest Experience Coordinator", "Operations Manager", "Housekeeping Supervisor"]
            body = f"<h1>SYNTHETIC careers</h1><p>We are hiring: {roles[h % 3]}</p>" if h % 4 == 0 else \
                "<h1>SYNTHETIC careers</h1><p>No open roles right now.</p>"
            return FetchResult(url, 200, f"<html><body>{body}</body></html>")
        if path.startswith("/about"):
            return FetchResult(url, 200, f"<html><body><p>SYNTHETIC about page for {name}. "
                                         f"We manage {20 + h % 160} vacation rentals.</p></body></html>")
        pms = _PMS_SNIPPETS[h % len(_PMS_SNIPPETS)]
        booking = '<form><input type="date" name="check-in"><button>Check availability</button></form>' \
            if h % 3 else ""
        ig = f'<a href="https://www.instagram.com/{name[:20]}_stays/">IG</a>' if h % 2 else ""
        html = (f"<html><body><h1>SYNTHETIC {name}</h1>{pms}{booking}"
                f'<a href="/about">About us</a><a href="/careers">Careers</a><a href="/contact">Contact</a>'
                f"{ig}</body></html>")
        return FetchResult(url, 200, html)
