import csv
import io
import json
import re
import unicodedata
from typing import Any

from app.models.leads import Business, CheckedContact, Lead

# Keep familiar business fields first; retain every other field alphabetically.
PREFERRED_COLUMNS = [
    "title", "categoryName", "categories", "address", "street", "city", "state",
    "postalCode", "countryCode", "phone", "phoneUnformatted", "website", "url",
    "totalScore", "reviewsCount", "placeId",
]


def generate_csv(items: list[dict[str, Any]]) -> bytes:
    if not items:
        raise ValueError("No businesses were found. Try another niche or location.")
    keys = {key for item in items for key in item}
    columns = [key for key in PREFERRED_COLUMNS if key in keys]
    columns += sorted(keys - set(columns))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writer.writerow([safe_cell(column) for column in columns])
    for item in items:
        writer.writerow({key: safe_cell(value)
                         for key, value in item.items()})
    # BOM enables Excel to recognize UTF-8; csv handles commas, quotes and newlines.
    return output.getvalue().encode("utf-8-sig")


def safe_cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
        return "'" + value
    return value


LEAD_COLUMNS = [key for key in Business.model_fields if key != "original"] + [
    "contact_first_name", "contact_last_name", "contact_full_name", "contact_job_title",
    "contact_seniority", "contact_department", "contact_is_decision_maker", "contact_type",
    "contact_email", "contact_phone", "contact_linkedin", "contact_twitter", "hunter_confidence",
    "hunter_source_count", "neverbounce_result", "neverbounce_flags", "neverbounce_status",
    "neverbounce_suggested_correction", "verified", "enrichment_status", "failure_reason",
    "hunter_search_reason", "contact_source", "email_verification_source", "scraped_source",
    "run_id", "enrichment_timestamp", "contact_scope", "shared_domain", "original_business_data",
    "hunter_contact_data", "hunter_search_metadata", "verification_attempts",
    "google_maps_rank", "ranking_evidence", "filter_reason",
]


def lead_row(lead: Lead) -> dict[str, Any]:
    row = lead.business.model_dump(exclude={"original"})
    contact, verification = lead.contact, lead.verification
    for field in ("first_name", "last_name", "job_title", "seniority", "department", "email", "phone", "linkedin", "twitter"):
        row[f"contact_{field}"] = getattr(contact, field) if contact else None
    row.update({
        "contact_full_name": " ".join(part for part in [contact.first_name, contact.last_name] if part) if contact else None,
        "contact_is_decision_maker": contact.decision_maker if contact else None,
        "contact_type": lead.contact_type, "hunter_confidence": contact.confidence if contact else None,
        "hunter_source_count": len(contact.sources) if contact else None,
        "neverbounce_result": verification.result if verification else None,
        "neverbounce_flags": verification.flags if verification else None,
        "neverbounce_status": verification.status if verification else None,
        "neverbounce_suggested_correction": verification.suggested_correction if verification else None,
        "verified": lead.verified, "enrichment_status": lead.enrichment_status, "failure_reason": lead.failure_reason,
        "hunter_search_reason": lead.hunter_search_reason, "contact_source": "Hunter" if contact else None,
        "email_verification_source": "NeverBounce" if verification else None, "scraped_source": "Apify",
        "run_id": lead.run_id, "enrichment_timestamp": lead.enrichment_timestamp.isoformat() if lead.enrichment_timestamp else None,
        "contact_scope": lead.contact_scope, "shared_domain": lead.shared_domain,
        "original_business_data": lead.business.original, "hunter_contact_data": contact.raw if contact else None,
        "hunter_search_metadata": lead.hunter_metadata, "verification_attempts": lead.verification_attempts,
        "google_maps_rank": lead.google_maps_rank, "ranking_evidence": lead.ranking_evidence,
        "filter_reason": lead.filter_reason,
    })
    return row


def generate_leads_csv(leads: list[Lead], verified_only: bool = False) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=LEAD_COLUMNS)
    writer.writeheader()
    for lead in leads:
        if verified_only and not (lead.verified and lead.contact and lead.verification and lead.verification.result == "valid"):
            continue
        writer.writerow({key: safe_cell(value) for key, value in lead_row(lead).items()})
    return output.getvalue().encode("utf-8-sig")


CONTACT_COLUMNS = [
    "first name", "last name", "company domain", "title", "email", "phone number",
    "linkedin", "twitter", "email_status",
]
CONTACT_STATUS_ORDER = {"valid": 0, "catchall": 1, "unknown": 2, "verification_error": 3, "disposable": 4}


def generate_contacts_csv(contacts: list[CheckedContact]) -> bytes:
    """One selected Hunter contact per domain, excluding invalid emails."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CONTACT_COLUMNS)
    writer.writeheader()
    seen: set[str] = set()
    for checked in sorted(contacts, key=lambda item: CONTACT_STATUS_ORDER.get(item.verification.result, 3)):
        contact, verification = checked.contact, checked.verification
        key = checked.company_domain.casefold()
        if verification.result == "invalid" or key in seen:
            continue
        seen.add(key)
        row = {
            "first name": contact.first_name, "last name": contact.last_name,
            "company domain": checked.company_domain, "title": contact.job_title,
            "email": contact.email, "phone number": contact.phone,
            "linkedin": contact.linkedin, "twitter": contact.twitter,
            # A provider error is not a NeverBounce result; preserve the contact without inventing one.
            "email_status": verification.result if verification.result != "verification_error" else None,
        }
        writer.writerow({key: safe_cell(value) for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


def csv_filename(niche: str, city: str, state: str) -> str:
    def slug(value: str) -> str:
        ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")[:60] or "leads"
    return "_".join(slug(value) for value in (niche, city, state)) + "_leads.csv"
