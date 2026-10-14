# GenMantis v3 - Conversational lead generation

One search runs the existing pipeline: **Apify scrape -> company domain -> Hunter contacts -> deterministic selection -> NeverBounce verification -> two CSV exports**. A conversational assistant now prepares and confirms searches on top of it. React/TypeScript/Vite and FastAPI remain. The original three-field manual search is accessible below the chat. Conversations persist in local SQLite; jobs still use the bounded in-memory run manager. There is no account/login system, CRM, or email sending.

## Conversational assistant setup

Install the updated backend requirements using the commands below. Preserve your existing `.env` values and add:

```dotenv
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-5.4-mini
```

Get a key from your [OpenAI API project](https://platform.openai.com/api-keys). The model is configurable and must support Responses, structured outputs, and function calling. Restart FastAPI after changing configuration. The manual form works without OpenAI; chat requires its key and model access. Existing Apify/Hunter/NeverBounce keys are still required to start lead generation.

Open the app and describe your prospects. The assistant gathers niche and one US city/state, remembers changes, and shows a validated confirmation card. **Start Lead Search** approves that specific plan version; **Edit Search** invalidates approval. Typed approval never starts a job. The registered function uses the existing RunManager directly, with argument/ownership checks, strict schema, no parallel calls, and durable execution reservations/idempotency. No source job starts during ordinary chat.

The official OpenAI SDK uses Responses structured parsing for requirements, `previous_response_id` for context, and function calls after approval. Backend-owned plans remain authoritative. SQLite at `backend/.data/agent.sqlite3` stores conversations, versions, approvals and execution records; optional AGENT_DB_PATH changes the location. The directory is ignored by Git. Browser ownership uses an HttpOnly, SameSite=Strict session cookie. Conversations expire after 24 hours. Keep the cookie to restore them; this is local session isolation, not production authentication.

Ranking filters run **before Hunter/NeverBounce** using the actor's reported rank and search context. The public actor build schema verifies rank as a one-based search-result position; schema evidence is saved in `backend/tests/fixtures/apify_rank_schema.json`. Ads, unknown ad status, missing ranks, and missing search context do not qualify. Multiple observations use the best (lowest) valid reported position, with all contexts retained. Rankings are query/map-area-specific, not universal citywide positions. No rating/review proxy is used. Source searches still collect at most 30 places; max_leads caps enrichment after filtering, at most 30. Unmatched businesses remain in All Results with source evidence and filter reasons. Unsupported size/revenue/employee-count qualifications block confirmation until removed.

Agent API routes:

- `POST /api/agent/conversations`
- `GET /api/agent/conversations/{conversation_id}`
- `POST /api/agent/conversations/{conversation_id}/messages` with `{message, message_id}`
- `POST /api/agent/search-plans/{plan_id}/confirm` with `{version}`
- `POST /api/agent/search-plans/{plan_id}/edit` with `{version}`

Progress and downloads reuse `/api/runs/{run_id}` and its download routes, scoped to the browser session. Polling and completion summaries never call OpenAI. Only conversation text and plan/tool metadata go to the model; CSVs, provider keys and lead datasets do not.

Run the tests/build below; all external providers and OpenAI are mocked. Live model interpretation and paid provider behavior still need valid credentials and manual verification. See [agent architecture, safeguards, ranking policy, and live checklist](docs/agent.md).

## Architecture

`POST /api/runs` validates inputs and provider configuration, creates an in-memory job, and immediately returns 202. A bounded thread executor runs the pipeline while the frontend polls local status. Apify starts exactly once per job; only status/dataset reads are retried. Legacy `/api/scrapes` endpoints remain for scrape-only API clients; all new runs require the same browser session for reads/downloads. Pre-v3 unclaimed source IDs are not accessible through the legacy routes.

Backend files:

- `config.py`: secrets and validated configuration.
- `models/leads.py`: separate business, contact, verification, lead, and progress schemas.
- `services/apify_service.py`: existing fixed payload, nonblocking actor start, status, and full dataset retrieval.
- `services/business_service.py` / `domain_service.py`: normalize/deduplicate businesses, extract registrable domains with tldextract, and exclude missing/invalid/directory/social URLs.
- `services/hunter_service.py`: header authentication, contact parsing, bounded pagination, and partial results.
- `services/contact_selector.py`: deterministic job-relevance ranking and actual generic-address fallback.
- `services/neverbounce_service.py` / `provider_http.py`: encoded verification requests, validated results, pacing, bounded retries, and safe error reasons.
- `services/enrichment_pipeline.py`: orchestration, domain/email caching, alternatives, and exports.
- `services/run_store.py`: thread-safe snapshots, bounded jobs/storage, idempotency keys, and lifecycle shutdown.
- `services/csv_service.py`: normalized columns, original data JSON, and formula-safe cells.

All provider calls happen on the backend. Keys and complete provider exceptions never reach React or application logs. Keep HTTP debug logging disabled, especially because NeverBounce uses query authentication.

## Accounts and setup

Use Python 3.11+ and Node.js 22.12+ (tested with Python 3.13 and Node 22.15).

Required accounts:

1. [Apify](https://console.apify.com/settings/integrations): token, actor access, and credits for `nwua9Gu5YrADL7ZDj` (`compass/crawler-google-places`).
2. [Hunter](https://hunter.io/api): API key and Domain Search access. Each filtered search requests at most ten contacts from one page by default. Domain Search tries priority job titles, then executive seniority, then decision_maker=true, then type=generic. Each subsequent query runs only if the previous successful query found no suitable candidates. Provider failures do not trigger fallback queries. At most one final contact is exported per domain; Hunter can return multiple candidates so they can be ranked. Result/page caps apply to each filtered query.
3. [NeverBounce](https://app.neverbounce.com/): create a Custom Integration App with a V4 API key and verification credits. See [authentication instructions](https://developers.neverbounce.com/reference/authentication).

From the repository folder in Windows PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `.env` does not exist, copy `.env.example` to `.env`. If it already contains your Apify token, preserve it and add the two new provider keys. Do not overwrite an existing `.env` with the example.

```dotenv
APIFY_API_TOKEN=your_apify_token
HUNTER_API_KEY=your_hunter_key
NEVERBOUNCE_API_KEY=your_neverbounce_v4_key
```

Git ignores `.env`. Process environment variables override the file. All three keys are required before creating an enrichment run, so missing enrichment keys do not trigger a paid scrape.

Start FastAPI from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use a **single worker**. Stop an existing backend with Ctrl+C before restarting. Restart after changing `.env`. `--reload` is optional for development; saving backend files during a job restarts the server and loses in-memory enrichment state.

In a second terminal from the repository folder:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to FastAPI on port 8000. CORS permits localhost and 127.0.0.1 frontend origins on port 5173, the idempotency header, and the download filename header. API docs: <http://localhost:8000/docs>.

On macOS/Linux, use `python3`, `.venv/bin/python`, and `npm`. Windows commands do not require virtual environment activation or PowerShell policy changes.

## Manual form workflow

1. Set the three lead-provider keys and start both servers. Conversational search additionally needs the OpenAI key described above; open the manual form below the chat for this workflow.
2. Enter **Chiropractors**, **Austin**, **Texas**, then click **Find and Enrich Leads**. This starts paid provider activity.
3. Inputs stay disabled while stages move through `pending`, `scraping`, `enriching`, `verifying`, and `exporting`. All counts come from the backend. Short stages can finish between polls.
4. The completed view shows scraped businesses, verified contacts, selected generic contacts, and businesses without a verified email. Counts refer to deduplicated companies, with unique names and domains.
5. **Download Verified Leads** creates `chiropractors_austin_texas_verified_leads.csv` with at most one selected Hunter contact per domain. Owners/CEOs are preferred, then executives, then other decision-makers, then a real generic email if no suitable person exists. No Hunter contact means zero rows for that domain; invalid emails are excluded. Columns are exactly `first name, last name, company domain, title, email, phone number, linkedin, twitter, email_status`. Rows are sorted `valid`, `catchall`, `unknown`, then `disposable`. A verification API error leaves email_status blank and appears before disposable rows. Each domain appears at most once. Phone number is Hunter's contact phone, not the business phone.
6. **Download All Results** creates `chiropractors_austin_texas_all_results.csv`, preserving every unique business including missing websites, no suitable contacts, unverified candidates, and API failures.
7. Compare both CSVs with the Apify dataset and actual provider results. Confirm separate business/contact phone numbers, actual Hunter LinkedIn fields, and the actual NeverBounce email_status values and ordering. The historical Verified Leads button/filename now includes unverified statuses as requested; only valid means verified.

Zero businesses or zero verified contacts are explicitly reported; empty exports contain headers. **Resume status check** reads the existing job after a polling error. A lost start response reuses the frontend's idempotency key, preventing duplicate jobs while the run is retained in the same process.

Live integration has **not** been validated with all four real credentials. Tests mock OpenAI and the three lead providers and never initiate paid calls. Account/model permissions, credits, plan restrictions, interpretation quality, and real results require manual verification.

## API

| Endpoint | Behavior |
| --- | --- |
| `POST /api/runs` | Accepts `niche`, `city`, `state`; returns 202 and pipeline run ID. Optional `Idempotency-Key` prevents duplicate creation while retained. |
| `GET /api/runs/{run_id}` | Returns stage, message, Apify run ID, counters, timestamps, failure reason, and download readiness. |
| `GET /api/runs/{run_id}/download?type=verified` | Compact Hunter-contact CSV after completion; invalid emails excluded. |
| `GET /api/runs/{run_id}/download?type=all` | Every unique business and enrichment outcome after completion. |

Progress fields: `businesses_scraped`, `businesses_processed`, `domains_searched`, `contacts_found`, `verified_emails`, `generic_emails_selected`, `businesses_without_contact`, `failed_enrichments`. Domains count attempted unique lookups including failures; contact counts count returned records per unique domain. Generic counts include all selected generic contacts, while the compact export includes only the selected non-invalid Hunter contact per domain. The verified_emails counter continues to mean businesses whose selected contact is valid, not the compact CSV row count.

Missing keys return 503 before work starts; bad input returns 422; active capacity returns 429; unknown/expired runs return 404; early downloads return 409. Individual business failures preserve records and do not fail the entire job.

## Selection and data quality

Owners/founders/CEOs/presidents/managing partners rank first, followed by relevant directors/executives and business management. Hunter's decision-maker classification is positive evidence, followed by confidence and useful metadata as tie-breakers. Ordinary employees do not qualify merely because an email exists. Product owner does not automatically mean business owner. Source ordering resolves ties reproducibly.

Only Hunter-returned contacts are considered. Generic priority: `info`, `contact`, `hello`, `office`, `admin`, `sales`, `support`, then other returned generic addresses. No email patterns, names, titles, numbers, or profiles are invented.

NeverBounce is the verification authority. `valid` is accepted; `invalid`/`disposable` trigger alternatives; `catchall`/`unknown` remain unverified fallbacks while other candidates are tried. Suggested corrections are recorded without substituting guessed contacts. Verification errors never become valid. Default candidate budget: four. When many people exist, the last slot is reserved for a real generic fallback. Selection stops at the first valid result and exports at most one final contact per domain. The previous extra pass verifying every Hunter contact has been removed. Shared emails have one in-flight/result cache entry per run, including errors.

Initial identity deduplication uses Place ID, CID/Maps URL, or name/address. Before Hunter or NeverBounce calls, a second pass filters duplicates by registrable domain OR company name normalized for case, whitespace, and punctuation. The first business with a usable website is preferred; retained companies have unique nonempty names and domains. Missing names/domains are not invented. Filtered source records remain under `original_business_data.duplicate_records`. All Results keeps its existing columns and provenance format, with one retained company row rather than duplicate locations. Selected company contacts explicitly state that local branch affiliation has not been established.

All Results retains its fixed snake_case columns and complete business/contact/verification provenance. The compact Hunter-contact CSV uses the nine column names specified above. Both use standard escaping, UTF-8 BOM for Excel, and formula-safe cells. All Results preserves original business JSON, selected Hunter contact JSON, search metadata/reasons, and business-selection verification attempts; extra contact-export checks do not change those rows. Missing values are blank. Formula-leading text and leading tab/newline are prefixed with an apostrophe, including `+` phone strings. Original values remain in JSON provenance cells. Status responses do not contain contact records.

## Configuration, limits, and credits

Apify's requested fixed configuration is unchanged, including 30 places per search. Only niche and location vary. Frontend polling reads local progress and does not start another actor or repeat enrichment.

| Setting | Default | Meaning |
| --- | --- | --- |
| `MAX_VERIFICATION_ATTEMPTS_PER_BUSINESS` | 4 | Candidate verification checks per retained company, allowed 1-10. |
| `MAX_HUNTER_RESULTS_PER_DOMAIN` | 10 | Contact request cap, allowed 1-100. |
| `MAX_HUNTER_PAGES_PER_DOMAIN` | 1 | Page cap, allowed 1-10; page size is at most 10. |
| `ENRICHMENT_CONCURRENCY` | 3 | Worker count, allowed 1-5. |
| `PROVIDER_MAX_RETRIES` | 2 | Additional transient attempts, allowed 0-3. |
| `PROVIDER_MIN_INTERVAL_SECONDS` | 0.25 | Per-provider request spacing within a run, allowed 0.1-10. |
| `MAX_ACTIVE_RUNS` | 1 | Run capacity, allowed 1-3; no unbounded waiting queue. |
| `MAX_STORED_RUNS` | 20 | Retained runs, allowed 3-100. |
| `RUN_RETENTION_SECONDS` | 3600 | Terminal run retention, allowed 60-86400. |
| `APIFY_POLL_INTERVAL_SECONDS` | 3 | Background actor-status interval. |
| `APIFY_WAIT_TIMEOUT_SECONDS` | 3600 | Maximum actor wait; does not abort the actor. |

Raising limits can spend more credits. Two retries mean up to three HTTP attempts per candidate: four candidates can involve up to twelve verification requests during transient failures. Only ranked candidates for the selected company contact are checked; ordinary employees and unused contacts are not bulk-verified. Duplicate email caching reduces calls. Billing after timeouts is provider-dependent; request limits are not a guaranteed bill. Request spacing is per run; retain the default single active run to avoid multiplying account traffic.

Hunter plan limits can prohibit offsets beyond the first ten results. Pagination/quota/permission failures preserve previous pages and record their reason. An unsuccessful search is not proof no company emails exist. Privacy suppression discards partial contacts for that search and never triggers guessed contacts. Search-cap truncation is recorded.

Transient HTTP 429/5xx, Hunter rate-limit 403 responses, timeouts, and NeverBounce `temp_unavail`/`throttle_triggered` responses receive bounded exponential backoff. Retry-After is respected across workers. Cooldowns above 30 seconds stop further provider requests for that run rather than retrying early. Authentication/quota failures also halt future requests to that provider; already in-flight requests may finish. Permanent errors and NeverBounce general request failures are not retried. Failure reasons omit upstream messages and request URLs.

## Tests and build

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

From `frontend/`:

```powershell
npm.cmd test
npm.cmd run build
npm.cmd audit
```

Fixtures and HTTP mock transports cover domains, missing sites, provider parsing/pagination/quota/privacy, ranking, generic fallback, alternative candidates, verification outcomes/errors, concurrent caching, partial failures, formula protection, both CSVs, progress, API downloads, idempotency, and storage bounds. A full API test uses real orchestration/provider modules with mocked Apify and HTTP responses. Frontend tests cover inputs, stages/counts, polling/cleanup, errors, idempotent retry, and both downloads. The build checks TypeScript.

## Known limitations

This is a **local, single-process MVP**. Bind to localhost. Browser-session isolation is not a production login system. Runs, exports, caches, and manual-run idempotency keys are lost on backend restart. Agent conversations, approvals and executed-version mappings survive in SQLite and do not silently restart old jobs. Oldest terminal runs are evicted at capacity; terminal runs expire after retention. Do not use multiple Uvicorn workers: they have separate stores and capacity counters.

Refreshing/closing the page stops browser polling but not the background job. Save the pipeline run ID or retrieve it through the API if needed after refresh. Shutdown stops further enrichment and waits for bounded in-flight calls; it does not abort Apify. If startup/status/dataset retrieval fails or waiting times out, check Apify Console before starting again. Scrape data remains in Apify if enrichment state is lost.

Contacts apply to a company domain, not proven branch ownership. Duplicate company names and domains are intentionally filtered, even when they represent distinct locations. Hunter confidence is not deliverability. Default searches can miss useful contacts beyond the first page. Exclusions are an explicit list and unfamiliar directories may need additions. tldextract uses its bundled suffix snapshot; update dependencies when new suffixes matter. Datasets and exports are held in memory, appropriate for this small MVP.

## Official provider references

- [Apify convenience methods](https://docs.apify.com/api/client/python/docs/concepts/convenience-methods) and [Python client reference](https://docs.apify.com/api/client/python/reference/class/ApifyClient). The existing client stays pinned to 2.5.1 with dictionary responses; current 3.x references use newer models.
- [Hunter Domain Search, authentication, errors, and pagination](https://hunter.io/api-documentation/v2#domain-search), plus [API documentation](https://hunter.io/api-documentation).
- [NeverBounce single check](https://developers.neverbounce.com/reference/single-check), [verification guide](https://developers.neverbounce.com/docs/verifying-an-email), [authentication](https://developers.neverbounce.com/reference/authentication), and [error handling](https://developers.neverbounce.com/reference/error-handling).
