# Application notes

## Design decisions

- **Human in the loop by construction.** There is no code path that sends a message. The API, the n8n flows
  and the exports all stop before sending.
- **Evidence first.** Scores, hooks and drafts all cite Evidence rows (URL plus snapshot). The validator
  rejects drafts whose numbers are not in that evidence or in `company.facts`.
- **Open data over scraping.** Inside Airbnb (CC BY 4.0) and city permits give scale without touching
  Airbnb, Vrbo, LinkedIn or Instagram. Websites are fetched politely: robots.txt, per-host delay and a cache.
- **Credits are budgeted.** Enrichment stops at `credit_budget_per_run`. Apollo's free search runs before any
  paid match, and emails are never guessed.
- **Honest analytics.** Every rate shows n; small samples are flagged with Wilson intervals; nothing is
  extrapolated.
- **Synthetic demo is isolated.** It has its own database, `.example` domains, SYNTHETIC labels, and is
  refused by the Attio push.

## What could not be verified

- **Attio adapter**: built from the public API reference (checked 2026-11-11), not run against a live
  workspace. The list slug `hostop_pipeline` and the `stage` status attribute must exist in your workspace.
- **Apollo and Hunter**: request shapes match their docs, but the tests use mocks only. Credit consumption
  per call was not measured.
- **Firecrawl v2 search**: the response shape (`data.web`) was taken from the docs and not exercised with a
  real key.
- **Instantly and Smartlead CSV import**: the column mapping must be confirmed in each tool's import UI.
- **Inside Airbnb columns** can change between snapshots. The importer was tested on generated files with
  the current column names.
- **Permit datasets**: each city needs its own mapping YAML. None was tested on a real portal export.
- **The Anthropic call** (structured output with `output_config`) was exercised with a mock LLM in tests and
  the demo.
- **The DNS checker's** DKIM detection only probes common selectors, so a custom selector needs `--selector`.
- **Compliance classification** is a heuristic (country to regime). It is not legal advice; the CASL, GDPR
  and unknown cases are held for human review.

## API assumptions to double-check

| API | Assumption |
|---|---|
| Firecrawl | `POST https://api.firecrawl.dev/v2/search`, Bearer auth, results in `data.web[]` with `url`, `title` and `description` |
| Apollo | `POST /api/v1/mixed_people/api_search` returns people without emails; `POST /api/v1/people/match` consumes credits and returns `email` and `email_status`; header `x-api-key` |
| Hunter | `GET /v2/domain-search` and `/v2/email-verifier`; header `X-API-KEY`; `status` is `valid` or `accept_all` / `unknown` / `invalid` |
| Attio | `PUT /v2/objects/{object}/records?matching_attribute=…` upserts; `PUT /v2/lists/{list}/entries`; `POST /v2/notes`; the id is at `data.id.record_id` |
| Anthropic | Model `claude-opus-5-5` (set via `ANTHROPIC_MODEL`) and the `output_config.format` JSON schema |
| Sending tools | Reply-webhook payload fields differ by tool; map them in the n8n Set node |

## Five next features

1. **Re-verification and bounce sync**: pull bounces and replies from Instantly or Smartlead with their APIs
   (read-only) instead of logging them by hand.
2. **Listing-growth tracking**: compare quarterly Inside Airbnb snapshots per operator and alert when a Tier
   B operator crosses into Tier A.
3. **LLM-assisted call insights**: add a structured-output pass that proposes tags for each line, shown next
   to the rule-based tags for a human to confirm.
4. **Hook experiment manager**: allocate each hook evenly and stop an experiment automatically at a preset n,
   with the report showing intervals per variant.
5. **Multi-user review**: approver identity and audit log on every draft approval and edit, plus role-based
   access to the dashboard.
