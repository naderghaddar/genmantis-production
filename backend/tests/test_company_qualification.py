import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.agents.research_agent import ResearchAgent
from app.models.leads import Business, Contact, Verification
from app.models.workspace import AdvisorMessage, CampaignPlan
from app.services.apify_service import ApifyService, build_actor_input
from app.services.business_service import normalize_business
from app.services.campaign_service import CampaignService
from app.services.company_qualification import matches_niche, official_domain_basis, contact_matches_domain
from app.services.domain_service import extract_domain
from app.services.hunter_service import HunterService
from app.services.provider_http import ProviderHTTP
from app.services.research_service import ResearchService
from app.services.workspace_store import WorkspaceStore


@pytest.mark.parametrize("category,categories,expected", [
    ("Chiropractor", [], True),
    ("Medical clinic", ["Medical clinic", "Chiropractor"], True),
    ("Public university", [], False),
    ("Orthopedic shoe store", [], False),
    ("Physical therapy clinic", [], False),
    (None, [], False),
])
def test_niche_requires_category_evidence(category, categories, expected):
    business = normalize_business({"title": "Chiropractors search result", "categoryName": category, "categories": categories})
    assert matches_niche(business, "Chiropractors") is expected


@pytest.mark.parametrize("website", ["https://healthline.com/find-care/provider/a", "https://doctor.webmd.com/doctor/a", "https://massagebook.com/therapists/a"])
def test_directory_urls_are_not_company_domains(website):
    assert extract_domain(website)[1:] == (None, "excluded_domain")


def test_identity_and_email_affiliation_require_evidence():
    business = Business(business_name="Cardinal Chiropractic", business_category="Chiropractor")
    assert official_domain_basis(business, "cardinalchiro.com") == "business_brand_matches_domain"
    assert official_domain_basis(business, "unrelated.com", "Different Company") is None
    assert official_domain_basis(business, "ccmuncie.com", "Cardinal Chiropractic LLC") == "hunter_organization_matches_business"
    assert contact_matches_domain(Contact(email="pat@cardinalchiro.com"), "cardinalchiro.com")
    assert contact_matches_domain(Contact(email="pat@branch.cardinalchiro.com"), "cardinalchiro.com")
    assert not contact_matches_domain(Contact(email="pat@other.com"), "cardinalchiro.com")
    assert not contact_matches_domain(Contact(email="pat@gmail.com"), "cardinalchiro.com")


