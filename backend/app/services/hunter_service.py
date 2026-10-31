from dataclasses import dataclass, field
from typing import Any

from app.models.leads import Contact
from app.services.contact_selector import rank_candidates
from app.services.lead_policy import is_person
from app.services.contact_selector import decision_tier, is_generic
from app.services.domain_service import extract_domain
from app.services.lead_diagnostics import emit
from app.services.provider_http import ProviderError, ProviderHTTP


@dataclass
class HunterSearch:
    contacts: list[Contact] = field(default_factory=list)
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def parse_contact(item: dict[str, Any]) -> Contact | None:
    email = text(item.get("value"))
    if not email or "@" not in email or any(char.isspace() for char in email):
        return None
    confidence = item.get("confidence")
    return Contact(
        email=email, first_name=text(item.get("first_name")), last_name=text(item.get("last_name")),
        job_title=text(item.get("position")) or text(item.get("position_raw")),
        seniority=text(item.get("seniority")), department=text(item.get("department")),
        decision_maker=item.get("decision_maker") if isinstance(item.get("decision_maker"), bool) else None,
        provider_type=text(item.get("type")),
        confidence=float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None,
        phone=text(item.get("phone_number")),
        linkedin=text(item.get("linkedin")) or text(item.get("linkedin_url")) or text(item.get("linkedin_profile")),
        twitter=text(item.get("twitter")), sources=item.get("sources") if isinstance(item.get("sources"), list) else [],
        raw=item,
    )


