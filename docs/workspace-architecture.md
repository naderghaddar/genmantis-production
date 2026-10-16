# GenMantis SEO research architecture

## Product surface

The React shell exposes exactly Research Advisor and Lead Database, defaulting to the advisor. Search runs are inline conversation cards with person-target progress, location results, cancellation, shortfalls and suggested cities. Removed pages: Overview, Campaigns, Pipeline, Business Profile, and Integrations. Authentication remains an account modal. Existing profile data is retained as context; users provide targeting details through conversation.

## Advisor and execution

`ResearchAgent` uses the Responses API with strict tool schemas. `source_capabilities`, `research_market`, `research_company`, `search_crm`, and `review_campaigns` provide context. `generate_leads` creates and starts a background search for an explicit request to fetch leads. `propose_campaign` creates a planning-only draft; `start_lead_search` starts an existing draft when requested. One create/start is allowed per message. Retried message IDs do not execute another run. Search history and current persisted outcomes are supplied on follow-up turns.

`CampaignPlan.max_leads` now means the requested number of new accepted people (1–1,000), not the number of businesses to enrich. `locations` is an ordered list of up to 30 city/region pairs. Old single-city drafts normalize into one location. A versioned durable reservation precedes worker submission and provider work. The five-tool conversational budget does not truncate the background worker.

The worker visits approved locations in order. Each Maps request uses `maxCrawledPlacesPerSearch=70`, one category search, and one location. It processes up to 70 results, deduplicates company domains across the run, applies requested ranking/company-fit filters, then calls Hunter for each eligible company. It stops when the person target is met, before spending on another city or contact. It never expands geography automatically.

## Person and email policy

The workspace uses `lead_policy.py`: an identifiable named contact with a Hunter email and an actual NeverBounce result in `valid`, `catchall`, `unknown`. Generic inboxes, unnamed contacts, invalid/disposable addresses, missing outcomes, and `verification_error` do not count. NeverBounce's explicit `unknown` is distinct from a failed/unavailable check.

Hunter candidate ranking prioritizes relevant SEO buyers. The worker checks all suitable people returned within configured Hunter result/page limits, not just one person per company. Each accepted person is stored separately, keyed by a case-folded email hash. Duplicate emails across companies/cities and already-saved accepted people do not increase the target count. A request asks for new people.

Only accepted people enter the new lead database. Failed checks, excluded businesses and missing contacts contribute to run counters rather than lead rows. Previously stored records are preserved; reads and exports apply the current person/status policy and deduplicate emails. Provider evidence remains unchanged. CSV exports include exact email statuses and escape formula-leading cells. The legacy standalone enrichment APIs retain their old contracts; the new advisor/workspace is the active product path.

## Shortfalls and recommendations

Exhausting the approved locations below the target produces `shortfall`, with `shortfall = target - verified`, a concrete result message and per-location counts. A separate two-request research budget searches for comparable nearby cities and structures recommendations. Evidence URLs must appear in the actual search sources; already-searched and duplicate city/region pairs are discarded. If recommendation research fails, the count remains accurate and the limitation is shown.

Suggestions are displayed in the advisor alongside a button that composes a request for the remaining count and suggested locations. Clicking that button does not itself scrape. The user can edit and send the request. Provider/storage interruption is `failed`, cancellation is `cancelled`, and a process restart is `interrupted`; these do not falsely claim every city was exhausted. Background outcomes are visible via workspace polling and available to subsequent advisor turns.

## Storage and isolation

Supabase project: `cpuhytycdbthpqvevjmc`, the production project originally supplied as blank. No other Supabase project is used. Existing table `gm_workspace_records` supports profile/campaign/lead/thread JSON records with owner-based RLS. This change requires no schema migration.

The API validates Supabase tokens; storage forwards the user's JWT to enforce RLS. Local development has a separate browser-owned SQLite workspace. Cloud write failures preserve results in a local recovery outbox for later synchronization. Retain the recovery data volume.

Run one backend process. Campaign locks/capacity are in-process. Persisted runs do not automatically resume paid provider operations after restart. Cancellation cannot reverse already billed calls or forcibly stop a remote Apify job. Database leases and provider-aware durable queue resumption would be needed for multiple replicas.

## Validation

Tests cover the user's 100-target/three-city/30-result case, a 50-person stopping case, multiple named people at one business, duplicate emails and saved-contact reuse, generic/unnamed exclusions, all NeverBounce statuses, cancellation, schema bounds, city evidence validation, model tool dispatch and idempotency, exports, and the two-screen UI. The Apify actor-input assertion fixes the business count at 70 regardless of the person's target.

Automated tests mock external providers. A live model dispatch smoke test uses isolated in-memory storage and a mocked executor, so it exercises real model/tool contracts without starting a paid scrape. Browser rendering, live paid-provider accounts, signup email delivery and deployment require separate integration validation.
