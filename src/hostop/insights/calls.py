"""Call insights: pull objections, pains and verbatim prospect phrases out of call transcripts.

Transcript format: plain text, one turn per line, `Speaker: text`. Lines whose speaker is in REP_SPEAKERS are
ignored (we only learn from what prospects say). Extraction is rule-based and transparent so a reviewer can
see why each line was tagged; nothing is summarised or invented. Counts come with the number of transcripts.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from hostop.models import CallInsight

REP_SPEAKERS = {"rep", "hostop", "ae", "sdr", "founder"}
SMALL_SAMPLE = 10

OBJECTIONS: dict[str, list[str]] = {
    "already_has_tool": [r"already (use|have|pay for)", r"we use (guesty|hostaway|hospitable|ownerrez|lodgify)"],
    "price": [r"too expensive", r"\bbudget\b", r"\bprice\b", r"margins?"],
    "timing": [r"not (right )?now", r"next (quarter|year|season)", r"busy season"],
    "integration": [r"integrat", r"sync with", r"work with our pms"],
    "switching_cost": [r"migrat", r"switching", r"retrain", r"contract"],
    "trust": [r"never heard of", r"references?\b", r"how many customers"],
}
PAINS: dict[str, list[str]] = {
    "deposits_damage": [r"deposit", r"damage"],
    "manual_checkin": [r"check-?in\b(?! request)", r"door codes?", r"\bkeys?\b"],
    "id_verification": [r"\bid verification\b", r"\bparty\b", r"fraud"],
    "guest_messaging": [r"messaging", r"\btexts?\b", r"\binbox\b"],
    "spreadsheets_finance": [r"spreadsheet", r"reconcil", r"payouts?", r"owner statements?"],
    "upsell_revenue": [r"early check-?in", r"late check-?out", r"upsell", r"extra revenue"],
}


@dataclass
class Tagged:
    transcript: str
    kind: str  # objection | pain
    tag: str
    text: str


def _prospect_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if line.startswith("#") or ":" not in line:
            continue
        who, said = line.split(":", 1)
        if who.strip().lower() not in REP_SPEAKERS and said.strip():
            out.append(said.strip())
    return out


def extract(name: str, text: str) -> list[Tagged]:
    tags: list[Tagged] = []
    for said in _prospect_lines(text):
        low = said.lower()
        for kind, table in (("objection", OBJECTIONS), ("pain", PAINS)):
            for tag, pats in table.items():
                if any(re.search(p, low) for p in pats):
                    tags.append(Tagged(name, kind, tag, said))
    return tags


def analyze_dir(s: Session, folder: Path, synthetic: bool) -> tuple[int, list[Tagged]]:
    files = sorted(folder.glob("*.txt"))
    tags = [t for f in files for t in extract(f.name, f.read_text(encoding="utf-8"))]
    s.execute(delete(CallInsight).where(CallInsight.is_synthetic.is_(synthetic)))
    for t in tags:
        s.add(CallInsight(transcript_name=t.transcript, kind=f"{t.kind}:{t.tag}", text=t.text,
                          is_synthetic=synthetic))
    return len(files), tags


def to_markdown(n_files: int, tags: list[Tagged], synthetic: bool) -> str:
    lines = ["# Call insights", ""]
    if synthetic:
        lines += ["> **SYNTHETIC DEMO TRANSCRIPTS.** These calls never happened; this shows the method only.", ""]
    lines += [f"Transcripts analysed: **{n_files}**. Tags are rule-based keyword matches on prospect lines; "
              "read the quotes before acting on a count."]
    if n_files < SMALL_SAMPLE:
        lines += ["", f"**SMALL SAMPLE** (under {SMALL_SAMPLE} calls): treat counts as anecdotes, not frequencies."]
    for kind in ("objection", "pain"):
        sub = [t for t in tags if t.kind == kind]
        calls = Counter({tag: len({t.transcript for t in sub if t.tag == tag}) for tag in {t.tag for t in sub}})
        lines += ["", f"## {kind.title()}s", "", "| tag | calls mentioning | example (verbatim) |", "|---|---|---|"]
        for tag, n in sorted(calls.items(), key=lambda kv: (-kv[1], kv[0])):
            ex = next(t.text for t in sub if t.tag == tag).replace("|", "/")
            lines.append(f'| {tag} | {n}/{n_files} | "{ex}" |')
    lines += ["", "## How to use", "",
              "- Pains raised in several calls are candidates for new hooks; keep only claims HostOp can back "
              "from `company.facts` in config/hostop.yaml.",
              "- Objections feed the objection table in docs/PLAYBOOK.md.", ""]
    return "\n".join(lines)
