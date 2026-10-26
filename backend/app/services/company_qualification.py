"""Evidence checks before a Maps result can become a company contact lead.

Search relevance alone is not category or website-ownership evidence. Keep these
checks deterministic so ordinary searches do not consume the research budget.
"""
import re
import unicodedata

from app.services.domain_service import EXTRACT, extract_domain


# Canonical Maps categories, including common alternate labels for each niche.
CATEGORY_GROUPS = (
    ({"chiropractor", "chiropractic"}, ["chiropractor"]),
    ({"dentist", "dental", "dentistry"}, ["dentist", "dental clinic", "cosmetic dentist", "pediatric dentist", "dental implants provider"]),
    ({"plumber", "plumbing"}, ["plumber"]),
    ({"electrician", "electrical"}, ["electrician"]),
    ({"lawyer", "attorney", "legal"}, ["lawyer", "law firm", "attorney"]),
    ({"hvac", "heating", "air conditioning"}, ["hvac contractor", "heating contractor", "air conditioning contractor"]),
    ({"roofer", "roofing"}, ["roofing contractor"]),
)
GENERIC = {"a", "an", "the", "and", "of", "for", "in", "near", "local", "business", "company", "service", "provider"}
LEGAL = {"inc", "llc", "ltd", "limited", "corp", "corporation", "pc", "pllc"}


def words(value):
    tokens = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value or "").casefold())
    singular = {token[:-3] + "y" if token.endswith("ies") else token[:-1]
                if token.endswith("s") and not token.endswith("ss") else token for token in tokens}
    aliases = {"chiropractic": "chiropractor", "dental": "dentist", "dentistry": "dentist",
               "plumbing": "plumber", "electrical": "electrician", "attorney": "lawyer"}
    return {aliases.get(token, token) for token in singular}


def niche_terms(niche):
    return words(niche) - GENERIC


def maps_categories(niche):
    terms = niche_terms(niche)
    for aliases, categories in CATEGORY_GROUPS:
        if any(words(alias) <= terms for alias in aliases):
            return categories
    return []


def matches_niche(business, niche):
    categories = business.original.get("categories") or []
    if not isinstance(categories, list):
        categories = []
    labels = [label for label in [business.business_category, *categories] if isinstance(label, str)]
    requested = maps_categories(niche)
    if requested:
        # Evaluate all supplied categories, not just Google's primary category.
        allowed = {frozenset(words(label)) for label in requested}
        return any(frozenset(words(label)) in allowed for label in labels)
    terms = niche_terms(niche)
    return bool(terms) and any(terms <= words(label) for label in labels)


def official_domain_basis(business, domain, organization=None):
    """Require name/domain or independent Hunter organization-name agreement.

    This establishes company-domain evidence, not employment at a local branch.
    A missing match remains unconfirmed rather than being assumed official.
    """
    name = words(business.business_name) - LEGAL
    if not name:
        return None
    label = EXTRACT(domain).domain
    compact_name = "".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", business.business_name or "").casefold()))
    compact_label = "".join(sorted(words(label)))
    if compact_name == compact_label:
        return "business_name_matches_domain"
    category_words = words(business.business_category) | words(business.business_city) | words(business.business_state)
    distinctive = name - GENERIC - category_words - {"clinic", "center", "centre", "group", "store", "dr", "doctor", "chiropractic", "dental"}
    if any(len(token) >= 4 and token in label for token in distinctive):
        return "business_brand_matches_domain"
    org = words(organization) - LEGAL - GENERIC
    brand = name - GENERIC
    if org and brand and (org == brand or ((brand <= org or org <= brand) and bool(org & distinctive))):
        return "hunter_organization_matches_business"
    return None


def contact_matches_domain(contact, domain):
    email_domain = contact.email.strip().rsplit("@", 1)[-1]
    return "@" in contact.email and extract_domain(email_domain)[1] == domain
