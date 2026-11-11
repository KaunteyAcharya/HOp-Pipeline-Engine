# Loom script (about 5 minutes, demo mode)

Everything shown is SYNTHETIC demo data. Say so at the start.

**0:00 – Hook (20s)**
"This is the HostOp Pipeline Engine. It finds STR operators with 10 to 500 listings from open data, explains
why each fits, and drafts outreach that a human approves. It never sends anything itself. Everything you'll
see is synthetic demo data."

**0:20 – Run it (40s)**
Terminal: `hostop run-all --demo`. Point out each stage as it prints:
- discover, with the Inside Airbnb attribution
- analyze, which is robots-aware
- score, enrich and draft

**1:00 – Pipeline tab (40s)**
Dashboard, Pipeline tab: progress toward 1,000 and tier counts.
Open one Tier A operator and expand the score factors. "Every point links to evidence: the page, the
dataset row, the date."

**1:40 – Draft review (60s)**
Draft review tab:
- Show a draft and the evidence ids it used.
- Edit it to add "we guarantee 30% more revenue" and save. It flips to needs_fix: the validator blocks
  invented numbers and guarantees.
- Revert it and approve.

**2:40 – Manual queue and export (40s)**
Manual queue tab: LinkedIn and Instagram tasks under daily caps, sent by a person.
Terminal: `hostop export --demo`. Show the SYNTHETIC_ filename and the postal-address signature.

**3:20 – Deliverability (20s)**
Deliverability tab: the DNS check and the warm-up plan.

**3:40 – Analytics and insights (50s)**
Analytics tab:
- Every rate shows n.
- Under 30 sends it is flagged SMALL SAMPLE with an interval.
- "No projections."

Open `reports/SYNTHETIC_call_insights.md`: objections and pains with verbatim quotes.

**4:30 – Close (30s)**
"Guardrails are in code: blocked domains, verified emails only, a fact allowlist for HostOp claims, and
suppression on opt-out. Next steps are in APPLICATION_NOTES.md."
