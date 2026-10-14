import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event, Lock
from typing import Callable

from apify_client.errors import ApifyApiError
from impit import TransportError

from app.config import Settings
from app.models.leads import CheckedContact, Lead, RunProgress, Verification
from app.models.schemas import ScrapeRequest
from app.services.apify_service import ApifyService
from app.services.business_service import deduplicate_businesses, unique_companies
from app.services.contact_selector import rank_candidates
from app.services.csv_service import csv_filename, generate_contacts_csv, generate_leads_csv
from app.services.domain_service import extract_domain
from app.services.hunter_service import HunterSearch, HunterService
from app.services.neverbounce_service import NeverBounceService
from app.services.qualification_service import qualify


class PipelineFailure(Exception):
    pass


class VerificationCache:
    """Single-flight email cache: duplicate branch workers share even in-flight results."""
    def __init__(self, provider: NeverBounceService):
        self.provider = provider
        self.values: dict[str, Future[Verification]] = {}
        self.lock = Lock()

    def verify(self, email: str) -> Verification:
        key = email.casefold()
        with self.lock:
            existing = self.values.get(key)
            if existing is None:
                existing = self.values[key] = Future()
                owner = True
            else:
                owner = False
        if owner:
            try:
                result = self.provider.verify(email)
            except Exception:
                result = Verification(result="verification_error", failure_reason="neverbounce_unexpected_error")
            existing.set_result(result)
        return existing.result().model_copy(deep=True)


def enrich_lead(lead: Lead, search: HunterSearch, cache: VerificationCache, max_attempts: int) -> Lead:
    lead.hunter_search_reason = search.reason
    lead.hunter_metadata = search.metadata
    candidates = rank_candidates(search.contacts)
    if not candidates:
        lead.enrichment_status = "hunter_error" if search.reason and search.reason != "hunter_search_limit_reached" else "no_suitable_contact" if search.contacts else "no_email_found"
        lead.failure_reason = search.reason or ("Hunter returned no suitable decision-maker or generic contact." if search.contacts else "Hunter returned no email records within the search limit.")
        return lead
    attempted = candidates[:max_attempts]
    # Reserve one slot for a generic fallback when many people exhaust the budget.
    generic = next((candidate for candidate in candidates if candidate[1] == "generic"), None)
    if max_attempts > 1 and generic and all(kind != "generic" for _, kind in attempted):
        attempted[-1] = generic
    best = None
    quality = {"valid": 0, "catchall": 1, "unknown": 2, "verification_error": 3, "invalid": 4, "disposable": 5}
    for contact, kind in attempted:
        result = cache.verify(contact.email)
        lead.verification_attempts.append({"email": contact.email, "contact_type": kind, **result.model_dump()})
        if best is None or quality[result.result] < quality[best[2].result]:
            best = (contact, kind, result)
        if result.result == "valid":
            break
    contact, kind, verification = best
    lead.contact, lead.contact_type, lead.verification = contact, kind, verification
    lead.contact_scope = "company_domain; local branch affiliation not established"
    lead.verified = verification.result == "valid"
    lead.enrichment_status = "verified" if lead.verified else "verification_error" if verification.result == "verification_error" else "unverified"
    if not lead.verified:
        lead.failure_reason = verification.failure_reason or f"NeverBounce result: {verification.result}. No verified contact found within the attempt limit."
    return lead


