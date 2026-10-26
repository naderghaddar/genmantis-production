# Investigating company-to-lead yield

New campaign runs emit INFO logs on `uvicorn.error.lead_funnel`. Each message
starts with `lead_funnel` followed by a JSON object. Normal Uvicorn INFO logging
includes these events; no debug flag or provider calls are needed to enable them.
Restart the backend with the updated code before starting a new campaign.

For Docker Compose, capture the next run with:

```powershell
docker compose logs --follow --since 5m genmantis 2>&1 | Select-String 'lead_funnel' | Tee-Object -FilePath lead-funnel.log
```

For a locally launched backend, the same events appear in its console. Filter by
`campaign_id` to isolate a run, then by `domain` to follow one company. Hunter's
page and filter events share the campaign ID and domain. `company_index` identifies
a company's processing attempt; city and round identify the discovery pass.
Logs omit contact names, email addresses, credentials, raw provider responses,
and exception messages. Company domains and campaign IDs are included.

| Event | What to inspect |
| --- | --- |
| `campaign_started` | Actual policies, existing-email count, provider pagination limits and research budget |
| `discovery_batch` | Source records versus unique places versus unique companies |
| `company_no_domain` | `no_website`, `invalid_website`, or `excluded_domain` |
| `company_repeated_domain` | Company was already encountered in this campaign |
| `company_at_saved_limit` | Existing saved contacts consumed the company cap |
| `company_rank_excluded` | Missing organic evidence versus observed rank outside the requested range |
| `company_research_error` | HTTP status, calls used and whether the research budget was exhausted |
| `company_research_unknown` / `company_research_excluded` | Evidence or fit prevented enrichment |
| `hunter_page_result` | Returned records, parsed contacts, provider total, and truncation |
| `hunter_page_error` | Safe provider error code |
| `hunter_filter_result` | Filter, ranked versus eligible contacts, stop/broaden decision, filters left untried |
| `company_contacts` | Generic contacts, contacts without qualifying roles, ranked people without names |
| `company_no_eligible_contact` | Empty Hunter response versus contacts failing the person/role policy |
| `candidate_duplicate_email` | Candidate already exists or was encountered earlier |
| `candidate_verification` | Exact NeverBounce outcome and safe failure code |
| `candidate_insert_conflict` | Storage found an already-saved contact |
| `lead_saved` | Accepted new lead |
| `company_enrichment_finished` | Candidate count, checks, saved leads and whether target/company cap was reached |
| `campaign_error` / `campaign_finished` | Exception class, final status, stop reason, progress and event counts |

An especially useful signal is `hunter_filter_result` with
`decision=stop_ranked_contacts`, `eligible_people=0`, and `remaining_filters>0`:
discovery stopped even though the campaign cannot use any returned contact.
If eligible candidates exist but no lead is saved, inspect duplicate, verification,
and storage events for that domain.

Campaign records also retain `diagnostics.version`, `diagnostics.counts` (event
totals), and `diagnostics.reasons` (reason totals by event). They are available in
the existing `GET /api/workspace` response under each campaign. Detailed domain
events live in server logs; they are not added to the frontend. Older campaigns
cannot be reconstructed from this instrumentation.

These counters have different units: discovery records, company processing
attempts, Hunter filter/page requests, contact candidates, and saved leads.
Do not sum them together as a single funnel. Repeated city passes can make
processing attempts exceed distinct discovered companies. Cancellation or a
provider/storage failure can interrupt a company before its finished event.

The diagnostic tests use simulated HTTP responses through the actual Hunter
parser and fallback implementation. A 300-company comparison produces 12 versus
240 leads by changing how many owner records contain a person's name. This
demonstrates a possible low-yield mechanism and the effect of fixture completeness;
it does not establish the cause or expected yield of a live run.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_lead_diagnostics.py -q
```
