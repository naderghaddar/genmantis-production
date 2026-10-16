# GenMantis — Research & Relationships

A full-stack lead research workspace built on the original React/FastAPI MVP.

- **Research advisor:** understands your offer, compares sources, researches markets and companies, checks existing leads, reviews campaign results, and prepares campaign plans.
- **Three discovery sources:** Google Maps through Apify, cited web discovery, and supplied company websites.
- **Consistent enrichment:** Hunter discovers contacts; the original selection pipeline checks them with NeverBounce. Only `valid` is verified.
- **CRM:** searchable and filterable company records, verification categories, research evidence, notes, tags, follow-ups, bulk stage changes, and CSV exports.
- **Pipeline:** drag cards through New → Qualified → Contacted → Meeting booked → Won, with accessible stage selectors.
- **Campaigns:** editable drafts, explicit start, persisted progress/results, cancellation, duplication and restart detection.
- **Accounts:** Supabase email/password sign-in with account-isolated cloud storage. A separate local workspace supports development.
- **Deployment:** Docker builds the frontend and serves it alongside the API.

## Run locally

Use Python 3.11+ and Node.js 22.12+. Preserve your existing `backend/.env` and provider keys.

```powershell
# From backend/
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# From frontend/, in a second terminal
npm.cmd ci
npm.cmd run dev
```

Open http://127.0.0.1:5173. The sidebar provides research, campaigns, CRM, pipeline and business context.

## Configuration

Copy `backend/.env.example` only if you do not already have an environment file.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Advisor and grounded web research |
| `OPENAI_MODEL` | Responses model with function calling, structured outputs and web search; default `gpt-5.4-mini` |
| `APIFY_API_TOKEN` | Google Maps discovery |
| `HUNTER_API_KEY` | Company contact discovery |
| `NEVERBOUNCE_API_KEY` | Email verification |
| `SUPABASE_URL` | Production project's API URL |
| `SUPABASE_PUBLISHABLE_KEY` | Public Supabase client key; no service-role key required |
| `ALLOW_LOCAL_WORKSPACE` | `true` for local browser-owned workspaces; **false for deployed environments** |
| `WORKSPACE_DB_PATH` | Local workspace and cloud recovery data; defaults to `backend/.data/workspace.sqlite3` |
| `RESEARCH_MAX_CALLS` | Per-research-task model-request ceiling; default 60 |
| `MAX_ACTIVE_RUNS` | Concurrent campaign capacity; default 1 |

The existing provider result, verification-attempt, retry, polling and concurrency settings remain in `.env.example`. Research can incur OpenAI web-search/model charges. Starting a campaign can also incur source, Hunter and NeverBounce charges; the review card describes bounded work rather than a guaranteed dollar cost.

## Supabase project

**Only the blank production project `cpuhytycdbthpqvevjmc` is used.** Supabase lists its name as `gemantis-production`. The app does not use `vougamed` or the separate legacy CRM database.

The checked-in migration is `supabase/migrations/202610160001_workspace.sql`. It creates `gm_workspace_records` and ownership policies. RLS requires `auth.uid() = owner_id` for reads and writes. The backend independently validates the user's bearer token.

The migration has been applied to that production project. Local settings contain its URL and publishable key. Provider secrets remain in the ignored backend environment file.

Create an account from the sidebar to use cloud storage. Confirm the account by email if required by Supabase. Local and signed-in workspaces are separate; local records are not silently moved into an account. Configure Supabase Auth site/redirect URLs and email delivery for your deployed domain.

## Working with leads

1. Add your offer, ideal customer, geography, buyer roles and exclusions in **Business profile**.
2. Ask the **Research advisor** to investigate a segment, or create a campaign directly.
3. Review the source, criteria, geography and maximum businesses; click **Start campaign**.
4. Watch real provider progress in **Campaigns**.
5. Review companies and source evidence in **Lead database**. Only NeverBounce-valid contacts receive a Verified badge.
6. Add notes and next actions, set follow-up dates, and move suitable leads through **Pipeline**.

Verification categories and sales stages are separate. A verified email does not establish purchase intent. Unknown company facts remain unknown. Already-known company domains are linked to later campaigns without repurchasing enrichment; their original verification timestamp is retained.

Default CRM export contains only verified contacts. Individual category exports preserve their actual status. CSV formula-leading cells are escaped.

## Production container

```powershell
docker compose up --build -d
```

This serves the app at http://127.0.0.1:8000, requires account authentication, and persists recovery data in a named volume. Put a TLS reverse proxy in front for public use. `GET /health` is available for readiness checks.

Run **one backend process/replica**. Campaign state and leads persist, but execution is a bounded in-process worker. A restarted campaign is marked interrupted and is not automatically repeated. Check the source provider before duplicating interrupted work. Cancellation does not forcibly abort an already-started Apify actor. Preserve the data volume for recovery if cloud storage fails mid-job.

## Validation

```powershell
# backend/
.venv/Scripts/python.exe -m pytest -q

# frontend/
npm.cmd test
npm.cmd run build
```

Tests mock paid providers. They cover original enrichment behavior, all three discovery paths converging on Hunter/NeverBounce, account ownership, campaign reservations, duplicate starts, restart handling, qualification, safe exports, advisor tool dispatch, and CRM interactions.

Validation completed: **184 backend tests and 26 frontend tests passed**, and the TypeScript/Vite production build passed. A live OpenAI smoke test returned cited web research; a second exercised source selection and campaign-draft tool dispatch without starting a paid campaign. Supabase RLS was checked with two temporary users inside a rolled-back transaction: cross-account reads and writes were rejected.

Live Apify/Hunter/NeverBounce execution and full sign-up/email confirmation have not been tested end to end. Browser visual QA was unavailable because no browser automation surface was enabled. The Docker image was not built because the local Docker daemon was unavailable. These checks remain before public release.

See [workspace architecture](docs/workspace-architecture.md) for tool contracts, data flow, limits and deployment behavior. The older chat/manual APIs remain available for compatibility and require authentication when local mode is disabled. [Legacy agent architecture](docs/agent.md) documents that earlier flow.