class EnrichmentPipeline:
    def __init__(self, settings: Settings, apify: ApifyService, hunter: HunterService,
                 neverbounce: NeverBounceService, cancel: Event | None = None):
        self.settings, self.apify, self.hunter = settings, apify, hunter
        self.cache = VerificationCache(neverbounce)
        self.cancel = cancel or Event()

    def run(self, run_id: str, request: ScrapeRequest, update: Callable[..., None]) -> dict[str, tuple[bytes, str]]:
        progress = RunProgress()
        update(status="scraping", message="Scraping businesses...")
        # Start exactly once. A lost start response is never automatically retried.
        try:
            scrape = self.apify.start(request)
        except Exception:
            raise PipelineFailure("Apify start failed. Check Apify Console before retrying; the run may have started.") from None
        update(apify_run_id=scrape.run_id)
        deadline = time.monotonic() + self.settings.apify_wait_timeout
        read_failures = 0
        while scrape.status == "running":
            if time.monotonic() >= deadline:
                raise PipelineFailure("Stopped waiting for Apify. The actor may still be running; check Apify Console before retrying.")
            if self.cancel.wait(self.settings.apify_poll_interval):
                raise PipelineFailure("Pipeline stopped during server shutdown. Check the Apify run in Console.")
            try:
                scrape = self.apify.status(scrape.run_id)
                read_failures = 0
            except (ApifyApiError, TransportError) as error:
                transient = isinstance(error, TransportError) or error.status_code == 429 or error.status_code >= 500
                if not transient or read_failures >= self.settings.provider_retries:
                    raise PipelineFailure("Apify status check failed. The existing actor may still be running; check Apify Console.") from None
                read_failures += 1
                if self.cancel.wait(2 ** read_failures):
                    raise PipelineFailure("Pipeline stopped during server shutdown.")
        if scrape.status != "succeeded":
            raise PipelineFailure(scrape.message)
        items = None
        for attempt in range(self.settings.provider_retries + 1):
            try:
                items = self.apify.results(scrape.run_id)
                break
            except (ApifyApiError, TransportError) as error:
                if (isinstance(error, ApifyApiError) and error.status_code not in {429} and error.status_code < 500) or attempt == self.settings.provider_retries:
                    raise PipelineFailure("Unable to retrieve the Apify dataset; the source run remains in Apify Console.") from None
                if self.cancel.wait(2 ** attempt):
                    raise PipelineFailure("Pipeline stopped during server shutdown.")
        businesses = unique_companies(deduplicate_businesses(items))
        progress.businesses_scraped = len(businesses)
        leads = [Lead(business=business, run_id=run_id) for business in businesses]
        domains: dict[str, HunterSearch] = {}
        eligible = 0
        for lead in leads:
            if not qualify(lead, request):
                continue
            if eligible >= request.max_leads:
                lead.enrichment_status = "filtered_out"
                lead.filter_reason = lead.failure_reason = "maximum_businesses_reached"
                continue
            eligible += 1
            normalized, domain, reason = extract_domain(lead.business.business_website)
            if normalized:
                lead.business.business_website = normalized
            lead.business.business_domain = domain
            if reason:
                lead.enrichment_status, lead.failure_reason = reason, reason
            elif domain:
                domains.setdefault(domain, HunterSearch())
        progress.businesses_eligible = eligible
        progress.businesses_filtered = len(leads) - eligible
        if eligible == 0 and (request.min_google_maps_rank or request.max_google_maps_rank):
            update(warnings=["No businesses had a matching, supported organic ranking with search context. No enrichment was performed."])
        update(status="enriching", message="Finding decision-makers...", progress=progress.model_copy())

        def search(domain: str) -> HunterSearch:
            if self.cancel.is_set():
                return HunterSearch(reason="pipeline_cancelled")
            try:
                return self.hunter.search(domain)
            except Exception:
                return HunterSearch(reason="hunter_unexpected_error")

        # Duplicate domains and company names have already been removed.
        with ThreadPoolExecutor(max_workers=self.settings.concurrency) as pool:
            futures = {domain: pool.submit(search, domain) for domain in domains}
            for domain, future in futures.items():
                domains[domain] = future.result()
                progress.domains_searched += 1
                progress.contacts_found += len(domains[domain].contacts)
                update(progress=progress.model_copy())
        update(status="verifying", message="Verifying emails...", progress=progress.model_copy())

        def process(lead: Lead) -> Lead:
            try:
                if self.cancel.is_set():
                    lead.enrichment_status, lead.failure_reason = "enrichment_error", "pipeline_cancelled"
                elif lead.enrichment_status != "filtered_out" and lead.business.business_domain:
                    lead = enrich_lead(lead, domains[lead.business.business_domain], self.cache, self.settings.max_verification_attempts)
            except Exception:
                lead.enrichment_status, lead.failure_reason = "enrichment_error", "Unexpected error processing this business."
            lead.enrichment_timestamp = datetime.now(timezone.utc)
            return lead

        with ThreadPoolExecutor(max_workers=self.settings.concurrency) as pool:
            # map retains source order; workers run concurrently, counters update on the orchestrator thread.
            results = []
            for lead in pool.map(process, leads):
                results.append(lead)
                progress.businesses_processed += 1
                progress.verified_emails += int(lead.verified)
                progress.unverified_contacts += int(lead.contact is not None and not lead.verified)
                progress.generic_emails_selected += int(lead.contact_type == "generic")
                progress.businesses_without_contact += int(lead.contact is None)
                progress.failed_enrichments += int(lead.enrichment_status in {"hunter_error", "verification_error", "enrichment_error"})
                update(progress=progress.model_copy())
        # Export only the final selected decision-maker/generic contact for each domain.
        checked_contacts = [CheckedContact(company_domain=lead.business.business_domain,
                                           contact=lead.contact, verification=lead.verification)
                            for lead in results if lead.business.business_domain and lead.contact and lead.verification]
        update(status="exporting", message="Preparing CSV...", progress=progress.model_copy())
        prefix = csv_filename(request.niche, request.city, request.state).removesuffix("_leads.csv")
        return {
            "verified": (generate_contacts_csv(checked_contacts), prefix + "_verified_leads.csv"),
            "all": (generate_leads_csv(results), prefix + "_all_results.csv"),
        }
