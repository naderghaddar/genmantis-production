from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from app.models.leads import Business, Contact, Lead, Verification
from app.services.business_service import deduplicate_businesses, unique_companies
from app.services.contact_selector import rank_candidates
from app.services.domain_service import extract_domain
from app.services.enrichment_pipeline import VerificationCache, enrich_lead
from app.services.hunter_service import HunterSearch


@pytest.mark.parametrize("url,domain", [
    ("https://www.example.com/about", "example.com"),
    ("https://example.co.uk/contact", "example.co.uk"),
    ("EXAMPLE.COM/contact", "example.com"), ("//www.example.ca", "example.ca"),
    ("https://sub.example.com:443/a?q=x#fragment", "example.com"),
    ("https://mybusiness.blogspot.com", "mybusiness.blogspot.com"),
])
def test_domain(url, domain):
    normalized, actual, reason = extract_domain(url)
    assert actual == domain and reason is None
    assert normalized.startswith(("http://", "https://"))


@pytest.mark.parametrize("url,reason", [
    (None, "no_website"), ("  ", "no_website"),
    ("https://facebook.com/page", "excluded_domain"), ("https://www.yelp.com/biz/a", "excluded_domain"),
    ("https://maps.google.com", "excluded_domain"), ("https://maps.app.goo.gl/xx", "excluded_domain"),
    ("http://127.0.0.1", "invalid_website"), ("javascript:alert(1)", "invalid_website"),
    ("https://user:pass@example.com", "invalid_website"), ("not a domain", "invalid_website"),
])
def test_skip_domains(url, reason):
    _, domain, actual = extract_domain(url)
    assert domain is None and actual == reason


def person(email, title=None, **extra):
    return Contact(email=email, job_title=title, provider_type="personal", **extra)


def test_owner_outranks_unrelated_and_rank_is_stable():
    owner = person("owner@clinic.com", "Clinic Owner", confidence=60)
    technical = person("cto@clinic.com", "CTO", decision_maker=True, confidence=100)
    ordinary = person("staff@clinic.com", "Associate Chiropractor", confidence=100)
    marketing = person("marketing@clinic.com", "Marketing Director", decision_maker=True)
    candidates = rank_candidates([technical, ordinary, marketing, owner])
    assert [contact.email for contact, _ in candidates] == [owner.email, marketing.email, technical.email]
    assert rank_candidates([technical, ordinary, marketing, owner]) == candidates


def test_tie_breakers_and_false_title_matches():
    a = person("a@x.com", "Owner", confidence=100)
    b = person("b@x.com", "Owner", confidence=10, decision_maker=True)
    c = person("c@x.com", "Owner", confidence=10, decision_maker=True, linkedin="actual")
    assistant = person("assistant@x.com", "Assistant to the Owner")
    vice = person("vp@x.com", "Vice President of Engineering")
    assert [contact.email for contact, _ in rank_candidates([a, b, c, assistant, vice])] == [c.email, b.email, a.email]


def test_generic_priority_and_no_arbitrary_employee():
    generic = [Contact(email=prefix + "@x.com", provider_type="generic") for prefix in ["support", "sales", "office", "info", "hello", "contact", "admin", "team"]]
    assert [contact.email.split("@")[0] for contact, _ in rank_candidates(generic)] == ["info", "contact", "hello", "office", "admin", "sales", "support", "team"]
    assert rank_candidates([person("employee@x.com", "Receptionist")]) == []
    assert rank_candidates([person("product@x.com", "Product Owner")]) == []


def lead():
    return Lead(business=Business(business_name="Clinic", business_domain="x.com"), run_id="run123")


def test_invalid_candidate_then_valid():
    provider = MagicMock()
    provider.verify.side_effect = [Verification(result="invalid"), Verification(result="valid")]
    contacts = [person("owner@x.com", "Owner"), person("manager@x.com", "Practice Manager")]
    result = enrich_lead(lead(), HunterSearch(contacts), VerificationCache(provider), 4)
    assert result.verified and result.contact.email == "manager@x.com"
    assert len(result.verification_attempts) == 2


