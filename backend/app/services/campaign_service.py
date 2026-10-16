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
from app.models.workspace import CampaignPlan, now, new_id
from app.services.apify_service import ApifyService
from app.services.business_service import deduplicate_businesses, unique_companies
from app.services.domain_service import extract_domain
from app.services.enrichment_pipeline import VerificationCache, enrich_lead
from app.services.hunter_service import HunterService
from app.services.neverbounce_service import NeverBounceService
from app.services.provider_http import ProviderHTTP
from app.services.qualification_service import qualify
from app.services.research_service import ResearchService, public_url

ACTIVE = {"queued", "discovering", "researching", "enriching"}


class CampaignService:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.process_id = uuid4().hex
        self.executor = ThreadPoolExecutor(max_workers=settings.max_active_runs, thread_name_prefix="campaign")
        self.jobs: dict[str, Event] = {}
        self.lock = RLock()
        self.closed = False

    def create(self, identity, plan: CampaignPlan):
        for website in plan.websites:
            if not public_url(website):
                raise HTTPException(422, "Use public HTTP or HTTPS company websites.")
        if len(self.store.list(identity, "campaign")) >= 500:
            raise HTTPException(429, "Workspace campaign limit reached.")
        campaign = {"id": new_id(), "plan": plan.model_dump(), "version": 1, "status": "draft",
            "created_at": now(), "message": "Review your research plan before starting.", "events": [],
            "progress": {"discovered": 0, "processed": 0, "verified": 0, "review": 0, "excluded": 0, "reused": 0},
            "usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0}, "warnings": []}
        return self.store.save(identity, "campaign", campaign)

    def update_plan(self, identity, campaign_id, plan, version):
        with self.store.operation_lock(identity.owner):
            campaign = self.store.get(identity, "campaign", campaign_id)
            if campaign["status"] != "draft" or campaign["version"] != version:
                raise HTTPException(409, "Only the current draft can be edited. Duplicate a finished campaign to run a new search.")
            for website in plan.websites:
                if not public_url(website):
                    raise HTTPException(422, "Use public company websites.")
            campaign["plan"], campaign["version"] = plan.model_dump(), version + 1
            return self.store.save(identity, "campaign", campaign)

    def start(self, identity, campaign_id, version):
        with self.lock, self.store.operation_lock(identity.owner):
            campaign = self.store.get(identity, "campaign", campaign_id)
            if campaign["version"] != version:
                raise HTTPException(409, "The campaign changed. Review the latest version.")
            if campaign["status"] != "draft":
                return self.recover(identity, campaign)
            if self.closed or len(self.jobs) >= self.settings.max_active_runs:
                raise HTTPException(429, "Another campaign is running. Wait for it to finish.")
            plan = CampaignPlan.model_validate(campaign["plan"])
            required = [("Hunter", self.settings.hunter_key), ("NeverBounce", self.settings.neverbounce_key)]
            if plan.source == "google_maps":
                required.append(("Apify", self.settings.apify_token))
            if plan.source != "google_maps" or plan.research_websites:
                required.append(("OpenAI", self.settings.openai_key))
            missing = [name for name, key in required if not key or key == "your_token_here"]
            if missing:
                raise HTTPException(503, "Configure " + ", ".join(missing) + " before starting this campaign.")
            # A durable reservation precedes every external paid action.
            campaign.update(status="queued", approved_version=version, process_id=self.process_id, started_at=now())
            self.store.save(identity, "campaign", campaign)
            cancel = self.jobs[campaign_id] = Event()
            try:
                self.executor.submit(self._run, identity, campaign, cancel)
            except Exception:
                self.jobs.pop(campaign_id, None)
                campaign.update(status="failed", message="Unable to schedule the campaign. No provider work was started.")
                self.store.save(identity, "campaign", campaign)
                raise HTTPException(503, campaign["message"]) from None
            return campaign

    def recover(self, identity, campaign):
        if campaign["status"] in ACTIVE and campaign.get("process_id") != self.process_id:
            campaign.update(status="interrupted", message="The backend restarted during this campaign. Saved leads are retained. Check the source provider before duplicating this campaign.")
            self.store.save(identity, "campaign", campaign)
        return campaign

    def cancel(self, identity, campaign_id):
        campaign = self.store.get(identity, "campaign", campaign_id)
        with self.lock:
            if campaign_id in self.jobs:
                self.jobs[campaign_id].set()
                return {"requested": True, "message": "Stopping after the current provider request. An existing Apify actor may still finish."}
        return {"requested": False, "message": "This campaign is not running in this process."}

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

    def _discover(self, plan, campaign, identity, cancel, research):
        if plan.source == "web_research":
            items, warnings = research.discover(plan)
            campaign["warnings"].extend(warnings)
            return items
        if plan.source == "company_websites":
            return [{"title": (extract_domain(url)[1] or url), "website": public_url(url),
                "discovery_source": "company_websites", "source_url": public_url(url)} for url in plan.websites[:plan.max_leads]]
        import time
        apify = ApifyService(ApifyClient(self.settings.apify_token, max_retries=0, timeout_secs=30))
        request = ScrapeRequest(niche=plan.niche, city=plan.city, state=plan.state, max_leads=plan.max_leads)
        scrape = apify.start(request)
        campaign["apify_run_id"] = scrape.run_id
        self._save(identity, campaign, message="Google Maps discovery is running.")
        deadline = time.monotonic() + self.settings.apify_wait_timeout
        while scrape.status == "running":
            if cancel.wait(self.settings.apify_poll_interval):
                raise InterruptedError
            if time.monotonic() > deadline:
                raise RuntimeError("Source wait timed out. Check Apify Console before starting another campaign.")
            scrape = apify.status(scrape.run_id)
        if scrape.status != "succeeded":
            raise RuntimeError("Google Maps discovery failed. Check Apify Console.")
        return apify.results(scrape.run_id)

    def _run(self, identity, campaign, cancel):
        research = ResearchService(self.settings)
        plan = CampaignPlan.model_validate(campaign["plan"])
        try:
            self._save(identity, campaign, "discovering", "Finding companies from " + plan.source.replace("_", " ") + ".")
            items = self._discover(plan, campaign, identity, cancel, research)
            businesses = unique_companies(deduplicate_businesses(items))
            campaign["progress"]["discovered"] = len(businesses)
            try:
                profile = self.store.get(identity, "profile", "business").get("profile", {})
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                profile = {}
            existing = {item.get("domain"): item for item in self.store.list(identity, "lead") if item.get("domain")}
            with httpx.Client(timeout=httpx.Timeout(35, connect=10), follow_redirects=False) as client:
                hunter = HunterService(ProviderHTTP(client, "hunter", self.settings.provider_retries,
                    self.settings.provider_interval, cancel=cancel), self.settings.hunter_key,
                    self.settings.max_hunter_results, self.settings.max_hunter_pages)
                cache = VerificationCache(NeverBounceService(ProviderHTTP(client, "neverbounce", self.settings.provider_retries,
                    self.settings.provider_interval, cancel=cancel), self.settings.neverbounce_key))
                enriched = 0
                for business in businesses:
                    if cancel.is_set():
                        raise InterruptedError
                    lead = Lead(business=business, run_id=campaign["id"])
                    _, domain, reason = extract_domain(business.business_website)
                    business.business_domain = domain
                    if domain in existing:
                        with self.store.operation_lock(identity.owner):
                            old = self.store.get(identity, "lead", existing[domain]["id"])
                            old["campaign_ids"] = list(dict.fromkeys(old.get("campaign_ids", []) + [campaign["id"]]))
                            self.store.save(identity, "lead", old)
                        campaign["progress"]["reused"] += 1
                        campaign["progress"]["processed"] += 1
                        self._save(identity, campaign)
                        continue
                    assessment = {"summary": "Website research was not requested.", "fit": "unknown", "reasons": [], "unknowns": [], "evidence": [], "excluded": False}
                    excluded = False
                    if plan.source == "google_maps":
                        request = ScrapeRequest(niche=plan.niche, city=plan.city, state=plan.state,
                            min_google_maps_rank=plan.min_google_maps_rank, max_google_maps_rank=plan.max_google_maps_rank, max_leads=plan.max_leads)
                        excluded = not qualify(lead, request)
                    if enriched >= plan.max_leads:
                        excluded, lead.filter_reason = True, "campaign_business_limit"
                    if not excluded and plan.research_websites and domain:
                        self._save(identity, campaign, "researching", "Researching " + (business.business_name or domain) + ".")
                        try:
                            assessment = research.assess(business, plan, profile)
                        except HTTPException:
                            assessment.update(summary="Website research could not be completed.", unknowns=["Research unavailable; manual review required"])
                        excluded = assessment["excluded"] or assessment["fit"] == "poor"
                        if excluded:
                            lead.filter_reason = "research_exclusion_or_poor_fit"
                    if cancel.is_set():
                        raise InterruptedError
                    if excluded:
                        lead.enrichment_status = "filtered_out"
                        campaign["progress"]["excluded"] += 1
                    elif domain:
                        enriched += 1
                        self._save(identity, campaign, "enriching", "Finding contacts with Hunter and verifying with NeverBounce for " + (business.business_name or domain) + ".")
                        # The same candidate selection and NeverBounce authority as the original pipeline.
                        try:
                            lead = enrich_lead(lead, hunter.search(domain), cache, self.settings.max_verification_attempts)
                        except Exception:
                            lead.enrichment_status, lead.failure_reason = "enrichment_error", "Provider request failed; contact not verified."
                    else:
                        lead.enrichment_status, lead.failure_reason = "no_website", reason or "No usable company domain."
                    lead.enrichment_timestamp = datetime.fromisoformat(now())
                    category = "excluded" if excluded else "verified" if lead.verified else "needs_review" if lead.contact else "no_contact"
                    campaign["progress"]["verified" if lead.verified else "review"] += int(not excluded)
                    record_id = hashlib.sha256((domain or business.business_name or new_id()).casefold().encode()).hexdigest()[:32]
                    record = {"id": record_id, "company": business.business_name or domain or "Unnamed business",
                        "domain": domain, "industry": business.business_category or plan.niche,
                        "location": business.business_address or ", ".join(filter(None, [business.business_city or plan.city, business.business_state or plan.state])),
                        "website": business.business_website, "category": category, "stage": "new", "tags": [], "notes": "",
                        "next_action": "", "follow_up": "", "campaign_ids": [campaign["id"]], "source": plan.source,
                        "assessment": assessment, "lead": lead.model_dump(mode="json"), "created_at": now(),
                        "activities": [{"at": now(), "message": "Discovered by " + plan.name}]}
                    try:
                        self.store.save(identity, "lead", record)
                    except HTTPException:
                        self.store.recovery_save(identity, "lead", record)
                        raise
                    if domain:
                        existing[domain] = record
                    campaign["progress"]["processed"] += 1
                    self._save(identity, campaign)
            campaign["completed_at"] = now()
            self._save(identity, campaign, "completed", "Research complete. Verified contacts and review items are saved to your CRM.")
        except InterruptedError:
            campaign["completed_at"] = now()
            self._safe_finish(identity, campaign, "cancelled", "Campaign stopped. Completed leads are saved; an existing source actor may still finish.")
        except Exception:
            campaign["completed_at"] = now()
            self._safe_finish(identity, campaign, "failed", "Campaign stopped because a provider or storage request failed. Completed leads are retained. Check provider accounts before duplicating; a source job may already exist.")
        finally:
            campaign["usage"] = {"requests": research.calls, "input_tokens": research.input_tokens, "output_tokens": research.output_tokens}
            try:
                self.store.save(identity, "campaign", campaign)
            except Exception:
                self.store.recovery_save(identity, "campaign", campaign)
            with self.lock:
                self.jobs.pop(campaign["id"], None)

    def _safe_finish(self, identity, campaign, status, message):
        try:
            self._save(identity, campaign, status, message)
        except Exception:
            self.store.recovery_save(identity, "campaign", campaign)

    def close(self):
        with self.lock:
            self.closed = True
            for event in self.jobs.values():
                event.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
