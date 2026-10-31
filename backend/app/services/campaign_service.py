import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock
from uuid import uuid4

import httpx
from apify_client import ApifyClient
from fastapi import HTTPException

from app.models.leads import Lead
from app.models.schemas import ScrapeRequest
from app.models.workspace import now, new_id
from app.models.search import SearchPlan
from app.services.apify_service import ApifyService, build_actor_input
from app.services.business_service import normalize_business
from app.services.domain_service import extract_domain
from app.services.contact_selector import decision_tier
from app.services.lead_diagnostics import emit
from app.services.lead_policy import ACCEPTED_RESULTS
from app.services.hunter_service import HunterService
from app.services.neverbounce_service import NeverBounceService
from app.services.provider_http import ProviderHTTP
from app.services.qualification_service import qualify

ACTIVE = {"queued", "discovering", "enriching", "researching", "recommending"}


class CampaignService:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.process_id = uuid4().hex
        self.executor = ThreadPoolExecutor(max_workers=settings.max_active_runs, thread_name_prefix="campaign")
        self.jobs: dict[str, Event] = {}
        self.lock = RLock()
        self.closed = False

    def create(self, identity, plan: SearchPlan):
        if len(self.store.list(identity, "campaign")) >= 500:
            raise HTTPException(429, "Workspace search limit reached.")
        campaign = {"id": new_id(), "plan": {**plan.model_dump(), "name": plan.niche, "source": "google_maps"},
            "version": 1, "status": "draft", "workflow": "sequential-v1", "created_at": now(),
            "message": "Ready to search cities in order.", "events": [], "locations": [], "lead_ids": [],
            "progress": {"scraped": 0, "discovered": 0, "processed": 0, "verified": 0,
                "duplicates": 0, "checked": 0, "cities_completed": 0, "cities_total": len(plan.locations),
                "review": 0, "excluded": 0, "reused": 0, "rejected": 0, "no_contact": 0, "verification_errors": 0},
            "warnings": []}
        return self.store.save(identity, "campaign", campaign)

    def update_plan(self, identity, campaign_id, plan: SearchPlan, version):
        with self.store.operation_lock(identity.owner):
            campaign = self.store.get(identity, "campaign", campaign_id)
            if campaign["status"] != "draft" or campaign["version"] != version:
                raise HTTPException(409, "Only the current draft can be edited.")
            campaign.update(plan={**plan.model_dump(), "name": plan.niche, "source": "google_maps"},
                version=version + 1, workflow="sequential-v1")
            campaign["progress"]["cities_total"] = len(plan.locations)
            return self.store.save(identity, "campaign", campaign)

    def start(self, identity, campaign_id, version):
        with self.lock, self.store.operation_lock(identity.owner):
            campaign = self.store.get(identity, "campaign", campaign_id)
            if campaign["version"] != version:
                raise HTTPException(409, "The search changed. Refresh and try again.")
            if campaign["status"] != "draft":
                return self.recover(identity, campaign)
            if campaign.get("workflow") != "sequential-v1":
                raise HTTPException(409, "Create a new search using the city form. Old advisor drafts cannot be started.")
            if self.closed or len(self.jobs) >= self.settings.max_active_runs:
                raise HTTPException(429, "Another search is running. Wait for it to finish.")
            if any(item["id"] in self.jobs for item in self.store.list(identity, "campaign")):
                raise HTTPException(409, "This workspace already has an active search.")
            missing = [name for name, key in [("Apify", self.settings.apify_token),
                ("Hunter", self.settings.hunter_key), ("NeverBounce", self.settings.neverbounce_key)]
                if not key or key == "your_token_here"]
            if missing:
                raise HTTPException(503, "Configure " + ", ".join(missing) + " before starting a search.")
            campaign.update(status="queued", process_id=self.process_id, started_at=now())
            self.store.save(identity, "campaign", campaign)
            cancel = self.jobs[campaign_id] = Event()
            try:
                self.executor.submit(self._run, identity, campaign, cancel)
            except Exception:
                self.jobs.pop(campaign_id, None)
                campaign.update(status="failed", message="Unable to schedule search. No provider work was started.")
                self.store.save(identity, "campaign", campaign)
                raise HTTPException(503, campaign["message"]) from None
            return campaign

    def recover(self, identity, campaign):
        if campaign["status"] in ACTIVE and campaign.get("process_id") != self.process_id:
            campaign.update(status="interrupted", message="The backend restarted. Saved leads are retained; this search was not automatically restarted.")
            self.store.save(identity, "campaign", campaign)
        return campaign

    def cancel(self, identity, campaign_id):
        self.store.get(identity, "campaign", campaign_id)
        with self.lock:
            if campaign_id in self.jobs:
                self.jobs[campaign_id].set()
                return {"requested": True, "message": "Stopping after the current provider request."}
        return {"requested": False, "message": "This search is not running."}

    def _save(self, identity, campaign, status=None, message=None):
        if status:
            campaign["status"] = status
        if message:
            campaign["message"] = message
            campaign["events"].append({"at": now(), "message": message})
            campaign["events"] = campaign["events"][-80:]
        try:
            self.store.save(identity, "campaign", campaign)
        except HTTPException:
            self.store.recovery_save(identity, "campaign", campaign)
            raise

    def _diagnose(self, campaign, event, **fields):
        message = fields.pop("message", event.replace("_", " "))
        level = fields.pop("level", "info")
        counts = campaign.setdefault("diagnostics", {"version": 2, "counts": {}})["counts"]
        counts[event] = counts.get(event, 0) + 1
        sequence = campaign["diagnostics"].get("sequence", 0) + 1
        campaign["diagnostics"]["sequence"] = sequence
        # Only explicit diagnostic fields are recorded: never raw provider responses,
        # request headers, credentials, contact names or email addresses.
        entry = {"id": sequence, "at": now(), "event": event, "level": level,
            "message": message, "domain": fields.get("domain"), "details": fields}
        campaign.setdefault("debug_log", []).append(entry)
        campaign["debug_log"] = campaign["debug_log"][-500:]
        emit(event, campaign_id=campaign["id"], **fields)

    def _hunter_diagnostic(self, identity, campaign, event, **fields):
        self._diagnose(campaign, event, **fields)
        # Flush before a blocking provider call and after its selection/error result,
        # so the four-second UI poll can show which request is in flight.
        if event in {"hunter_query_started", "hunter_people_filter", "hunter_page_error"}:
            self._save(identity, campaign)

    @staticmethod
    def _check_cancel(cancel):
        if cancel.is_set():
            raise InterruptedError

    def _discover(self, identity, campaign, plan, location, cancel):
        import time
        apify = ApifyService(ApifyClient(self.settings.apify_token, max_retries=0, timeout_secs=30))
        request = ScrapeRequest(niche=plan.niche, city=location.city, state=location.state)
        payload = build_actor_input(request)
        payload["maxCrawledPlacesPerSearch"] = plan.places_per_city
        local = {**location.model_dump(), "status": "discovering", "discovered": 0,
            "processed": 0, "leads": 0, "business_limit": plan.places_per_city}
        campaign["locations"].append(local)
        self._save(identity, campaign, "discovering",
            f"Searching city {len(campaign['locations'])}/{len(plan.locations)}: {location.city}, {location.state}.")
        self._diagnose(campaign, "apify_request", message=f"Starting Apify for {location.city}, {location.state}.", actor_input=payload)
        self._save(identity, campaign)
        self._check_cancel(cancel)
        scrape = apify.start(request, business_limit=plan.places_per_city)
        campaign["apify_run_id"] = local["apify_run_id"] = scrape.run_id
        campaign.setdefault("apify_run_ids", []).append(scrape.run_id)
        self._diagnose(campaign, "apify_started", message="Apify run created; waiting for results.", run_id=scrape.run_id)
        self._save(identity, campaign)
        deadline = time.monotonic() + self.settings.apify_wait_timeout
        while scrape.status == "running":
            stopped = cancel.wait(self.settings.apify_poll_interval)
            timed_out = time.monotonic() > deadline
            if stopped or timed_out:
                try:
                    apify.abort(scrape.run_id)
                except Exception:
                    campaign["warnings"].append("Apify abort could not be confirmed; check the actor run in Apify.")
                    self._diagnose(campaign, "apify_abort_failed", level="warning", message="Could not confirm Apify abort.", run_id=scrape.run_id)
                if stopped:
                    raise InterruptedError
                raise RuntimeError("Apify wait timed out")
            scrape = apify.status(scrape.run_id)
        self._check_cancel(cancel)
        if scrape.status != "succeeded":
            raise RuntimeError("Apify discovery failed")
        items = apify.results(scrape.run_id)[:plan.places_per_city]
        local.update(status="completed", discovered=len(items))
        campaign["progress"]["scraped"] += len(items)
        campaign["progress"]["cities_completed"] += 1
        self._diagnose(campaign, "city_scraped", message=f"{location.city}, {location.state}: received {len(items)} businesses.",
            city=location.city, state=location.state, businesses=len(items))
        self._save(identity, campaign)
        return items

    def _run(self, identity, campaign, cancel):
        progress = campaign["progress"]
        try:
            plan = SearchPlan.model_validate({key: campaign["plan"][key] for key in ("niche", "locations", "places_per_city")})
            index = self.store.lead_index(identity)
            seen_emails = set(index.emails)
            self._diagnose(campaign, "campaign_started", message=f"Search started: {len(plan.locations)} cities; {len(seen_emails)} saved emails loaded for duplicate checks.",
                cities=len(plan.locations), existing_emails=len(seen_emails))
            # Complete every city before any Hunter or NeverBounce requests.
            collected = []
            for location in plan.locations:
                self._check_cancel(cancel)
                collected.extend((item, location) for item in self._discover(identity, campaign, plan, location, cancel))
            # Rank is query-specific: qualify each city result before retaining one per domain.
            domains = {}
            self._diagnose(campaign, "domain_filtering_started", message=f"All cities finished. Filtering {len(collected)} business results into unique company domains.", businesses=len(collected))
            self._save(identity, campaign)
            for item_index, (item, location) in enumerate(collected):
                self._check_cancel(cancel)
                if item_index and item_index % 100 == 0:
                    self._save(identity, campaign)
                business = normalize_business(item)
                website, domain, domain_reason = extract_domain(business.business_website)
                if not domain:
                    progress["no_contact"] += 1
                    self._diagnose(campaign, "domain_skipped", message="Business skipped: " + (domain_reason or "no usable website").replace("_", " ") + ".",
                        reason=domain_reason, city=location.city, business=business.business_name)
                    continue
                business.business_website, business.business_domain = website, domain
                business.business_city = business.business_city or location.city
                business.business_state = business.business_state or location.state
                lead = Lead(business=business, run_id=campaign["id"])
                request = ScrapeRequest(niche=plan.niche, city=location.city, state=location.state,
                    min_google_maps_rank=location.min_rank, max_google_maps_rank=location.max_rank)
                if not qualify(lead, request):
                    progress["excluded"] += 1
                    self._diagnose(campaign, "rank_excluded", domain=domain, message="Domain excluded by rank filter: " + (lead.filter_reason or "rank unavailable").replace("_", " ") + ".",
                        rank=lead.google_maps_rank, min_rank=location.min_rank, max_rank=location.max_rank, city=location.city)
                    continue
                if domain in domains:
                    progress["duplicates"] += 1
                    self._diagnose(campaign, "duplicate_domain", domain=domain, message="Duplicate domain removed; the first eligible result is already queued.")
                    continue
                domains[domain] = lead
                self._diagnose(campaign, "domain_queued", domain=domain, message="Unique company domain queued for Hunter.", rank=lead.google_maps_rank, city=location.city)
            progress["discovered"] = len(domains)
            self._diagnose(campaign, "domains_ready", message=f"Domain filtering complete: {len(domains)} unique domains, {progress['duplicates']} duplicates removed, {progress['excluded']} rank exclusions, {progress['no_contact']} unusable websites.",
                domains=len(domains), duplicates=progress["duplicates"], rank_exclusions=progress["excluded"], unusable_websites=progress["no_contact"])
            self._save(identity, campaign, "enriching",
                f"All cities scraped. Processing {len(domains)} unique company domains, one at a time.")
            hunter_errors = verification_errors = 0
            with httpx.Client(timeout=httpx.Timeout(35, connect=10), follow_redirects=False) as client:
                hunter = HunterService(ProviderHTTP(client, "hunter", self.settings.provider_retries,
                    self.settings.provider_interval, cancel=cancel), self.settings.hunter_key,
                    self.settings.max_hunter_results, self.settings.max_hunter_pages)
                hunter.diagnostic = lambda event, **fields: self._hunter_diagnostic(identity, campaign, event, **fields)
                verifier = NeverBounceService(ProviderHTTP(client, "neverbounce", self.settings.provider_retries,
                    self.settings.provider_interval, cancel=cancel), self.settings.neverbounce_key)
                for domain, base in domains.items():
                    self._check_cancel(cancel)
                    before = {key: progress[key] for key in ("checked", "verified", "rejected", "reused", "verification_errors")}
                    self._diagnose(campaign, "domain_started", domain=domain, message=f"Domain {progress['processed'] + 1}/{len(domains)}: searching Hunter for up to two people.")
                    self._save(identity, campaign, message=f"Processing domain {progress['processed'] + 1}/{len(domains)}: {domain}.")
                    search = hunter.search_people(domain)
                    self._check_cancel(cancel)
                    reason = search.reason or ""
                    self._diagnose(campaign, "hunter_selection", domain=domain, message=f"Hunter selected {len(search.contacts)} of at most 2 non-generic contacts (names optional).",
                        selected=len(search.contacts), reason=search.reason)
                    self._save(identity, campaign)
                    failed = bool(reason and reason not in {"hunter_search_limit_reached", "hunter_privacy_suppressed"})
                    hunter_errors = hunter_errors + 1 if failed else 0
                    if reason.endswith(("quota_exhausted", "authentication_error", "rate_limit_cooldown")) or hunter_errors >= 3:
                        campaign["stop_reason"] = reason or "hunter_unavailable"
                        raise RuntimeError("Hunter unavailable")
                    if failed:
                        warning = "Some Hunter searches failed. Those domains may have no saved contacts."
                        if warning not in campaign["warnings"]:
                            campaign["warnings"].append(warning)
                    if not search.contacts:
                        progress["no_contact"] += 1
                        self._diagnose(campaign, "no_eligible_contacts", domain=domain, level="warning", message="No lead from this domain: Hunter returned no eligible non-generic emails.", reason=search.reason)
                    # Selection is capped before verification. Rejected or existing emails
                    # do not cause replacement checks beyond these two selected contacts.
                    for candidate_index, contact in enumerate(search.contacts[:2], start=1):
                        self._check_cancel(cancel)
                        email = contact.email.strip().casefold()
                        if email in seen_emails:
                            progress["reused"] += 1
                            self._diagnose(campaign, "duplicate_email", domain=domain, message=f"Contact {candidate_index}: email already saved or encountered; skipping NeverBounce.", contact_number=candidate_index)
                            continue
                        seen_emails.add(email)
                        self._diagnose(campaign, "verification_started", domain=domain, message=f"Contact {candidate_index}: waiting for NeverBounce.", contact_number=candidate_index)
                        self._save(identity, campaign)
                        verification = verifier.verify(email)
                        progress["checked"] += 1
                        self._diagnose(campaign, "candidate_verification", domain=domain,
                            message=f"Contact {candidate_index}: NeverBounce returned {verification.result}.",
                            level="error" if verification.result == "verification_error" else "info",
                            contact_number=candidate_index,
                            result=verification.result, failure_reason=verification.failure_reason)
                        self._check_cancel(cancel)
                        failed = verification.result == "verification_error"
                        verification_errors = verification_errors + 1 if failed else 0
                        progress["verification_errors"] += int(failed)
                        reason = verification.failure_reason or ""
                        if reason.endswith(("quota_exhausted", "authentication_error", "rate_limit_cooldown")) or verification_errors >= 3:
                            campaign["stop_reason"] = reason or "neverbounce_unavailable"
                            raise RuntimeError("NeverBounce unavailable")
                        if verification.result not in ACCEPTED_RESULTS:
                            progress["rejected"] += 1
                            self._diagnose(campaign, "contact_rejected", domain=domain, level="warning", message=f"Contact {candidate_index}: {verification.result} is not accepted; no database save.", contact_number=candidate_index)
                            self._save(identity, campaign)
                            continue
                        lead = base.model_copy(deep=True)
                        lead.contact, lead.contact_type = contact, "decision_maker" if decision_tier(contact) else "person"
                        lead.verification, lead.verified, lead.enrichment_status = verification, True, "verified"
                        lead.enrichment_timestamp = datetime.fromisoformat(now())
                        lead.hunter_metadata, lead.hunter_search_reason = search.metadata, search.reason
                        lead.contact_scope = "Email matches company domain; local branch affiliation not established."
                        lead.verification_attempts = [{"email": email, **verification.model_dump()}]
                        business = lead.business
                        record = {"id": hashlib.sha256(email.encode()).hexdigest()[:32],
                            "company": business.business_name or domain, "domain": domain,
                            "industry": business.business_category or plan.niche,
                            "location": business.business_address or f"{business.business_city}, {business.business_state}",
                            "website": business.business_website, "category": "verified", "stage": "new",
                            "tags": [], "notes": "", "next_action": "", "follow_up": "",
                            "campaign_ids": [campaign["id"]], "source": "google_maps",
                            "assessment": {"summary": "", "fit": "unknown", "reasons": [], "unknowns": [], "evidence": [], "excluded": False},
                            "lead": lead.model_dump(mode="json"), "created_at": now(),
                            "activities": [{"at": now(), "message": "Found by " + plan.niche}]}
                        self._diagnose(campaign, "lead_save_started", domain=domain, message=f"Contact {candidate_index}: accepted ({verification.result}); saving to the database.", contact_number=candidate_index)
                        self._save(identity, campaign)
                        # Keep recovery creation in the same owner lock as insertion,
                        # so deletion cannot be followed by a stale recovery write.
                        with self.store.operation_lock(identity.owner):
                            try:
                                inserted = self.store.insert_lead(identity, record)
                            except HTTPException:
                                self._diagnose(campaign, "lead_save_failed", domain=domain, level="error", message=f"Contact {candidate_index}: database save failed; attempting a local recovery copy.", contact_number=candidate_index)
                                self.store.recovery_save(identity, "lead", record)
                                raise
                        if inserted:
                            progress["verified"] += 1
                            campaign["lead_ids"].append(record["id"])
                            self._diagnose(campaign, "lead_saved", domain=domain, level="success", message=f"Contact {candidate_index}: lead saved. {progress['verified']} new leads saved so far.", contact_number=candidate_index, lead_id=record["id"])
                        else:
                            progress["reused"] += 1
                            self._diagnose(campaign, "lead_insert_conflict", domain=domain, message=f"Contact {candidate_index}: already exists in the database; duplicate insert skipped.", contact_number=candidate_index)
                        self._save(identity, campaign)
                    progress["processed"] += 1
                    delta = {key: progress[key] - before[key] for key in before}
                    self._diagnose(campaign, "domain_finished", domain=domain,
                        message=f"Domain finished: {delta['checked']} checked, {delta['verified']} saved, {delta['rejected']} rejected, {delta['reused']} duplicates skipped.", **delta)
                    self._save(identity, campaign)
            self._check_cancel(cancel)
            campaign.update(completed_at=now(), stop_reason="all_domains_processed")
            self._save(identity, campaign, "completed",
                f"Finished all {len(plan.locations)} cities and {len(domains)} unique domains. Saved {progress['verified']} new leads.")
        except InterruptedError:
            campaign.update(status="cancelled", stop_reason="cancelled", completed_at=now(),
                message=f"Search stopped. {progress['verified']} saved leads retained.")
        except Exception as error:
            campaign.setdefault("stop_reason", "provider_or_storage_failure")
            self._diagnose(campaign, "campaign_error", level="error", message="Search interrupted: " + campaign["stop_reason"].replace("_", " ") + ".", exception_type=type(error).__name__)
            campaign.update(status="failed", completed_at=now(),
                message=f"Search interrupted. {progress['verified']} saved leads retained. Check provider access and storage before starting another search.")
        finally:
            self._diagnose(campaign, "campaign_finished", level="success" if campaign["status"] == "completed" else "warning",
                message=f"Search {campaign['status']}: {progress['processed']} domains processed, {progress['checked']} emails checked, {progress['verified']} leads saved.", status=campaign["status"])
            try:
                self.store.save(identity, "campaign", campaign)
            except Exception:
                self.store.recovery_save(identity, "campaign", campaign)
            finally:
                with self.lock:
                    self.jobs.pop(campaign["id"], None)

    def close(self):
        with self.lock:
            self.closed = True
            for event in self.jobs.values():
                event.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
