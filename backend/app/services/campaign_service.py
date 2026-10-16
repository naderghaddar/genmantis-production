import hashlib
from datetime import datetime
from dataclasses import replace
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
from app.services.enrichment_pipeline import VerificationCache
from app.services.contact_selector import rank_candidates
from app.services.lead_policy import ACCEPTED_RESULTS, is_person, verified_contact
from app.services.hunter_service import HunterService
from app.services.neverbounce_service import NeverBounceService
from app.services.provider_http import ProviderHTTP
from app.services.qualification_service import qualify
from app.services.research_service import ResearchService, public_url

ACTIVE = {"queued", "discovering", "researching", "enriching", "recommending"}


class CampaignService:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.process_id = uuid4().hex
        self.executor = ThreadPoolExecutor(max_workers=settings.max_active_runs, thread_name_prefix="campaign")
        self.jobs: dict[str, Event] = {}
        self.lock = RLock()
        self.closed = False

    def create(self, identity, plan: CampaignPlan, thread_id=None, request_id=None):
        for website in plan.websites:
            if not public_url(website):
                raise HTTPException(422, "Use public HTTP or HTTPS company websites.")
        if len(self.store.list(identity, "campaign")) >= 500:
            raise HTTPException(429, "Workspace campaign limit reached.")
        campaign = {"id": new_id(), "plan": plan.model_dump(), "version": 1, "status": "draft",
            "created_at": now(), "message": "Ready to find verified people for your SEO outreach.", "events": [],
            "thread_id": thread_id, "request_id": request_id, "locations": [], "recommendations": [],
            "lead_ids": [], "policy_version": "person-v2",
            "progress": {"discovered": 0, "processed": 0, "verified": 0, "review": 0, "excluded": 0, "reused": 0, "target": plan.max_leads, "rejected": 0, "no_contact": 0, "verification_errors": 0},
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
            campaign["progress"]["target"] = plan.max_leads
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
            campaign["policy_version"] = "person-v2"
            campaign.setdefault("locations", [])
            campaign.setdefault("recommendations", [])
            campaign.setdefault("lead_ids", [])
            campaign["progress"]["target"] = plan.max_leads
            for key in ("rejected", "no_contact", "verification_errors"):
                campaign["progress"].setdefault(key, 0)
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
                "discovery_source": "company_websites", "source_url": public_url(url)} for url in plan.websites]
        import time
        apify = ApifyService(ApifyClient(self.settings.apify_token, max_retries=0, timeout_secs=30))
        request = ScrapeRequest(niche=plan.niche, city=plan.city, state=plan.state, max_leads=30)
        scrape = apify.start(request)
        campaign["apify_run_id"] = scrape.run_id
        campaign.setdefault("apify_run_ids", []).append(scrape.run_id)
        campaign["locations"][-1]["apify_run_id"] = scrape.run_id
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
        return apify.results(scrape.run_id)[:70]

    def _run(self, identity, campaign, cancel):
        research = ResearchService(self.settings)
        plan = CampaignPlan.model_validate(campaign["plan"])
        progress = campaign["progress"]
        progress.update(target=plan.max_leads)
        seen_domains, seen_emails = set(), set()
        recommendations_research = None
        try:
            # A new request counts new people, never duplicates already in the lead database.
            seen_emails = {item["lead"]["contact"]["email"].strip().casefold()
                for item in self.store.list(identity, "lead") if verified_contact(item)}
            try:
                profile = self.store.get(identity, "profile", "business").get("profile", {})
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                profile = {"offer": "Local SEO services", "ideal_customer": "Local businesses that can benefit from better search visibility"}
            locations = plan.locations or [None]
            if plan.source == "company_websites":
                locations = [None]
            with httpx.Client(timeout=httpx.Timeout(35, connect=10), follow_redirects=False) as client:
                hunter = HunterService(ProviderHTTP(client, "hunter", self.settings.provider_retries,
                    self.settings.provider_interval, cancel=cancel), self.settings.hunter_key,
                    self.settings.max_hunter_results, self.settings.max_hunter_pages)
                cache = VerificationCache(NeverBounceService(ProviderHTTP(client, "neverbounce", self.settings.provider_retries,
                    self.settings.provider_interval, cancel=cancel), self.settings.neverbounce_key))
                for location in locations:
                    if cancel.is_set():
                        raise InterruptedError
                    if progress["verified"] >= plan.max_leads:
                        break
                    local_plan = plan.model_copy(update={"city": location.city, "state": location.state, "locations": [location]}) if location else plan
                    local = {"city": local_plan.city, "state": local_plan.state, "status": "discovering", "discovered": 0, "processed": 0, "leads": 0}
                    campaign["locations"].append(local)
                    label = ", ".join(filter(None, [local_plan.city, local_plan.state])) or "the supplied websites"
                    self._save(identity, campaign, "discovering", f"Finding up to 70 businesses in {label}. {progress['verified']}/{plan.max_leads} leads found.")
                    items = self._discover(local_plan, campaign, identity, cancel, research)
                    businesses = unique_companies(deduplicate_businesses(items[:70]))
                    local.update(discovered=len(businesses), status="enriching")
                    progress["discovered"] += len(businesses)
                    for business in businesses:
                        if cancel.is_set():
                            raise InterruptedError
                        if progress["verified"] >= plan.max_leads:
                            break
                        progress["processed"] += 1
                        local["processed"] += 1
                        _, domain, reason = extract_domain(business.business_website)
                        business.business_domain = domain
                        if not domain:
                            progress["no_contact"] += 1
                            self._save(identity, campaign)
                            continue
                        if domain in seen_domains:
                            progress["reused"] += 1
                            self._save(identity, campaign)
                            continue
                        seen_domains.add(domain)
                        base = Lead(business=business, run_id=campaign["id"])
                        if plan.source == "google_maps":
                            request = ScrapeRequest(niche=plan.niche, city=local_plan.city, state=local_plan.state,
                                min_google_maps_rank=plan.min_google_maps_rank, max_google_maps_rank=plan.max_google_maps_rank)
                            if not qualify(base, request):
                                progress["excluded"] += 1
                                self._save(identity, campaign)
                                continue
                        assessment = {"summary": "Website research was not requested.", "fit": "unknown", "reasons": [], "unknowns": [], "evidence": [], "excluded": False}
                        if plan.research_websites:
                            self._save(identity, campaign, "researching", f"Checking SEO fit for {business.business_name or domain}.")
                            try:
                                assessment = research.assess(business, local_plan, profile)
                            except HTTPException:
                                assessment.update(summary="Website research could not be completed.", unknowns=["Research unavailable; manual review required"])
                            if assessment["excluded"] or assessment["fit"] == "poor":
                                progress["excluded"] += 1
                                self._save(identity, campaign)
                                continue
                        if cancel.is_set():
                            raise InterruptedError
                        self._save(identity, campaign, "enriching", f"Finding and checking people at {business.business_name or domain}. {progress['verified']}/{plan.max_leads} leads found.")
                        search = hunter.search(domain)
                        candidates = [(person, kind) for person, kind in rank_candidates(search.contacts) if kind == "decision_maker" and is_person(person)]
                        if search.reason and search.reason != "hunter_search_limit_reached":
                            warning = "Some Hunter searches failed; lead yield may be incomplete. Check provider access before retrying."
                            if warning not in campaign["warnings"]:
                                campaign["warnings"].append(warning)
                        if not candidates:
                            progress["no_contact"] += 1
                        # Hunter's configured result/page limits bound this list. Check all suitable people,
                        # rather than stopping at the first person or counting a company inbox.
                        for contact, kind in candidates:
                            if cancel.is_set():
                                raise InterruptedError
                            if progress["verified"] >= plan.max_leads:
                                break
                            email = contact.email.strip().casefold()
                            if email in seen_emails:
                                progress["reused"] += 1
                                continue
                            seen_emails.add(email)
                            verification = cache.verify(contact.email)
                            if verification.result not in ACCEPTED_RESULTS:
                                progress["rejected"] += 1
                                progress["verification_errors"] += int(verification.result == "verification_error")
                                continue
                            lead = base.model_copy(deep=True)
                            lead.contact, lead.contact_type, lead.verification = contact, kind, verification
                            lead.verified, lead.enrichment_status = True, "verified"
                            lead.hunter_search_reason, lead.hunter_metadata = search.reason, search.metadata
                            lead.contact_scope = "company_domain; local branch affiliation not established"
                            lead.enrichment_timestamp = datetime.fromisoformat(now())
                            lead.verification_attempts = [{"email": contact.email, "contact_type": kind, **verification.model_dump()}]
                            record_id = hashlib.sha256(email.encode()).hexdigest()[:32]
                            record = {"id": record_id, "company": business.business_name or domain,
                                "domain": domain, "industry": business.business_category or plan.niche,
                                "location": business.business_address or ", ".join(filter(None, [business.business_city or local_plan.city, business.business_state or local_plan.state])),
                                "website": business.business_website, "category": "verified", "stage": "new", "tags": [], "notes": "",
                                "next_action": "", "follow_up": "", "campaign_ids": [campaign["id"]], "source": plan.source,
                                "assessment": assessment, "lead": lead.model_dump(mode="json"), "created_at": now(),
                                "activities": [{"at": now(), "message": "Found by " + plan.name}]}
                            try:
                                self.store.save(identity, "lead", record)
                            except HTTPException:
                                self.store.recovery_save(identity, "lead", record)
                                raise
                            progress["verified"] += 1
                            local["leads"] += 1
                            campaign["lead_ids"].append(record_id)
                            self._save(identity, campaign)
                        self._save(identity, campaign)
                    local["status"] = "target_reached" if progress["verified"] >= plan.max_leads else "completed"
                    self._save(identity, campaign)
            if cancel.is_set():
                raise InterruptedError
            shortfall = max(0, plan.max_leads - progress["verified"])
            campaign["shortfall"] = shortfall
            if shortfall:
                message = f"Found {progress['verified']} of {plan.max_leads} requested leads across {len(campaign['locations'])} searched locations. {shortfall} more leads are needed."
                if progress["verification_errors"]:
                    campaign["warnings"].append(f"{progress['verification_errors']} email checks failed; these are not counted as unknown or as leads.")
                if plan.source != "company_websites" and self.settings.openai_key:
                    self._save(identity, campaign, "recommending", message + " Researching similar cities for your SEO outreach.")
                    # Reserve a separate two-call budget so company research cannot consume recommendations.
                    recommendations_research = ResearchService(replace(self.settings, research_max_calls=2))
                    try:
                        campaign["recommendations"] = recommendations_research.recommend_locations(plan, profile)
                    except (HTTPException, ValueError):
                        campaign["warnings"].append("Similar-city research was unavailable. Ask the advisor to recommend the next locations.")
                if cancel.is_set():
                    raise InterruptedError
                message += " Review the suggested cities to continue." if campaign["recommendations"] else " Tell me more cities, or ask me to research similar markets, to continue."
                if campaign["warnings"]:
                    message += " Some research or provider checks were limited; see the run details."
                status = "shortfall"
            else:
                message = f"Found all {plan.max_leads} requested leads. Each is a unique person with a Hunter email checked by NeverBounce as valid, catchall or unknown."
                status = "completed"
            campaign["completed_at"] = now()
            self._save(identity, campaign, status, message)
        except InterruptedError:
            campaign["completed_at"] = now()
            self._safe_finish(identity, campaign, "cancelled", f"Search stopped with {progress['verified']} of {plan.max_leads} leads saved. An existing source actor may still finish.")
        except Exception:
            campaign["completed_at"] = now()
            self._safe_finish(identity, campaign, "failed", f"Search interrupted with {progress['verified']} of {plan.max_leads} leads saved. A provider or storage request failed; the remaining cities may not have been searched. Check provider accounts before retrying.")
        finally:
            services = [research] + ([recommendations_research] if recommendations_research else [])
            campaign["usage"] = {"requests": sum(s.calls for s in services), "input_tokens": sum(s.input_tokens for s in services), "output_tokens": sum(s.output_tokens for s in services)}
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
