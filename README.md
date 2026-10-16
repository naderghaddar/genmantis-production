# GenMantis — SEO Lead Research

GenMantis has two screens: **Research Advisor** (the landing screen) and **Lead Database**. The advisor plans and runs searches, displays progress, and recommends additional cities when a search falls short. The lead database contains named people, their checked email addresses, company evidence and CRM notes.

## Ask your agent

> Fetch me 50 dentist leads for SEO outreach from Austin, Round Rock and Cedar Park, Texas.

The agent uses the business context from your conversation, asks for missing niche/geography when necessary, and starts a bounded background search when you explicitly ask to fetch leads. Planning-only requests produce drafts with an inline start button. There is no separate campaigns, dashboard, settings or pipeline screen.

For Google Maps, Apify requests **70 businesses per location**. Hunter finds relevant named decision-makers; NeverBounce checks their emails. Multiple people can qualify at one company. Business counts do not count toward the lead target. The worker continues through the supplied cities until the requested number of new people is reached or the cities are exhausted. It stops before starting another city once the target is met.

A lead uses this workspace's policy:

- A named person with an email from Hunter.
- NeverBounce returned **valid**, **catchall**, or **unknown**.
- Generic inboxes, invalid/disposable addresses, missing results and verification errors do not count.
- Emails are deduplicated case-insensitively across businesses, locations and existing leads. Previously saved people do not count again as new leads.

The exact NeverBounce status is shown in the database and exports. Catch-all and unknown are accepted under this product policy; they are not claims of confirmed deliverability.

If a 100-lead search across three cities finds 30 people, the advisor shows **30/100 found, 70 remaining**, city-level results, and cited recommendations for similar cities. Recommendations are not scraped until the user asks to continue. A provider interruption is reported separately from an exhausted search. Partial saved leads remain available.

## Run locally on Windows

Use Python 3.11+ and Node.js 22.12+. Preserve your existing `backend/.env` and API keys.

```cmd
cd C:\Users\nader\genmantis-production\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```cmd
cd C:\Users\nader\genmantis-production\frontend
npm.cmd ci
npm.cmd run dev
```

Open http://127.0.0.1:5173. Restart the backend after changing Python code or `.env` (or use `--reload` during development).

## Configuration and persistence

The existing `backend/.env.example` documents provider configuration. Required services are OpenAI (advisor/research), Apify (Maps), Hunter (people) and NeverBounce (email checks). `OPENAI_MODEL` chooses the Responses API model; the model must support function calling, web search and structured output. Model and provider work incur their respective account charges.

Only production Supabase project **`cpuhytycdbthpqvevjmc`** (`gemantis-production` in Supabase) is configured. Vougamed and the legacy CRM project are not used. The existing `gm_workspace_records` table and its ownership RLS policies store account records. This update needs no SQL migration. Provider credentials remain in the ignored backend environment file.

Supabase email/password sign-in is available through the account control. Local and cloud workspaces are separate. `ALLOW_LOCAL_WORKSPACE=false` requires authentication for production. Keep the server's local recovery volume even when using cloud storage.

## Bounds and execution

- Up to 1,000 requested people and 30 explicitly supplied cities per search.
- Up to 70 source businesses per city; the provider can return fewer.
- Hunter's configured page/result limits bound contact discovery. All suitable named people returned within those limits are checked until the lead target is reached.
- Company research uses `RESEARCH_MAX_CALLS` (default 60); shortfall city research reserves two additional model requests. Unsupported evidence stays unknown.
- Run one backend process/replica. Execution capacity uses `MAX_ACTIVE_RUNS` (default 1).
- Cancellation stops after the current provider request and does not forcibly abort an existing Apify actor. Restarted active work is marked interrupted and is never silently repeated.

Web discovery and supplied websites remain available as advisor tools, also using Hunter and NeverBounce. The removed manual legacy UI is not part of the application navigation; older API contracts remain for compatibility.

## Checks and deployment

```cmd
cd backend
.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm.cmd test
npm.cmd run build
```

Tests cover all accepted/rejected email outcomes, named-person rules, multiple contacts per company, duplicate suppression, stopping at the target, cancellation, city shortfalls and recommendations, agent dispatch, exports and two-screen navigation. Provider calls are mocked in automated tests. A live model dispatch check uses a mocked worker so it never starts paid scraping or enrichment.

`docker compose up --build -d` builds the frontend and serves it with FastAPI at http://127.0.0.1:8000. Configure TLS, Supabase Auth URLs and email delivery before public deployment. Browser visual QA and live paid-provider integration still require validation in an enabled environment.

See [workspace architecture](docs/workspace-architecture.md) for implementation details.
