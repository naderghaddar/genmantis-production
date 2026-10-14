# Conversational assistant architecture

The existing lead providers, contact ranking, provider limits, one-contact-per-domain policy and two download routes remain. Chat prepares a plan and invokes that pipeline after explicit approval; it does not replace provider services.

## Implementation files

- `backend/app/models/agent_schemas.py`: strict model output, messages, plans, versions, usage and API views.
- `backend/app/agents/system_prompt.py`: concise conversation behavior, location/rank semantics, and capability limits.
- `backend/app/services/openai_service.py`: official SDK Responses structured parsing, conversation chaining and function-call turns.
- `backend/app/services/search_plan_service.py`: apply only changed fields, normalize US state names and block unsupported qualifications.
- `backend/app/services/conversation_store.py`: small SQLite repository, browser ownership, expiry and operation locks.
- `backend/app/agents/tool_registry.py`: allowlisted strict function schema and server-side execution checks.
- `backend/app/agents/lead_agent.py`: conversation, edit/approval/version lifecycle, two-turn tool loop and grounded job summaries.
- `backend/app/api/agent_routes.py`: session cookie and typed chat/confirmation routes.
- `backend/app/services/qualification_service.py`: source rank validation and pre-enrichment qualification.
- `frontend/src/components/AgentChat.tsx`, `SearchConfirmation.tsx`, `AgentRunProgress.tsx`, and `services/agentApi.ts`: chat, validated plan, real progress and existing downloads. The manual LeadScraper stays accessible.

## OpenAI requests and memory

Configure OPENAI_API_KEY and OPENAI_MODEL (default `gpt-5.4-mini`). Use a model your API project can access that supports Responses function calling and structured outputs. The SDK is pinned to 3.31.0. No OpenAI key is put in Vite environment variables.

`responses.parse(..., text_format=AgentInterpretation)` interprets a user turn. The current validated plan is supplied separately. Only explicitly changed fields are applied, so an incomplete model response cannot erase unrelated established preferences. Ordinary chat exposes no function tools and sets tool_choice=none. Required fields are niche, one concrete US city and state; optional size/revenue/extra qualifications are retained but cannot be silently executed. No population data or live browser tool exists; suggested cities are examples, not claims of population or market demand.

Responses are chained through previous_response_id with store=true. Stable instructions are supplied on every request. When starting a fresh chain, bounded recent message history and the authoritative current plan restore context. If a post-tool model follow-up fails, the job remains recorded and the next user turn starts a fresh chain, avoiding an unfulfilled tool-call chain. OpenAI-side response storage follows project/API data policies. Only conversation text, plan parameters and lightweight function outputs are sent; provider keys, CSVs and lead/contact datasets are excluded.

SQLite defaults to `backend/.data/agent.sqlite3`, with optional AGENT_DB_PATH. ConversationStore isolates persistence for later replacement. There is no PostgreSQL migration or distributed queue. Up to 100 conversations are retained, expiring after 24 hours. Conversation creation, restoration and progress polling do not call OpenAI.

## Confirmation and execution

The confirmation card uses validated backend plan fields. Start Lead Search approves an exact ID/version. Edit Search advances the version and invalidates approval. Changing parameters also invalidates the old version. A typed yes, tool arguments, or prompt injection is not authorization. A running job retains its original parameters when a new draft is edited.

After approval, Responses is asked for the registered start_lead_generation function. Strict schema has no additional properties, all fields required, nullable rank bounds, and max_leads in 1..30. Python checks ownership, current approved version, actual request validation, exact parameter equality, provider configuration, capacity and existing execution state before dispatching RunManager.start directly. The function returns only job ID/status/message. It does not wait for the pipeline.

The idempotency key is plan ID plus version. Execution is reserved in SQLite before calling the run manager and the job ID is saved immediately after creation, before model follow-up. Duplicate confirmations reuse the same recorded job. Uncertain interrupted reservations block automatic re-execution: check Apify Console, then explicitly prepare/review a new plan version if appropriate. Model failure after a job starts cannot trigger a second job. Parallel calls are disabled and the loop allows at most one executed function plus one function-output response turn. Additional/unknown/malformed calls are rejected.

Session ownership uses a random HttpOnly, SameSite=Strict browser cookie; only its hash is persisted. Agent conversations/plans and new run/download access are checked against it. Source-run ownership is retained so a raw legacy download cannot bypass it. Retain cookies in API clients. Clearing cookies loses access. This local isolation is not a user account or production authentication system; keep one Uvicorn worker bound to localhost.

