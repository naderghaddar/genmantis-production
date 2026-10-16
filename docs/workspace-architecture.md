# GenMantis research workspace

## Application flow

The React application contains Overview, Research advisor, Lead database, Pipeline, Campaigns, Business profile, and Sources & integrations. Hash navigation preserves deep links without a separate router service. Supabase Auth provides email/password registration and login; email confirmation follows the project's configuration. The backend verifies bearer tokens against Supabase Auth before trusting account identity. A short cache avoids repeated validation on polling.

For signed-in accounts, `WorkspaceStore` uses the Supabase REST API with that user's token. RLS independently restricts every record to `auth.uid()`. No service-role key is exposed or required. Local development can use a browser-owned SQLite workspace. Local records are separate from cloud accounts and are not automatically imported at login.

The only Supabase project configured for this implementation is `cpuhytycdbthpqvevjmc` (`gemantis-production`, the blank production project). Migration: `supabase/migrations/202610160001_workspace.sql`. Other connected projects are outside this application's scope.

## Research agent

`ResearchAgent` uses a bounded Responses API tool loop. The business profile and recent conversation provide context. Six tools are available:

- `source_capabilities`: discovery coverage, fields, configuration, and limits.
- `research_market`: live web search with source citations.
- `research_company`: research restricted to a supplied public company's domain.
- `search_crm`: inspect relevant company records, assessments, and user notes.
- `review_campaigns`: inspect real campaign outcomes before recommending revisions.
- `propose_campaign`: validate and persist a draft; never executes the campaign.

Each message allows five tool executions and a final response turn. Parallel tool calls are disabled. Threads retain tool activity, citations, associated drafts, and token usage. A repeated message ID returns the saved result. An interrupted model turn produces an explicit response and preserves prepared drafts. Validation failures return field-specific errors to the model for correction, without including raw user input. Users can continue the conversation to revise the strategy. Model outputs are not treated as permission to execute paid provider work.

Tools do not expose environment variables, arbitrary code execution, filesystem access, or outreach sending. Website content and CRM notes are untrusted data. Company research uses OpenAI's hosted web search rather than backend fetching arbitrary URLs. Citation and company-domain checks discard unsupported discoveries. The advisor does not have direct access to Supabase administrative tools.

## Discovery and qualification

Three executable sources:

1. Google Maps: the existing Apify actor with its fixed 30-place ceiling and observed ranking checks.
2. Web discovery: live OpenAI web search, followed by structured company extraction. A candidate's official website must have appeared in search sources. This is grounded discovery, not an arbitrary scraper generator.
3. Company websites: a supplied list of at most 30 websites, followed by optional company research and contact enrichment.

Website research records a summary, fit assessment, reasons, unknowns, and cited evidence. A company is excluded only when the assessment establishes poor fit or an explicit exclusion; absence of evidence stays unknown. When research fails, the CRM marks fit unknown and retains the limitation. Qualification and email validity are separate.

The current research loop improves strategy across conversation turns; it does not silently launch additional campaigns or expand geography/budgets. Source cost estimates are expressed as bounded work, not invented dollar prices. A campaign uses at most `RESEARCH_MAX_CALLS` model requests; defaults to 60. A researched company normally needs two requests, so the final companies in a maximal campaign may remain unassessed when the budget is exhausted.

## Invariant contact pipeline

All discovery paths converge on the existing `HunterService`, `VerificationCache`, and `enrich_lead` candidate selection. No model-created email is accepted. Every selected Hunter contact receives a NeverBounce outcome. Only `valid` sets `verified=true`. Catchall, unknown, invalid, disposable and verification errors remain unverified. Companies without Hunter contacts remain no-contact records. Excluded companies do not consume enrichment credits.

The CRM categories are Verified, Needs review, No contact, and Excluded. Sales stages are independent: New, Qualified, Contacted, Meeting booked, Won, Lost and Archived. The API restricts edits to stage, tags, notes, next action and follow-up; users cannot override provider outcomes through these routes. Verified-only export additionally checks the stored NeverBounce result, and CSV cells are escaped against formula injection. All-category export retains outcomes explicitly.

Companies are deduplicated by domain/name within discovery and by domain across a workspace. Existing CRM records are linked to a later campaign without buying another enrichment. Their original verification timestamp remains unchanged; reuse does not imply a fresh verification. Contact freshness/reverification is a future extension.

## Execution and persistence

Campaigns are draft/versioned. Start requires the current version, validates provider configuration, and durably records approval before submitting background work. Duplicate starts return the existing campaign. Edits are allowed only on drafts. Campaign progress, source run ID, per-company results, usage, and activity are persisted.

The executor is bounded by `MAX_ACTIVE_RUNS`. Cancellation stops after the current provider request; an already-started Apify actor is not forcibly aborted. After a process restart, old active campaigns are marked interrupted and never automatically repeated. Partial leads remain available. A cloud failure saves recovery records and an outbox locally; authenticated requests attempt synchronization after access is restored. Retain the local data volume even with cloud storage.

Run one backend process/replica. Execution locks and active capacity are in-process. The storage is durable, but this release is not a distributed task queue and does not resume partially completed provider operations automatically. This avoids accidentally repeating paid source jobs. Moving to multiple replicas requires a database lease/queue and provider-aware resumption.

## Deployment and validation

Docker serves the built React app and FastAPI from one origin. `ALLOW_LOCAL_WORKSPACE=false` requires authentication on workspace and legacy API routes. Place a TLS reverse proxy in front for internet use. Configure Supabase Auth site/redirect URLs for the deployed origin and appropriate email delivery before public registration.

Automated backend tests cover the original provider behavior plus ownership, persistence, reservations, restart handling, all-source Hunter/NeverBounce convergence, exclusion before enrichment, grounded URL constraints, advisor idempotency, cloud request identity, and exports. Frontend tests cover category filters, draft creation, profile updates, and CRM edits. External provider calls are mocked in the suites; these tests do not establish live paid-account access, research quality on every brief, or actual lead yield.

Suggested quality evaluation: maintain reviewed business briefs and company examples. Measure target selection, source compatibility, evidence support, irrelevant-company rate, verified-contact yield, requests per accepted lead, and whether the advisor revises weak hypotheses. Store explicit user feedback in CRM notes/stages for retrieval; no automatic model training occurs.