def test_real_hunter_path_rejects_observed_bad_results_before_email_spend(settings, monkeypatch):
    """Reproduce university, store, directory, wrong city/company/email failures."""
    store = WorkspaceStore(":memory:")
    service = CampaignService(settings, store)
    user = store.identity("regression")
    rows = [
        {"title": "Cooper Science Building", "categoryName": "Public university", "website": "https://bsu.edu/biology"},
        {"title": "The Good Feet Store", "categoryName": "Orthopedic shoe store", "website": "https://goodfeet.com/stores/florence"},
        {"title": "Spaulding Clinic", "categoryName": "Chiropractor", "website": "https://healthline.com/find-care/provider/richard-spaulding"},
        {"title": "Acme Chiropractic", "categoryName": "Chiropractor", "website": "https://unrelated.com"},
        {"title": "Cross Chiropractic", "categoryName": "Chiropractor", "website": "https://crosschiro.com"},
        {"title": "Nearby Chiropractic", "categoryName": "Chiropractor", "website": "https://nearbychiro.com", "city": "Union"},
        {"title": "Cardinal Chiropractic", "categoryName": "Chiropractor", "website": "https://cardinalchiro.com"},
        {"title": "Acme Medical", "categoryName": "Medical clinic", "categories": ["Medical clinic", "Chiropractor"], "website": "https://acmemedical.com"},
    ]
    service._discover = lambda *args: [dict(rank=18, searchString="Chiropractors",
        searchPageUrl="https://www.google.com/maps/search/Chiropractors", isAdvertisement=False, **row) for row in rows]
    queried = []

    def handler(request):
        domain = request.url.params["domain"]
        queried.append(domain)
        email_domain = "unaffiliated.com" if domain == "crosschiro.com" else domain
        return httpx.Response(200, json={"data": {"domain": domain, "organization": "Different Company",
            "emails": [{"value": "owner@" + email_domain, "first_name": "Pat", "position": "Owner", "type": "personal"}]},
            "meta": {"results": 1}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        hunter = HunterService(ProviderHTTP(client, "hunter", interval=0), "test-key")
        monkeypatch.setattr("app.services.campaign_service.HunterService", lambda *args: hunter)
        verifier = MagicMock(); verifier.verify.return_value = Verification(result="valid")
        monkeypatch.setattr("app.services.campaign_service.NeverBounceService", lambda *args: verifier)
        plan = CampaignPlan(name="Chiropractor regression", source="google_maps", niche="Chiropractors",
            city="Muncie", state="Indiana", max_leads=50, research_websites=False, min_google_maps_rank=12)
        campaign = service.create(user, plan)
        try:
            service._run(user, campaign, Event())
            records = store.list(user, "lead")
            assert {row["domain"] for row in records} == {"cardinalchiro.com", "acmemedical.com"}
            assert campaign["progress"]["verified"] == 2
            assert set(queried) == {"unrelated.com", "crosschiro.com", "cardinalchiro.com", "acmemedical.com"}
            assert verifier.verify.call_count == 2
            assert campaign["diagnostics"]["counts"]["company_niche_excluded"] == 2
            assert campaign["diagnostics"]["counts"]["company_identity_unconfirmed"] == 1
            assert campaign["diagnostics"]["counts"]["company_location_excluded"] == 1
            assert campaign["diagnostics"]["counts"]["candidate_domain_mismatch"] == 1
            assert all(row["lead"]["company_validation"]["contact_affiliation"] == "email_matches_company_domain" for row in records)
        finally:
            service.close(); store.close()


def test_apify_100_places_categories_and_geography(sdk):
    from app.models.schemas import ScrapeRequest
    request = ScrapeRequest(niche="Chiropractors", city="Muncie", state="Indiana")
    service = ApifyService(sdk)
    service.start(request)
    first = sdk.actor.return_value.start.call_args.kwargs["run_input"]
    assert first["maxCrawledPlacesPerSearch"] == 100
    assert first["categoryFilterWords"] == ["chiropractor"]
    service.start(request, business_limit=300)
    deeper = sdk.actor.return_value.start.call_args.kwargs["run_input"]
    assert deeper["maxCrawledPlacesPerSearch"] == 300
    assert deeper["locationQuery"] == first["locationQuery"] == "Muncie, Indiana"
    assert deeper["categoryFilterWords"] == first["categoryFilterWords"]
    assert "categoryFilterWords" not in build_actor_input(ScrapeRequest(niche="specialist widget makers", city="Muncie", state="Indiana"))


def test_cancellation_aborts_existing_apify_actor(settings, monkeypatch):
    store = WorkspaceStore(":memory:"); service = CampaignService(settings, store)
    cancel = Event(); provider = MagicMock()
    def start(*args, **kwargs):
        cancel.set()
        return SimpleNamespace(run_id="existing-run", status="running")
    provider.start.side_effect = start
    monkeypatch.setattr("app.services.campaign_service.ApifyService", lambda *args: provider)
    plan = CampaignPlan(name="Cancel", source="google_maps", niche="Chiropractors", city="Muncie", state="Indiana")
    campaign = service.create(store.identity("owner"), plan)
    campaign["locations"] = [{"business_limit": 100}]
    try:
        with pytest.raises(InterruptedError):
            service._discover(plan, campaign, store.identity("owner"), cancel, None)
        provider.start.assert_called_once()
        provider.abort.assert_called_once_with("existing-run")
        assert campaign["diagnostics"]["counts"]["apify_abort_requested"] == 1
    finally:
        service.close(); store.close()


def test_new_conversation_cannot_inherit_niche_from_other_campaigns(settings, monkeypatch):
    store = WorkspaceStore(":memory:"); campaigns = CampaignService(settings, store)
    user = store.identity("owner")
    agent = ResearchAgent(replace(settings, openai_key="test"), store, campaigns)
    prior = campaigns.create(user, CampaignPlan(name="Prior chiropractors", source="google_maps", niche="Chiropractors", city="Muncie", state="Indiana"))
    thread = agent.create(user)
    thread["messages"] = [{"role": "user", "content": "Find 50 qualified leads in Muncie Indiana", "id": "brief", "at": "now"}]
    store.save(user, "thread", thread)
    try:
        args = prior["plan"]
        result = agent.execute("generate_leads", args, user, None, [], thread_id=thread["id"])
        assert "niche is not established" in result["error"]
        assert len(store.list(user, "campaign")) == 1
        client = MagicMock(); client.__enter__.return_value = client
        client.responses.create.return_value = SimpleNamespace(status="completed", output=[], output_text="Which niche?", usage=None)
        monkeypatch.setattr(ResearchService, "client", lambda self: client)
        agent.message(user, thread["id"], AdvisorMessage(message="Find 50 leads", message_id="second"))
        context = client.responses.create.call_args.kwargs["input"]
        assert "Prior chiropractors" not in json.dumps(context)
        # An explicit niche in this conversation is sufficient, including plural normalization.
        thread["messages"].append({"role": "user", "content": "Use chiropractors", "id": "niche", "at": "now"})
        store.save(user, "thread", thread)
        campaigns.start = MagicMock(side_effect=lambda identity, record_id, version: store.get(identity, "campaign", record_id))
        assert "campaign_id" in agent.execute("generate_leads", args, user, None, [], thread_id=thread["id"])
    finally:
        campaigns.close(); store.close()
