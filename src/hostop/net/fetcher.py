"""Polite HTTP fetching for public company websites.

- Hard blocklist (Airbnb, Vrbo, LinkedIn, Instagram, Facebook...): requests are refused in code.
- robots.txt checked per host (unreachable robots.txt => treated as disallow-nothing only on 404,
  as per RFC 9309; other failures => skip the host).
- Per-host minimum delay, on-disk cache with TTL, honest User-Agent, timeouts.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx


class BlockedDomainError(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    from_cache: bool = False
    skipped_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.skipped_reason is None and 200 <= self.status < 300


class Fetcher(Protocol):
    def get(self, url: str) -> FetchResult: ...


def is_blocked(url: str, blocked_domains: list[str]) -> bool:
    host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in blocked_domains)


class PoliteFetcher:
    def __init__(self, user_agent: str, blocked_domains: list[str], min_delay: float = 2.0,
                 cache_dir: Path = Path(".cache/http"), cache_ttl_hours: int = 168, timeout: float = 15,
                 client: httpx.Client | None = None, sleep: object = time.sleep) -> None:
        self.ua, self.blocked, self.min_delay = user_agent, blocked_domains, min_delay
        self.cache_dir, self.ttl = cache_dir, cache_ttl_hours * 3600
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True,
                                             headers={"User-Agent": user_agent})
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # --- helpers -------------------------------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    def _throttle(self, host: str) -> None:
        wait = self.min_delay - (time.monotonic() - self._last.get(host, -1e9))
        if wait > 0:
            self._sleep(wait)  # type: ignore[operator]
        self._last[host] = time.monotonic()

    def _robots_for(self, scheme: str, host: str) -> urllib.robotparser.RobotFileParser | None:
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"{scheme}://{host}/robots.txt"
            try:
                self._throttle(host)
                r = self.client.get(robots_url)
                if r.status_code in (401, 403):
                    rp.parse(["User-agent: *", "Disallow: /"])
                elif r.status_code >= 400:
                    rp.parse([])  # no robots.txt => allowed
                else:
                    rp.parse(r.text.splitlines())
                self._robots[host] = rp
            except httpx.HTTPError:
                self._robots[host] = None  # cannot determine => do not crawl
        return self._robots[host]

    # --- public --------------------------------------------------------------------------------
    def get(self, url: str) -> FetchResult:
        if is_blocked(url, self.blocked):
            raise BlockedDomainError(f"Refusing to fetch blocked domain: {url}")
        cp = self._cache_path(url)
        if cp.exists() and time.time() - cp.stat().st_mtime < self.ttl:
            data = json.loads(cp.read_text(encoding="utf-8"))
            return FetchResult(url=url, status=data["status"], text=data["text"], from_cache=True)
        parsed = urlparse(url)
        host = parsed.hostname or ""
        rp = self._robots_for(parsed.scheme or "https", host)
        if rp is None:
            return FetchResult(url, 0, "", skipped_reason="robots.txt unreachable")
        if not rp.can_fetch(self.ua, url):
            return FetchResult(url, 0, "", skipped_reason="disallowed by robots.txt")
        self._throttle(host)
        try:
            r = self.client.get(url)
        except httpx.HTTPError as exc:
            return FetchResult(url, 0, "", skipped_reason=f"http error: {type(exc).__name__}")
        text = r.text if "html" in r.headers.get("content-type", "html") else ""
        cp.write_text(json.dumps({"status": r.status_code, "text": text}), encoding="utf-8")
        return FetchResult(url=str(r.url), status=r.status_code, text=text)
