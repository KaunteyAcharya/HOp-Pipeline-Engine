"""SPF / DKIM / DMARC / MX checker for sending domains (dnspython). Read-only DNS lookups."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import dns.exception
import dns.resolver

COMMON_DKIM_SELECTORS = ["google", "selector1", "selector2", "default", "k1", "k2", "s1", "s2", "dkim", "mail",
                         "smtp", "mxvault", "instantly", "smartlead"]
Resolver = Callable[[str, str], list[str]]


def default_resolver(name: str, rtype: str) -> list[str]:
    try:
        answers = dns.resolver.resolve(name, rtype, lifetime=5)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return []
    out = []
    for r in answers:
        if rtype == "TXT":
            out.append(b"".join(r.strings).decode(errors="replace"))  # type: ignore[attr-defined]
        else:
            out.append(r.to_text())
    return out


@dataclass
class DomainReport:
    domain: str
    mx: list[str] = field(default_factory=list)
    spf: str | None = None
    dmarc: str | None = None
    dmarc_policy: str | None = None
    dkim_selectors: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


def check_domain(domain: str, resolver: Resolver = default_resolver,
                 selectors: list[str] | None = None) -> DomainReport:
    r = DomainReport(domain=domain.lower().strip())
    r.mx = resolver(r.domain, "MX")
    if not r.mx:
        r.issues.append("no MX record (replies and bounces will fail)")
    spf = [t for t in resolver(r.domain, "TXT") if t.lower().startswith("v=spf1")]
    if not spf:
        r.issues.append("no SPF record")
    elif len(spf) > 1:
        r.issues.append("multiple SPF records (invalid; merge into one)")
    else:
        r.spf = spf[0]
        if "+all" in spf[0]:
            r.issues.append("SPF uses +all (allows anyone to send)")
        if spf[0].count("include:") > 8:
            r.issues.append("SPF has many includes; check the 10 DNS-lookup limit")
    dmarc = [t for t in resolver(f"_dmarc.{r.domain}", "TXT") if t.lower().startswith("v=dmarc1")]
    if not dmarc:
        r.issues.append("no DMARC record")
    else:
        r.dmarc = dmarc[0]
        tags = dict(p.strip().split("=", 1) for p in dmarc[0].split(";") if "=" in p)
        r.dmarc_policy = tags.get("p", "").strip().lower() or None
        if not r.dmarc_policy:
            r.issues.append("DMARC record has no p= policy")
        if "rua" not in tags:
            r.issues.append("DMARC has no rua= reporting address (you will not see failures)")
    for sel in selectors or COMMON_DKIM_SELECTORS:
        if any("p=" in t for t in resolver(f"{sel}._domainkey.{r.domain}", "TXT")):
            r.dkim_selectors.append(sel)
    if not r.dkim_selectors:
        r.issues.append("no DKIM key found on common selectors (pass your provider's selector to confirm)")
    return r
