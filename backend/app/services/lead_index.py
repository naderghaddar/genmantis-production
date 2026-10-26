"""Per-search, owner-scoped email membership and company counts."""
from collections import Counter

from app.services.domain_service import extract_domain


class LeadIndex:
    def __init__(self, rows):
        self.emails: set[str] = set()
        self.company_counts: Counter[str] = Counter()
        memberships = set()
        for row in rows:
            email = (row.get("email") or "").strip().casefold()
            if not email:
                continue
            self.emails.add(email)
            domain = next((domain for value in (
                row.get("domain"), row.get("website"),
                row.get("company_domain"), row.get("company_website"),
            ) if (domain := extract_domain(value)[1])), None)
            if domain and (domain, email) not in memberships:
                memberships.add((domain, email))
                self.company_counts[domain] += 1

    def at_company_limit(self, domain: str, limit: int | None) -> bool:
        return limit is not None and self.company_counts[domain] >= limit

    def add(self, email: str, domain: str):
        self.emails.add(email.strip().casefold())
        self.company_counts[domain] += 1
