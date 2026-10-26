# GenMantis SEO research architecture

## Product surface

The React shell exposes exactly Research Advisor and Lead Database, defaulting to the advisor. Search runs are inline conversation cards with person-target progress, location results, cancellation, shortfalls and suggested cities. Removed pages: Overview, Campaigns, Pipeline, Business Profile, and Integrations. Authentication remains an account modal. Existing profile data is retained as context; users provide targeting details through conversation.

## Advisor and execution

`ResearchAgent` uses the Responses API with strict tool schemas. `source_capabilities`, `research_market`, `research_company`, `search_crm`, `crm_insights`, and `review_campaigns` provide context. `remember_business_context` merges explicitly supplied agency facts into the owner-scoped profile, preserving null/unmentioned fields. `stop_lead_search` cancels an owned active search on request. `generate_leads` creates and starts a background search for an explicit request to fetch leads. `propose_campaign` creates a planning-only draft; `start_lead_search` starts an existing draft when requested. One create/start is allowed per message. Retried message IDs do not execute another run. Only this conversation's persisted campaign outcomes are supplied automatically. A campaign tool call must establish its niche from user messages in this conversation or explicit saved business context; other conversations do not supply an implicit niche.

`CampaignPlan.max_leads` now means the requested number of new accepted people (1–1,000), not the number of businesses to enrich. `locations` is an ordered list of up to 30 city/region pairs. Old single-city drafts normalize into one location. A versioned durable reservation precedes worker submission and provider work. The five-tool conversational budget does not truncate the background worker.

The worker first visits every approved location in order, requesting 100 Maps businesses per city. After a pass fills its cap and yields new domains, it queues a deeper pass in that same city with `maxCrawledPlacesPerSearch` increased by 100. `max_city_rounds` defaults to 3 (100/200/300), accepts 1-5, and is shown in draft cards. Old persisted drafts without the field retain one pass. Each request keeps the same niche, city and region. A smaller batch or duplicate-only pass ends that city's queue. New cities are never selected automatically.

Domains and emails are deduplicated across the entire run, including deeper passes. Source discovery can bill repeated rows; enrichment and verification are not repeated for those domains/emails. The overall discovered counter counts distinct companies; per-pass counters describe that pass. The worker stops at the exact new-person target before another city, pass, contact or verification. A finite city list may exhaust before the target; the agent must report this honestly.

Runs persist `stop_reason`, city pass number, requested business limit and remaining count. Hunter/NeverBounce quota/authentication/cooldown failures halt work before more discovery; three consecutive contact-search or email-check failures also halt. ProviderHTTP still handles bounded transient retries. One active campaign per owner prevents concurrent runs from counting the same new person twice, even if process capacity permits multiple owners.

Explicit positive company-fit criteria are checked individually against cited evidence. Missing, unknown or uncited criterion checks become unknown fit, contribute to the review counter and do not spend on contact enrichment or count toward the target. Ordinary searches without extra criteria continue without website research.

## Person and email policy

The workspace uses `lead_policy.py`: an identifiable named contact with a Hunter email and an actual NeverBounce result in `valid`, `catchall`, `unknown`. This remains the default `email_policy=accepted`, as requested by the owner. New searches may explicitly select `valid_only`; this narrows that run without relabelling older CRM evidence. Generic inboxes, unnamed contacts, invalid/disposable addresses, missing outcomes, and `verification_error` do not count. NeverBounce's explicit `unknown` is distinct from a failed/unavailable check.

Hunter candidate ranking prioritizes relevant SEO buyers. `max_leads_per_company` defaults to 1, accepts integers from 1 to 1,000, and supports null for explicitly unlimited contacts. The advisor maps “200 leads from 200 unique companies” to a 200-person target and a company cap of 1. Existing saved leads count toward the cap, including archived and legacy records. Companies are grouped by normalized registrable website domain; branches and subdomains share the cap. Unrelated domains cannot reliably be identified as one organization. Rejected or duplicate candidates consume no new slots; the worker tries the next candidate until the cap or overall target is reached. Companies already at their cap are skipped before research or enrichment. Old drafts adopt the new default when started; completed history retains its original plan.

Before provider work, `WorkspaceStore.lead_index` loads compact email/domain keys for the current owner, regardless of lead status. SQLite uses the existing `(owner,kind,id)` primary-key prefix; Supabase selects only identity fields and uses primary-key cursor pagination in 500-row pages. Pending cloud outbox results are included. Building the index is O(saved leads); email membership and per-company counts are O(1) per candidate. The index is updated during the run. One active campaign per owner prevents competing snapshots within the supported single-process deployment. A failed index read stops the run before provider spending.

