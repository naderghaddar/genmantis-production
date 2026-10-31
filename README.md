# GenMantis

GenMantis has two screens: **Find leads** and **Lead database**. Searches use a simple form and CSV import. There are no active AI advisor, conversation, web-research, or recommendation endpoints. OpenAI is not required or called by the application.

## Search workflow

1. Enter one niche/keyword and up to 500 cities with their states/regions. Optionally specify inclusive minimum and maximum organic Maps ranks per city.
2. Alternatively import a CSV, review the resulting editable city rows, and click **Start search**. Import replaces the current city rows; it does not start scraping.
3. Run Apify actor `nwua9Gu5YrADL7ZDj` for each city **sequentially**, using one keyword and location per run. The selected business limit is 100?500 per city (default 100). There are no automatic deeper passes or extra cities.
4. After **every city finishes**, normalize company domains and retain one qualifying company result per domain across the whole search. Only blank website fields are omitted. Social/directory domains, IP addresses, non-HTTP schemes, unknown suffixes, and malformed nonblank values are retained. Use the registered domain when available, otherwise the hostname, otherwise the original field value as the Hunter lookup/deduplication key. A retained value does not guarantee Hunter will return contacts; shared directory/social domains are still deduplicated together. Rank filters are applied within each city's query context before domain deduplication; missing organic rank evidence does not satisfy a requested rank filter.
5. Process unique domains **one at a time**. Hunter searches personal decision-maker emails first, then personal emails if fewer than two contacts were selected. Each query requests at most two results. Names are optional. Generic contacts, malformed emails, and emails outside the company domain are excluded. Hunter's explicit personal/generic classification takes precedence; known shared-inbox prefixes are used only when that classification is missing.
6. Select **at most two unique people per domain**, then check their emails through NeverBounce sequentially. There are no replacement checks when an email fails. Existing workspace emails are skipped before verification.
7. Immediately save contacts with NeverBounce `valid`, `catchall`, or `unknown` results to the existing database. Other outcomes are not saved. Proceed to the next domain until every domain has been processed; there is no overall lead target.

A duplicate domain retains one company, rather than discarding every occurrence of that company. Domain deduplication is across the current search; saved-email deduplication also covers previous searches. The two-contact limit applies per domain in this search, not as a lifetime database cap.

The progress cards show cities, scraped businesses, removed duplicate domains, processed domains, email checks, and saved leads. Existing CRM records remain available. Stop requests wait for the current request and attempt to abort an active Apify actor. Provider or storage interruptions retain saved leads and report failure. Searches are not automatically resumed after backend restarts.

## CSV format

```csv
city,state,rank
Spokane,Washington,100
Boise,Idaho,100
```

`rank` is an inclusive **maximum** organic Maps rank. For a range, use:

```csv
city,state,min_rank,max_rank
Spokane,Washington,11,100
Boise,Idaho,,
```

Blank ranks mean no rank restriction. Headers are case-insensitive; quoted CSV fields and UTF-8 BOM are supported. Conflicting rank settings for repeated cities are rejected. The form includes a downloadable template. The CSV maximum is 500 KB / 500 rows.

## Local development

Use Python 3.11+ and Node.js 22.12+. Preserve `backend/.env` and its provider keys.

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open http://127.0.0.1:5173. Restart the backend after Python changes, or use `--reload` for development. The frontend proxies `/api` to the backend. `npm.cmd run build` compiles the frontend; it does not run tests.

## Configuration and storage

Required providers: Apify, Hunter, NeverBounce. See `backend/.env.example`. Credentials remain server-side. Existing OpenAI environment variables can be removed; they are unused by the running application.

Signed-in accounts use the existing Supabase `gm_workspace_records` table and ownership policies. Local workspaces use SQLite. No migration is needed. `ALLOW_LOCAL_WORKSPACE=false` requires sign-in. Keep the local recovery volume even when using cloud storage. Local and cloud workspaces remain separate.

## API

- `POST /api/workspace/cities/import` with `{ "csv": "city,state,rank\nSpokane,Washington,100" }`: validate and preview imported cities without starting providers.
- `POST /api/workspace/campaigns`: create a draft with the body below.
- `PUT /api/workspace/campaigns/{id}?version={version}`: update a draft with the same shape.
- `POST /api/workspace/campaigns/{id}/start` with `{ "version": 1 }`: start the current draft version.
- `POST /api/workspace/campaigns/{id}/cancel`: request cancellation.
- `GET /api/workspace`: campaigns, progress and saved leads; the UI polls every four seconds while a search is active.
- `GET /api/workspace/config`: authentication settings and provider availability.
- `PATCH /api/workspace/leads/{id}` and `PATCH /api/workspace/leads/bulk`: CRM edits.
- `DELETE /api/workspace/leads/{id}`: permanently delete one workspace lead.
- `DELETE /api/workspace/leads/bulk` with `{ "ids": ["lead-id"] }`: permanently delete up to 100 selected leads. Both deletion endpoints are owner-scoped and clear local recovery copies as well as cloud/local records. Repeating a deletion is safe. Historical search counts remain unchanged; future searches may find deleted emails again.
- `GET /api/workspace/leads/export?category=verified&campaign_id={id}`: CSV export; the campaign filter is optional.

```json
{
  "niche": "chiropractor",
  "locations": [
    { "city": "Spokane", "state": "Washington", "min_rank": null, "max_rank": 100 },
    { "city": "Boise", "state": "Idaho", "min_rank": null, "max_rank": null }
  ],
  "places_per_city": 100
}
```

The first Apify input includes `searchStringsArray: ["chiropractor"]`, `locationQuery: "Spokane, Washington"`, and `maxCrawledPlacesPerSearch: 100`. Apify contact enrichment stays disabled. Rank is filtered against returned evidence locally, not sent as an unsupported actor field.

External calls use Apify actor runs/datasets, `GET https://api.hunter.io/v2/domain-search`, and `GET https://api.neverbounce.com/v4.2/single/check`. Authenticated cloud storage uses Supabase Auth and REST.

The old `/api/agent`, `/api/workspace/threads`, `/api/runs`, and `/api/scrapes` routes are no longer registered. Historical saved campaigns and leads are retained; old advisor drafts cannot be started.
