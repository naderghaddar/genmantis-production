from dataclasses import dataclass, field
from typing import Any

from app.models.leads import Contact
from app.services.contact_selector import rank_candidates
from app.services.lead_policy import is_person
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

    def _search(self, domain: str, filters: dict[str, str]) -> HunterSearch:
        found = HunterSearch()
        offset = 0
        seen = set()
        for page in range(self.max_pages):
            limit = min(10, self.max_results - offset)
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
                self._diagnose("hunter_page_error", domain=domain, filters=filters, offset=offset, reason=error.reason)
                return found
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("emails"), list):
                found.reason = "hunter_invalid_response"
                self._diagnose("hunter_page_error", domain=domain, filters=filters, offset=offset, reason=found.reason)
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
                requested_limit=limit, returned_records=len(items), parsed_unique_contacts=len(found.contacts),
                provider_total=total if isinstance(total, int) else None, more_available=more,
                truncated=more and (offset >= self.max_results or page + 1 >= self.max_pages))
            if not more:
                break
            if offset >= self.max_results or page + 1 >= self.max_pages:
                found.reason = "hunter_search_limit_reached"
                break
        return found
