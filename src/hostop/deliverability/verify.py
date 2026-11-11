"""List-verification hook: re-verify emails right before export (addresses decay).

Hunter Email Verifier: GET https://api.hunter.io/v2/email-verifier?email=.. (X-API-KEY), data.status in
valid | invalid | accept_all | webmail | disposable | unknown (checked against docs 2026-11-10).
Only `valid` passes. Each call costs a verification credit on Hunter.
"""

from __future__ import annotations

from typing import Protocol

import httpx


class Verifier(Protocol):
    def status(self, email: str) -> str: ...


class HunterVerifier:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.key, self.client = api_key, client or httpx.Client(timeout=30)

    def status(self, email: str) -> str:
        r = self.client.get("https://api.hunter.io/v2/email-verifier", params={"email": email},
                            headers={"X-API-KEY": self.key})
        r.raise_for_status()
        return str((r.json().get("data") or {}).get("status") or "unknown")


class MockVerifier:
    """SYNTHETIC: .example addresses are 'valid', anything else 'unknown'."""

    def status(self, email: str) -> str:
        return "valid" if email.endswith(".example") else "unknown"


def passes(v: Verifier, email: str) -> bool:
    return v.status(email) == "valid"
