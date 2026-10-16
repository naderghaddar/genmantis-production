"""GenMantis lead policy: named people and the user's accepted NeverBounce outcomes."""
from app.models.leads import Contact
from app.services.contact_selector import is_generic

ACCEPTED_RESULTS = frozenset({"valid", "catchall", "unknown"})


def is_person(contact: Contact | None) -> bool:
    if contact is None or not contact.email.strip() or is_generic(contact):
        return False
    return bool((contact.first_name or "").strip() or (contact.last_name or "").strip())


def verified_contact(record: dict) -> bool:
    lead = record.get("lead") or {}
    contact = lead.get("contact")
    if not contact or record.get("category") == "excluded" or lead.get("contact_type") == "generic":
        return False
    return is_person(Contact.model_validate(contact)) and (lead.get("verification") or {}).get("result") in ACCEPTED_RESULTS


def normalize_record(record: dict) -> dict:
    """Apply the current policy to older saved records without changing provider evidence."""
    lead = record.get("lead") or {}
    lead["verified"] = verified_contact(record)
    record["lead"] = lead
    if record.get("category") != "excluded":
        record["category"] = "verified" if lead["verified"] else "needs_review" if lead.get("contact") else "no_contact"
    return record


def visible_leads(records: list[dict]) -> list[dict]:
    seen, result = set(), []
    for record in records:
        if not verified_contact(record):
            continue
        email = record["lead"]["contact"]["email"].strip().casefold()
        if email not in seen:
            result.append(normalize_record(record))
            seen.add(email)
    return result
