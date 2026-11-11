# Finding the first 1,000 operators

Goal: 1,000 resolved, deduplicated STR operators in the 10 to 500 listing range, each with evidence for why
they fit. This is a method, not a result. The demo's counts (about 1,700 operators) are SYNTHETIC and say
nothing about real yield.

## Sources, in order of cost

| # | Source | What it gives | Cost and terms |
|---|---|---|---|
| 1 | **Inside Airbnb** city snapshots | `host_id`, `host_name`, `calculated_host_listings_count` and neighbourhoods. Hosts with 10+ listings are the core list. | Free, CC BY 4.0. Must attribute. Snapshots lag by months. |
| 2 | **City STR permit / licence registries** (open-data portals) | Licensee or business name, sometimes the operator company and address | Free. Columns differ by city, so each one needs a mapping YAML. Check each portal's terms. |
| 3 | **Manual lists**: conference exhibitors, STR association member directories, podcast guests | Names and domains of active, visible operators | Free but manual. Respect each list's terms. |
| 4 | **Firecrawl web search** (`--web`) | Operator websites for queries like "vacation rental management {city}" | Paid credits. Only open web results; marketplace and social domains are filtered out. |

Not used, deliberately: Airbnb, Vrbo, LinkedIn and Instagram pages or private APIs. The fetcher blocks them.

## From rows to operators

1. **Normalise** names (strip LLC, Inc, "Vacation Rentals" and so on) and domains.
2. **Resolve**, in this order:
   - same Inside Airbnb `host_id`
   - same website domain
   - fuzzy name match (token sort ratio ≥ 92) only for distinctive names, and never across different countries
3. Every merged field keeps its provenance (source, URL, snapshot date), so a reviewer can see where each fact
   came from.
4. **Multi-market** operators appear in several city snapshots under one host or domain, and score higher.

## Getting a website for each operator

Inside Airbnb gives a host name, not a domain. In order:
- domains from permit rows and lists
- Firecrawl search on the operator name plus city, accepting only a result whose page title or body mentions
  the name
- a manual research queue for Tier A operators that still have no site

## Making 1,000 realistic

The real count depends on how many cities you load and how many hosts in each have 10 to 500 listings. Count
it from your own snapshots with `hostop discover` and `hostop score`, and add cities until the Tier A+B pool
is large enough. Expect more duplicates than you think: the same company often runs several host accounts.

## Quality checks before outreach

- Spot-check 20 random Tier A operators with `hostop score --explain`. Does each factor's evidence hold up?
- Watch for property managers whose sites are on a franchise platform. They may not choose their own tools.
- Re-pull Inside Airbnb each quarter. Changes in listing count are a signal (`listing_growth`).
