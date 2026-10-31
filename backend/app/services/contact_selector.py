import re

from app.models.leads import Contact

GENERIC_PREFIXES = ["info", "contact", "hello", "office", "admin", "sales", "support"]
TITLES = [
    r"\b(owner|founder|co\s*founder|cofounder|ceo|chief executive officer|president|managing partner)\b",
    r"\b(managing director|general manager|executive director|marketing director|director of marketing|head of marketing|cmo|chief marketing officer)\b",
    r"\b(practice manager|clinic manager|operations manager|marketing manager|manager of marketing)\b",
]


def is_generic(contact: Contact) -> bool:
    provider_type = (contact.provider_type or "").strip().casefold()
    if provider_type in {"generic", "personal"}:
        return provider_type == "generic"
    # Fall back to known shared inboxes only when Hunter has not classified it.
    # Names never affect whether an address is generic.
    return contact.email.strip().split("@", 1)[0].casefold() in GENERIC_PREFIXES


def decision_tier(contact: Contact) -> int | None:
    title = re.sub(r"[-_/]+", " ", (contact.job_title or "").lower())
    department = (contact.department or "").casefold()
    if re.search(r"\b(product|process|account|service|data) owner\b", title):
        return 4 if contact.decision_maker is True else None
    # Prevent assistant-to-owner, former CEO, and vice-president substring matches.
    if re.search(r"\b(assistant|former|retired|vice president|vice-president)\b", title):
        return 4 if contact.decision_maker is True and department in {"marketing", "management", "operations", "sales"} else None
    for tier, pattern in enumerate(TITLES, start=1):
        if re.search(pattern, title):
            return min(tier, 2) if (contact.seniority or "").casefold() == "executive" else tier
    if (contact.seniority or "").casefold() == "executive":
        return 2
    relevant = department in {"marketing", "management", "operations", "sales", "procurement", "executive"}
    if relevant and re.search(r"\b(senior manager|director|head|chief|vp|vice president)\b", title):
        return 3
    if contact.decision_maker is True:
        return 4
    return None


def rank_candidates(contacts: list[Contact]) -> list[tuple[Contact, str]]:
    """Relevant people first, real generic addresses next; ordinary employees excluded."""
    people, generic = [], []
    for index, contact in enumerate(contacts):
        metadata = sum(bool(value) for value in (contact.first_name, contact.last_name, contact.phone, contact.linkedin))
        if is_generic(contact):
            prefix = contact.email.split("@", 1)[0].lower()
            priority = GENERIC_PREFIXES.index(prefix) if prefix in GENERIC_PREFIXES else len(GENERIC_PREFIXES)
            generic.append(((priority, -(contact.confidence or 0), -metadata, index), contact))
        elif (tier := decision_tier(contact)) is not None:
            people.append(((tier, -(contact.decision_maker is True), -(contact.confidence or 0), -metadata, index), contact))
    ranked = [(contact, "decision_maker") for _, contact in sorted(people, key=lambda item: item[0])]
    ranked += [(contact, "generic") for _, contact in sorted(generic, key=lambda item: item[0])]
    seen = set()
    result = []
    for contact, kind in ranked:
        if contact.email.casefold() not in seen:
            seen.add(contact.email.casefold())
            result.append((contact, kind))
    return result
