# Sequential search diagnostics

Each new search card includes a **Flow debug log**, refreshed by the existing four-second workspace poll. Filter by domain, event, result, or details; optionally show warnings/errors only. Download the retained log as JSON for inspection. The latest 500 entries are retained per campaign, with a total event count so truncation is visible. Historical campaigns cannot be backfilled.

The log follows city scraping, website/rank filtering, duplicate domains, Hunter request and selection counts (including separate generic, malformed-email and wrong-domain exclusions, plus the number selected without names), existing email skips, NeverBounce start/results, database saves/conflicts/failures, and a per-domain summary. It identifies contacts as Contact 1/2 within their domain without recording their names, emails, credentials, or raw provider responses. Request-start events are saved before waiting on Hunter/NeverBounce, so a slow request is visible in the UI.

The current workflow is implemented by `CampaignService` and identified by `workflow: sequential-v1` on saved campaign records. It completes all Apify city runs before processing unique domains with Hunter and NeverBounce. There are no research or recommendation calls.

`GET /api/workspace` exposes each campaign's status, message, city results, warnings and progress:

- `cities_completed` / `cities_total`: completed Apify city runs.
- `scraped`: source business records collected, before domain/rank filtering.
- `discovered`: unique eligible domains after all cities finish.
- `duplicates`: repeated eligible company domains removed from the current search.
- `processed`: domains whose enrichment step finished.
- `checked`: NeverBounce checks performed, at most two selected emails per domain.
- `verified`: new accepted contacts saved, including valid, catchall and unknown results.
- `reused`: existing emails skipped, or insertion conflicts.
- `excluded`: source results excluded by rank requirements.
- `no_contact`: source results with blank website fields plus domains without an eligible non-generic email. This mixes units and is not a single conversion funnel.
- `rejected`: email checks whose outcome was not accepted.
- `verification_errors`: checks that failed; these are never counted as NeverBounce unknown results.

The `uvicorn.error.lead_funnel` logger emits `lead_funnel` JSON records. Current events include `apify_request` (actor JSON), `hunter_page_result`, `hunter_page_error`, `candidate_verification`, and `campaign_error`. Campaign records retain event totals in `diagnostics.counts` (version 2). Provider diagnostics omit credentials and contact email addresses.

Completion means all city and domain work finished, not that a requested lead target was reached. Inspect warnings and error counters for individual provider failures. Consecutive provider errors or account/quota failures stop the search. Cancellation and failures retain already-saved contacts. A backend restart marks an active search interrupted; it is not automatically resumed.

Old campaign diagnostics used different events and counters. Their historical data remains stored; it cannot be interpreted as the current sequential workflow.

Website filtering now skips only blank fields. `website_parse_fallback` records nonblank values whose domain could not be parsed; these still enter the Hunter queue after rank filtering and deduplication. `domains_ready.details.blank_websites` is the count skipped at this step. Older exports may use `unusable_websites` under the previous stricter policy.
