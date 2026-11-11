# 90-day plan

Volumes below are planning inputs, not forecasts. Replace them with real numbers from `hostop report` as
soon as they exist. No reply or conversion rate is assumed anywhere.

## Days 1–30: foundation and first sends

- **Week 1**
  - Buy 2 to 3 sending domains.
  - Set up 2 to 3 inboxes each, plus SPF, DKIM and DMARC. `hostop dns-check` must pass.
  - Start warm-up (`hostop warmup`).
- **Week 1–2**
  - Load Inside Airbnb for the 6 configured cities, plus the permit datasets that have usable columns.
  - Run `discover`, `analyze` and `score`.
  - Spot-check 20 Tier A explanations by hand and fix the scoring weights if needed.
- **Week 2**: fill in the `sender` config and write 3 hook variants per segment. The founder reviews tone.
- **Week 2–3**:
  - Send LinkedIn and Instagram tasks by hand to Tier A, within the daily caps. These need no email warm-up.
  - Log every send.
- **Week 3**: after 14 days of warm-up, export the first email batch to Tier A at about 5 emails per inbox
  per day.
- **Week 4**: first weekly report. Expect SMALL SAMPLE flags everywhere, and make no decisions from rates yet.

## Days 31–60: volume and learning

- Ramp email to the planned cap per inbox (+3 per week). Pause at any bounce or complaint spike.
- Extend to Tier B. Add cities if the Tier A+B pool falls below about 4 weeks of sending capacity.
- Record calls (with consent) and run `hostop insights` weekly. Turn repeated pains into new hook variants.
- Connect the n8n flows: Slack review alerts and the reply webhook.
- Connect the Attio push once the adapter is tested against a sandbox workspace.

## Days 61–90: decide what works

- Compare hooks and channels only where n ≥ 30 sends per group, and look at the Wilson intervals, not point
  rates.
- Retire weak hook variants and keep the rotation even for the rest.
- Write up what objections showed up and update PLAYBOOK.md.
- Decide whether to add a second ICP slice (for example, larger operators at 150 to 500 listings), based on
  demos held, not on reply rate.

## Owner checklist

| Owner | Weekly |
|---|---|
| GTM (you) | Review and approve drafts, do the manual LinkedIn and Instagram tasks, log events, write the report |
| Founder | Take demos; review new hook variants for accuracy against `company.facts` |
