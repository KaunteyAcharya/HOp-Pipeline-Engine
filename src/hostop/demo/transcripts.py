"""Writes SYNTHETIC discovery-call transcripts for the call-insights demo. Fictional people and companies.

Rep lines only state facts from company.facts in config/hostop.yaml.
"""

from __future__ import annotations

from pathlib import Path

HEADER = "# SYNTHETIC TRANSCRIPT - fictional call generated for the demo. Not a real conversation.\n"

CALLS = {
    "call_01_harbor_stays.txt": [
        "Rep: Thanks for taking the call. How do you handle guest check-in today?",
        "Prospect: Honestly it's door codes sent by hand and a lot of texts at 3am when they can't get in.",
        "Prospect: Damage is the other one. We stopped taking deposits because chasing them was a nightmare.",
        "Rep: HostOp covers guest check-in, ID verification and damage waivers.",
        "Prospect: We already use Hostaway for the channel side, so it has to sync with that.",
        "Prospect: We're in busy season, so not right now, maybe next quarter.",
    ],
    "call_02_pine_ridge.txt": [
        "Rep: What does your finance side look like?",
        "Prospect: Owner statements are a spreadsheet. Reconciling payouts takes my partner two days a month.",
        "Prospect: We had a party last summer, so ID verification is on my list.",
        "Prospect: Price matters, we're 40 units and margins are thin.",
        "Rep: Understood. HostOp is founder-led and live with paying operators.",
        "Prospect: Never heard of you before, do you have references I can call?",
    ],
    "call_03_coastal_keys.txt": [
        "Rep: Where does revenue leak for you?",
        "Prospect: Early check-in requests come in and we never charge for them. That's extra revenue we lose.",
        "Prospect: And the inbox is constant, guest messaging eats my whole morning.",
        "Rep: Upsells are live today; AI guest messaging is next on HostOp's roadmap.",
        "Prospect: Switching would mean we retrain cleaners on a new app, that's the hard part.",
    ],
}


def write_transcripts(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, lines in CALLS.items():
        (folder / name).write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return folder
