"""Per-contact compliance flags. These are operational guardrails, not legal advice."""

from __future__ import annotations

from dataclasses import dataclass

from hostop.config import HostOpConfig

NOTES = {
    "CAN-SPAM": ("US CAN-SPAM: B2B cold email allowed. Must include accurate sender/subject, a physical postal "
                 "address, and a working opt-out honored within 10 business days."),
    "CASL": ("Canada CASL: commercial email needs consent. Implied consent may apply if the address is "
             "conspicuously published, not marked 'no unsolicited email', and the message relates to the "
             "recipient's role. Record where it was published. Include sender ID, address, unsubscribe."),
    "UK-GDPR/PECR": ("UK: corporate subscribers may be emailed under PECR; personal data processing needs a "
                     "lawful basis (usually legitimate interests, with an LIA on file). Identify yourself, "
                     "offer opt-out, honor objections, respond to data-subject requests."),
    "GDPR": ("EU GDPR: B2B outreach usually relies on legitimate interests (Art. 6(1)(f)) with a documented "
             "LIA; some member states' ePrivacy rules require prior consent even for business emails "
             "(e.g. Germany). Provide Art. 14 notice (source of data) on first contact, opt-out, and DSAR handling."),
    "UNKNOWN": "Country unknown: treat as the strictest applicable regime until confirmed.",
}
REVIEW_REGIMES = {"CASL", "GDPR", "UNKNOWN"}


@dataclass
class ComplianceFlag:
    regime: str
    note: str
    needs_review: bool


def classify(country: str | None, cfg: HostOpConfig) -> ComplianceFlag:
    c = (country or "").upper()
    if c in cfg.compliance.eu_countries:
        regime = cfg.compliance.regions.get("EU", "GDPR")
    elif c:
        regime = cfg.compliance.regions.get(c, "UNKNOWN")
    else:
        regime = "UNKNOWN"
    return ComplianceFlag(regime, NOTES.get(regime, NOTES["UNKNOWN"]), regime in REVIEW_REGIMES)