## Ranking evidence and limits

The public actor build schema at `https://api.apify.com/v2/acts/compass~crawler-google-places/builds/default` was inspected without starting a job. Build 0.14.770, ID B7ybnATEIXjudDHFs, defines rank as a one-based position in search results. The saved minimal fixture is `backend/tests/fixtures/apify_rank_schema.json`; source field descriptions are included. The actor's README shows null rank/context for direct-place inputs.

After identity/name/domain deduplication, qualification accepts a positive integer rank only with nonempty searchString, a Google Maps search-page URL and isAdvertisement=false. Missing/ad/direct-detail/unreliable observations cannot match a constrained search. Search strings, searchPageUrl, searchPageLoadedUrl, advertisement status and reported ranks are retained. Ratings, reviews and row order are never used as rank proxies.

Across multiple source observations, use the best (lowest) valid reported rank. Observations at 5 and 25 therefore do not establish that a company is outside the top 20. Query and map-area context remain attached; there is no universal citywide rank claim. Ads are excluded, and reported positions are not renumbered after excluding them.

Only qualified companies go to Hunter/NeverBounce. max_leads caps enrichment after qualification, at most 30. The actor's existing fixed 30-place limit remains unchanged; only niche/location are dynamic. A request for five companies outside the top 20 examines up to 30 source places and enriches at most five matches. A rank constraint beyond the source cap can produce no matches; no additional city searches or hidden limit increases occur.

All Results preserves excluded companies and original source data, with enrichment_status=filtered_out and a filter reason. Its existing provenance stays, with google_maps_rank, ranking_evidence and filter_reason appended. The compact contact export retains its exact nine columns, one selected contact per domain, status order and invalid-email exclusion. A run with no supported ranking matches completes without enrichment and reports a warning.

## Costs, failures, and local limits

Messages are limited to 2,000 characters; a conversation permits 40 user turns, 80 model requests, and 100,000 reported input/output tokens. Output limits are 2,500 tokens for interpretation and 1,800 per tool turn. Calls use 30-second timeouts and at most one SDK retry. Usage/request attempts are recorded when available; these are safeguards, not a guaranteed bill. Retrying a successful message ID returns saved state without repeating the model call. Concurrent actions on one conversation return 409 until the current action finishes.

Missing keys, unsupported model access, OpenAI errors, stale versions, unavailable jobs and provider failures produce explicit safe errors. No provider exception bodies or credentials are returned. Progress and completion summaries come from backend metrics, with no additional model calls. No fake progress or results are generated.

Conversation state and executed versions survive restart; in-memory jobs and CSV bytes do not. Restoring a conversation with an unavailable executed job reports the problem rather than rerunning it. Check Apify Console before creating a new paid search. Existing background cancellation semantics remain: a server shutdown does not abort an already-started Apify actor.

## Testing and live checklist

Use the backend pytest and frontend test/build commands in README.md. All model/provider responses are mocked. Tests cover multi-turn updates, missing information, ranking translation/state, unsupported qualifications, typed approval rejection, strict tool schemas, exact-version confirmation, duplicate calls, stale plans, ownership, persistence/expiry, budget limits, OpenAI failures, post-start failures, unknown ranks, pre-enrichment filtering, progress, and downloads.

Live integration is unverified until you configure all four provider credentials. These manual steps may incur charges:

1. Install updated requirements, add OPENAI_API_KEY/OPENAI_MODEL, and restart the single-worker backend and Vite.
2. Ask for SEO clients; verify useful follow-up questions and no source job.
3. Supply chiropractors, Austin/Texas and outside the top 20 over several turns. Check minimum rank 21 and the 30-business ceiling.
4. Change to Dallas and check unrelated fields survive. Edit/reject the plan before running it.
5. Click Start Lead Search once. Verify a single Apify start and enrichment only for qualified companies.
6. Observe actual counts and download both CSVs. Check statuses, source evidence and excluded rows.
7. Refresh to restore chat; try another browser session to verify ownership isolation. Test the unchanged manual form separately.

The mock tests validate application behavior and wiring; they cannot establish live model interpretation quality, provider access, real ranking availability, or paid-account limits. Browser visual verification remains manual when browser automation is unavailable.

## Official references

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Default model capabilities](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- [Apify actor README](https://apify.com/compass/crawler-google-places)
- [Public actor build schema](https://api.apify.com/v2/acts/compass~crawler-google-places/builds/default)
