import json
import re
import unicodedata
from typing import Any

from app.models.leads import Business
from app.services.hunter_service import text
from app.services.domain_service import extract_domain


def normalize_business(item: dict[str, Any]) -> Business:
    def numeric(key: str, integer: bool = False):
        value = item.get(key)
        if value is None:
            return None
        try:
            return int(value) if integer else float(value)
        except (ValueError, TypeError, OverflowError):
            return None

    return Business(
        business_name=text(item.get("title")), business_category=text(item.get("categoryName")),
        business_website=text(item.get("website")), business_phone=text(item.get("phone")) or text(item.get("phoneUnformatted")),
        business_address=text(item.get("address")), business_city=text(item.get("city")), business_state=text(item.get("state")),
        business_postal_code=str(item["postalCode"]) if item.get("postalCode") is not None else None,
        google_maps_url=text(item.get("url")), google_place_id=text(item.get("placeId")),
        google_rating=numeric("totalScore"), google_review_count=numeric("reviewsCount", True), original=dict(item),
    )


def deduplicate_businesses(items: list[dict[str, Any]]) -> list[Business]:
    found: dict[str, Business] = {}
    for item in items:
        business = normalize_business(item)
        if business.google_place_id:
            key = "place:" + business.google_place_id
        elif item.get("cid"):
            key = "cid:" + str(item["cid"])
        elif business.google_maps_url:
            key = "maps:" + business.google_maps_url
        elif business.business_name and business.business_address:
            key = "address:" + json.dumps([business.business_name.casefold(), business.business_address.casefold(),
                business.business_city, business.business_state], ensure_ascii=False)
        else:
            # Exact-record fallback; a shared domain or phone never merges separate branches.
            key = "record:" + json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        if key not in found:
            found[key] = business
        else:
            existing = found[key]
            existing.original.setdefault("duplicate_records", []).append(item)
            for field in Business.model_fields:
                if field != "original" and getattr(existing, field) is None:
                    setattr(existing, field, getattr(business, field))
    return list(found.values())


def unique_companies(businesses: list[Business]) -> list[Business]:
    """Keep one business per normalized name OR registrable domain before provider calls."""
    prepared = []
    for index, business in enumerate(businesses):
        normalized, domain, _ = extract_domain(business.business_website)
        if normalized:
            business.business_website = normalized
        business.business_domain = domain
        name = re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", business.business_name or "").casefold()).strip()
        prepared.append((index, business, name))

    names: dict[str, Business] = {}
    domains: dict[str, Business] = {}
    kept = []
    # Prefer a usable website when duplicate company names include missing/invalid websites.
    for index, business, name in sorted(prepared, key=lambda item: (not bool(item[1].business_domain), item[0])):
        domain = business.business_domain
        existing = domains.get(domain) if domain else None
        existing = existing or (names.get(name) if name else None)
        if existing:
            duplicates = existing.original.setdefault("duplicate_records", [])
            duplicates.append(business.original)
            continue
        if name:
            names[name] = business
        if domain:
            domains[domain] = business
        kept.append((index, business))
    return [business for _, business in sorted(kept, key=lambda item: item[0])]