class HunterService:
    def __init__(self, http: ProviderHTTP, key: str, max_results: int = 10, max_pages: int = 1):
        self.http, self.key = http, key
        self.max_results, self.max_pages = max_results, max_pages
        self.diagnostic = None

    def _diagnose(self, event, **fields):
        (self.diagnostic or emit)(event, **fields)

    def search_people(self, domain: str) -> HunterSearch:
        """Select at most two non-generic emails, preferring decision-makers; names optional."""
        selected = HunterSearch()
        seen = set()
        for filters in ({"type": "personal", "decision_maker": "true"}, {"type": "personal"}):
            mode = "decision-makers" if filters.get("decision_maker") else "other personal emails"
            self._diagnose("hunter_query_started", domain=domain, filters=filters,
                message=f"Requesting up to 2 personal emails from Hunter ({mode}).")
            found = self._search(domain, filters, result_limit=2)
            selected.metadata.update(found.metadata)
            if found.reason == "hunter_privacy_suppressed":
                self._diagnose("hunter_people_filter", domain=domain, level="warning", message="Hunter privacy suppression: discarded contacts for this domain.", reason=found.reason)
                return HunterSearch(reason=found.reason, metadata=found.metadata)
            provider_domain = found.metadata.get("domain")
            if provider_domain and extract_domain(provider_domain)[1] != domain:
                self._diagnose("hunter_people_filter", domain=domain, level="warning", message="Hunter returned a different company domain; discarded the contacts.", reason="hunter_domain_mismatch")
                return HunterSearch(reason="hunter_domain_mismatch", metadata=found.metadata)
            people = [contact for contact in found.contacts if is_person(contact)
                and extract_domain(contact.email.rsplit("@", 1)[-1])[1] == domain]
            people.sort(key=lambda contact: (decision_tier(contact) or 99, -(contact.confidence or 0)))
            for contact in people:
                email = contact.email.strip().casefold()
                if email not in seen:
                    seen.add(email)
                    selected.contacts.append(contact)
                if len(selected.contacts) == 2:
                    break
            selected.reason = found.reason
            non_people = sum(not is_person(contact) for contact in found.contacts)
            generic = sum(is_generic(contact) for contact in found.contacts)
            unnamed_selected = sum(not (contact.first_name or contact.last_name) for contact in selected.contacts)
            mismatches = sum(is_person(contact) and extract_domain(contact.email.rsplit("@", 1)[-1])[1] != domain for contact in found.contacts)
            self._diagnose("hunter_people_filter", domain=domain, filters=filters,
                message=f"Hunter {mode}: {len(found.contacts)} parsed contacts, {generic} generic excluded, {non_people - generic} malformed emails excluded, {mismatches} wrong-domain excluded; {len(selected.contacts)} selected in total ({unnamed_selected} without names).",
                returned=len(found.contacts), non_people=non_people, domain_mismatches=mismatches,
                generic_excluded=generic, invalid_email_excluded=non_people - generic, unnamed_selected=unnamed_selected,
                selected=len(selected.contacts), reason=found.reason)
            if len(selected.contacts) == 2 or (found.reason and found.reason != "hunter_search_limit_reached"):
                break
        return selected

    def search(self, domain: str) -> HunterSearch:
        # Hunter documents job_titles, decision_maker, seniority and type filters.
        # Fetch owners/CEOs first; broaden only after a successful empty search.
        filters = [
            {"type": "personal", "job_titles": "Owner,Founder,CEO,President,Managing Partner"},
            {"type": "personal", "seniority": "executive"},
            {"type": "personal", "decision_maker": "true"},
            {"type": "generic"},
        ]
        for filter_index, query in enumerate(filters, start=1):
            found = self._search(domain, query)
            found.metadata["filters"] = query
            ranked = rank_candidates(found.contacts)
            stop = bool(ranked) or bool(found.reason and found.reason != "hunter_search_limit_reached")
            self._diagnose("hunter_filter_result", domain=domain, filter_index=filter_index,
                filters=query, parsed_contacts=len(found.contacts), ranked_contacts=len(ranked),
                eligible_people=sum(kind == "decision_maker" and is_person(contact) for contact, kind in ranked),
                reason=found.reason, pages_fetched=found.metadata.get("pages_fetched", 0),
                max_results=self.max_results, max_pages=self.max_pages,
                decision="stop_ranked_contacts" if ranked else "stop_provider_reason" if stop else "filters_exhausted" if filter_index == len(filters) else "broaden",
                remaining_filters=len(filters) - filter_index)
            if stop:
                return found
        return found

    def _search(self, domain: str, filters: dict[str, str], result_limit: int | None = None) -> HunterSearch:
        found = HunterSearch()
        offset = 0
        seen = set()
        max_results = result_limit if result_limit is not None else self.max_results
        max_pages = 1 if result_limit is not None else self.max_pages
        for page in range(max_pages):
            limit = min(10, max_results - offset)
            if limit <= 0:
                break
            try:
                payload = self.http.get("https://api.hunter.io/v2/domain-search",
                    params={"domain": domain, "limit": limit, "offset": offset, **filters},
                    headers={"X-API-KEY": self.key})
            except ProviderError as error:
                # A privacy suppression invalidates partial contacts; do not work around it.
                if error.reason == "hunter_privacy_suppressed":
                    found.contacts.clear()
                found.reason = error.reason
                self._diagnose("hunter_page_error", domain=domain, filters=filters, offset=offset, reason=error.reason,
                    level="error", message="Hunter request failed: " + error.reason.replace("_", " ") + ".")
                return found
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("emails"), list):
                found.reason = "hunter_invalid_response"
                self._diagnose("hunter_page_error", domain=domain, filters=filters, offset=offset, reason=found.reason,
                    level="error", message="Hunter returned an unexpected response format.")
                return found
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            found.metadata = {"organization": data.get("organization"), "domain": data.get("domain"),
                              "results": meta.get("results"), "pages_fetched": page + 1}
            items = data["emails"]
            for item in items:
                if isinstance(item, dict) and (contact := parse_contact(item)) and contact.email.casefold() not in seen:
                    seen.add(contact.email.casefold())
                    found.contacts.append(contact)
            offset += len(items)
            total = meta.get("results")
            more = bool(items) and (offset < total if isinstance(total, int) else len(items) == limit)
            self._diagnose("hunter_page_result", domain=domain, filters=filters, page=page + 1,
                message=f"Hunter response: {len(items)} raw results, {len(found.contacts)} unique parsed contacts." + (" More results exist beyond this request's limit." if more else ""),
                requested_limit=limit, returned_records=len(items), parsed_unique_contacts=len(found.contacts),
                provider_total=total if isinstance(total, int) else None, more_available=more,
                truncated=more and (offset >= max_results or page + 1 >= max_pages))
            if not more:
                break
            if offset >= max_results or page + 1 >= max_pages:
                found.reason = "hunter_search_limit_reached"
                break
        return found