Each accepted person is stored separately, keyed by a trimmed, case-folded email hash. New lead writes use insert-if-absent (SQLite `INSERT OR IGNORE`, PostgREST `resolution=ignore-duplicates`) so a conflict cannot overwrite CRM notes or count as a new lead. Regular CRM updates remain updates. Duplicate emails across companies/cities and all already-saved people never increase the target count. Duplicate filtering cannot be disabled. No schema migration is required.

Only accepted people enter the new lead database. Failed checks, excluded businesses and missing contacts contribute to run counters rather than lead rows. Previously stored records are preserved; reads and exports apply the current person/status policy and deduplicate emails. Provider evidence remains unchanged. CSV exports include exact email statuses and escape formula-leading cells. The legacy standalone enrichment APIs retain their old contracts; the new advisor/workspace is the active product path.

## Shortfalls and recommendations

Exhausting the approved locations and eligible deeper passes below the target produces `shortfall`, with `shortfall = target - verified`, a concrete result message, stop reason and per-city/pass counts. The shortfall is also recorded on cancellation or provider failure. A separate two-request research budget searches for comparable nearby cities and structures recommendations. Evidence URLs must appear in the actual search sources; already-searched and duplicate city/region pairs are discarded. If recommendation research fails, the count remains accurate and the limitation is shown.

Suggestions are displayed in the advisor alongside a button that composes a request for the remaining count and suggested locations. Clicking that button does not itself scrape. The user can edit and send the request. Provider/storage interruption is `failed`, cancellation is `cancelled`, and a process restart is `interrupted`; these do not falsely claim every city was exhausted. Background outcomes are visible via workspace polling and available to subsequent advisor turns.

## Storage and isolation

Supabase project: `cpuhytycdbthpqvevjmc`, the production project originally supplied as blank. No other Supabase project is used. Existing table `gm_workspace_records` supports profile/campaign/lead/thread JSON records with owner-based RLS. This change requires no schema migration.

The API validates Supabase tokens; storage forwards the user's JWT to enforce RLS. Local development has a separate browser-owned SQLite workspace. Cloud write failures preserve results in a local recovery outbox for later synchronization. Retain the recovery data volume.

Run one backend process. Campaign locks/capacity are in-process. Persisted runs do not automatically resume paid provider operations after restart. Cancellation cannot reverse already billed calls or forcibly stop a remote Apify job. Database leases and provider-aware durable queue resumption would be needed for multiple replicas.

## Validation

Tests cover the user's 100-target/three-city/30-result case, a 50-person stopping case, an exact 60-person target requiring a deeper same-city pass, multiple named people at one business, duplicate emails and saved-contact reuse, generic/unnamed exclusions, all NeverBounce statuses, cancellation, schema bounds, city evidence validation, model tool dispatch and idempotency, exports, and the two-screen UI. Actor-input assertions verify a 100-business first pass and a 200-business deeper pass without changing geography. Tests also cover city-depth bounds, duplicate-only exhaustion, provider circuit breaking, evidence-backed criteria, partial profile updates, cancellation ownership and legacy draft budgets.

Automated tests mock external providers. The opt-in `backend/scripts/smoke_advisor.py --live` uses isolated in-memory storage and a mocked executor. On October 21, 2026, five real requests on unchanged `gpt-6.1-sol` confirmed missing-brief clarification and one correctly configured 60-person queued search. No scraping, enrichment or cloud writes ran. The implementation follows the [official strict function-calling contract](https://developers.openai.com/api/docs/guides/function-calling). Browser rendering, live paid-provider accounts, signup email delivery and deployment require separate integration validation.


## Company qualification

Maps searches include category filters for recognized local niches and retain the
same filters on deeper passes. Unrecognized niches use the search term and the
backend category-evidence check. Every Maps company must match its requested
niche using the primary or secondary categories. Merely appearing in search, or
having the niche in a title, is insufficient. Listed cities that differ from the
requested city are excluded.

Known directory domains (including Healthline provider listings) cannot become
company domains. Before a contact can count, the company needs business-name /
brand agreement with the domain or Hunter organization-name agreement. Ambiguous
identity is held for review. Every accepted contact's email must share the
company's registrable domain, and a mismatching domain returned by Hunter is
rejected. This is company-level affiliation evidence; employment at a specific
local branch remains unestablished. Saved leads carry `company_validation` with
the evidence basis. These deterministic checks do not add model calls, crawl
arbitrary websites or change the research budget. They are evidence checks, not
a guarantee of legal website ownership or present employment.

Cancelling while waiting on a running Apify actor requests its abort. An abort
failure is logged, and the campaign still stops processing. `apify_request` logs
the exact actor input without credentials. The UI reports niche/location
exclusions and insufficient qualification/identity evidence. Older saved leads
are retained; this change does not retroactively requalify or delete them.