def test_generic_verified_fallback_and_attempt_cap():
    provider = MagicMock()
    provider.verify.side_effect = [Verification(result="invalid"), Verification(result="valid")]
    contacts = [person(f"owner{i}@x.com", "Owner") for i in range(5)] + [Contact(email="info@x.com", provider_type="generic")]
    result = enrich_lead(lead(), HunterSearch(contacts), VerificationCache(provider), 2)
    assert result.verified and result.contact_type == "generic"
    assert result.contact.email == "info@x.com"
    assert provider.verify.call_count == 2


@pytest.mark.parametrize("status", ["catchall", "unknown", "invalid", "disposable", "verification_error"])
def test_unverified_results(status):
    provider = MagicMock()
    provider.verify.return_value = Verification(result=status)
    result = enrich_lead(lead(), HunterSearch([person("a@x.com", "Owner")]), VerificationCache(provider), 4)
    assert not result.verified and result.verification.result == status and result.failure_reason


def test_preserve_best_unverified_fallback():
    provider = MagicMock()
    provider.verify.side_effect = [Verification(result="catchall"), Verification(result="invalid")]
    result = enrich_lead(lead(), HunterSearch([person("a@x.com", "Owner"), person("b@x.com", "CEO")]), VerificationCache(provider), 4)
    assert result.contact.email == "a@x.com" and result.verification.result == "catchall"


def test_no_suitable_contact_skips_verification():
    provider = MagicMock()
    result = enrich_lead(lead(), HunterSearch([person("a@x.com", "Receptionist")]), VerificationCache(provider), 4)
    assert result.enrichment_status == "no_suitable_contact"
    provider.verify.assert_not_called()


def test_concurrent_email_cache():
    provider = MagicMock()
    provider.verify.return_value = Verification(result="valid")
    cache = VerificationCache(provider)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(cache.verify, ["Owner@x.com", "owner@x.com", "OWNER@x.com"] * 5))
    assert all(result.result == "valid" for result in results)
    provider.verify.assert_called_once()


def test_dedup_preserves_branches_and_additional_data():
    businesses = deduplicate_businesses([
        {"placeId": "1", "title": "North", "website": "https://x.com"},
        {"placeId": "2", "title": "South", "website": "https://x.com"},
        {"placeId": "1", "title": "North", "phone": "real number", "extra": [1, 2]},
    ])
    assert len(businesses) == 2
    assert businesses[0].business_phone == "real number"
    assert businesses[0].original["duplicate_records"][0]["extra"] == [1, 2]


def test_unique_names_and_domains_before_enrichment():
    businesses = unique_companies(deduplicate_businesses([
        {"placeId": "1", "title": "Acme, Clinic", "website": "https://www.acme.co.uk/a"},
        {"placeId": "2", "title": "Other Branch", "website": "https://sub.acme.co.uk/b"},
        {"placeId": "3", "title": " ACME clinic ", "website": "https://another-domain.com"},
        {"placeId": "4", "title": "Independent", "website": "https://independent.com"},
        {"placeId": "5", "title": "No website"},
        {"placeId": "6", "title": "no WEBSITE"},
    ]))
    assert [business.business_name for business in businesses] == ["Acme, Clinic", "Independent", "No website"]
    assert [business.business_domain for business in businesses] == ["acme.co.uk", "independent.com", None]
    assert len(businesses[0].original["duplicate_records"]) == 2


def test_duplicate_name_prefers_usable_website_and_keeps_unknowns_separate():
    businesses = unique_companies(deduplicate_businesses([
        {"placeId": "1", "title": "Clinic"},
        {"placeId": "2", "title": "Clinic", "website": "https://clinic.com"},
        {"placeId": "3"}, {"placeId": "4"},
    ]))
    assert len(businesses) == 3 and businesses[0].business_domain == "clinic.com"


def test_executive_metadata_prioritized_over_management():
    contacts = [person("staff@x.com", "Staff"), person("manager@x.com", "Practice Manager"),
                person("executive@x.com", "COO", seniority="executive", decision_maker=True),
                person("ceo@x.com", "CEO"), Contact(email="info@x.com", provider_type="generic")]
    assert [contact.email for contact, _ in rank_candidates(contacts)] == [
        "ceo@x.com", "executive@x.com", "manager@x.com", "info@x.com",
    ]
