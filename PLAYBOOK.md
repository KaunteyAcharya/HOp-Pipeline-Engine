# Outbound playbook

What HostOp may claim comes only from `company.facts` in `config/hostop.yaml`:
- an AI operating system for STR operators with 10 to 500 listings
- guest check-in, ID verification, damage waivers, upsells, and payments and financials
- AI guest messaging is next on the roadmap
- founder-led and bootstrapped, and live with paying operators
- the founder scaled his own rental arbitrage business to 400+ units

Nothing else. No customer names, no metrics, no integrations.

## Who

| Tier | Typical profile | Channel order |
|---|---|---|
| A | 15 to 150 listings, several markets, direct-booking site, visible PMS or hiring | LinkedIn note, then email 1, then Instagram DM, then emails 2 and 3 |
| B | In the ICP range with fewer signals | Email sequence; LinkedIn only if a named decision-maker is found |
| C | Out of the ICP range or no evidence | No outreach. Re-score next quarter. |

Contacts in a CASL, GDPR or unknown-country regime are held back from export until a person checks the
lawful basis.

## Sequence (per contact, all drafted and then approved by a person)

| Day | Step | Notes |
|---|---|---|
| 0 | LinkedIn connection note (≤300 chars) | No pitch. One observed fact plus a reason to connect. |
| 1 | Email 1 | Hook built from evidence, one question, opt-out line |
| 4 | Instagram DM (if the operator has a public business account) | Short and casual. Sent by hand. |
| 5 | Email 2 | A different value prop from `value_props` |
| 10 | Email 3 | Polite close-out |

Daily caps live in config (`outreach.daily_caps`). The queue spreads tasks across weekdays to stay under them.

## Hooks

Hooks are chosen from evidence the analyser found, never guessed:
- **hiring**: they are hiring guest-experience or ops staff, so lead with check-in and ID verification
  reducing manual work. Don't claim a number.
- **direct_booking**: they run their own booking site, so lead with upsells and damage waivers on direct
  bookings.
- **multi_market**: operating in several cities, so lead with one system for check-in and payments across
  markets.
- **general**: the ICP range only.

Each hook has three variants (`hook_id`). Rotate them evenly, and compare only once each has 30+ sends
(`hostop report` flags anything smaller).

## Objections (seed list; update from `hostop insights` on real calls)

| Objection | Response principle |
|---|---|
| "We already use Guesty / Hostaway…" | Ask which guest-facing steps still happen outside it. Don't claim an integration; say you'll check. |
| "Not now, busy season" | Agree. Ask which month is quiet and log a follow-up task for then. |
| "Price" | Ask what deposits, damage and manual check-in cost them today. Don't quote savings you can't show. |
| "Never heard of you" | True and fine: founder-led, bootstrapped, live with paying operators. Offer a short demo. |
| "Switching is painful" | Ask what a pilot on a few listings would need. |

## Replies

- **Opt-out or "remove me"**: the reply webhook or `hostop log ... opt_out` suppresses the address
  immediately. Don't reply again.
- **Positive**: a person marks it `positive` and books a demo by hand, then logs `demo_booked` and later
  `demo_held`.
- **Bounce**: log it; the address is suppressed. If bounces exceed about 2% of a campaign, pause it and
  re-check the list.

## Weekly ritual (30 min)

1. Run `hostop report` and read the sample sizes before reading any rate.
2. Look at hooks with 30+ sends, then retire or rewrite the weakest variant.
3. Run `hostop insights` on new call transcripts, and add new pains and objections to this file.
4. Run `hostop dns-check` on the sending domains.
