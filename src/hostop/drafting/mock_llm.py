"""Deterministic mock LLM for --demo and tests. Builds messages only from the brief it is given."""

from __future__ import annotations

import json
import re
from typing import Any

HOOKS = {
    "hiring": ["You're hiring for guest-facing roles, which usually means the guest workload is growing.",
               "New ops hires often inherit check-in, ID checks and deposit chasing spread across tools.",
               "Hiring for guest experience is a good moment to look at what the software could take off that role."],
    "direct_booking": ["Direct bookings skip the OTA's guest verification, so that work lands on your team.",
                       "Your own booking site means you own check-in, ID checks and deposits for those guests.",
                       "Direct guests are the best margin, and the most manual to check in."],
    "multi_market": ["Running homes in more than one market makes consistent check-in harder.",
                     "Each new market tends to add another set of guest-ops habits.",
                     "Multi-city operators usually feel guest ops sprawl first."],
    "listing_growth": ["Your listing count has grown in the open data, and guest ops usually grow with it.",
                       "Adding listings tends to stretch check-in and deposit handling first.",
                       "Growth is when manual guest steps start to hurt."],
    "pms": ["Your site runs on a PMS, and guest check-in and waivers often live outside it.",
            "Most PMS setups still leave ID checks and damage waivers to separate tools.",
            "The PMS handles bookings; the guest steps around arrival are often manual."],
    "general": ["Operators your size usually run check-in, ID checks and deposits across several tools.",
                "Guest check-in and damage handling are where small ops teams lose hours.",
                "Most mid-size operators still chase deposits by hand."],
}


class MockLLM:
    name = "mock"

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        if "hooks" in schema["properties"]:
            seg = re.search(r"Segment: (\w+)", user)
            texts = HOOKS.get(seg.group(1) if seg else "general", HOOKS["general"])
            return {"hooks": [{"angle": f"angle {i + 1}", "text": t} for i, t in enumerate(texts)]}
        brief = json.loads(user.split("Brief (the only facts you may use):\n", 1)[1].split("\n\nOpening angle", 1)[0])
        hook = user.split("Opening angle to use: ", 1)[1].split("\n", 1)[0]
        op, contact = brief["operator"], brief["contact"]
        hi = f"Hi {contact['first_name']}," if contact.get("first_name") else "Hi there,"
        name = op["name"]
        ev = brief["evidence"][0] if brief["evidence"] else None
        count = f" with {op['listing_count']} listings" if op.get("listing_count") else ""
        return {
            "linkedin_note": f"{hi} I work with HostOp, which builds software for short-term rental operators. "
                             f"{name}{count} caught my eye. Would be glad to connect.",
            "linkedin_followup": f"Thanks for connecting. {hook} HostOp handles guest check-in, ID verification, "
                                 f"damage waivers and upsells in one place. Open to a short demo with our founder?",
            "email_subject": f"guest check-in at {name}"[:50].lower(),
            "email_1": f"{hi}\n\n{hook} HostOp is an operating system for rental operators: guest check-in, ID "
                       f"verification, damage waivers, upsells and payments in one flow. Our founder built it after "
                       f"running his own rental business.\n\nWorth a short demo with him to see if it fits "
                       f"{name}?",
            "email_2": f"{hi} one more thought: damage waivers can replace chasing security deposits after "
                       f"checkout. Happy to show how that works in HostOp.",
            "email_3": f"{hi} last note from me. If guest ops at {name} are under control, no worries. If not, "
                       f"a short call with our founder could be useful.",
            "instagram_dm": f"Hey, love seeing {name} here. {hook} We build HostOp for operators like you, "
                            f"happy to share a quick demo if useful.",
            "evidence_ids_used": [ev["id"]] if ev else [],
        }
