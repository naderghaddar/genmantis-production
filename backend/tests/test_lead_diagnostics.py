import json
import logging
from threading import Event
from unittest.mock import MagicMock

import httpx
import pytest

from app.models.leads import Verification
from app.models.workspace import CampaignPlan
from app.services.campaign_service import CampaignService
from app.services.hunter_service import HunterService
from app.services.provider_http import ProviderHTTP
from app.services.workspace_store import WorkspaceStore


def events(caplog):
    return [json.loads(record.getMessage().removeprefix("lead_funnel "))
            for record in caplog.records if record.getMessage().startswith("lead_funnel ")]


def place(name, website=None, rank=20):
    return {"title": name, "website": website, "rank": rank, "searchString": "clinics",
            "searchPageUrl": "https://www.google.com/maps/search/clinics", "isAdvertisement": False}


def test_real_hunter_funnel_explains_low_yield_without_changing_fallback(settings, tmp_path, monkeypatch, caplog):
    """Exercise the actual Hunter parser/filter sequence, not a mock returning eligible people."""
    store = WorkspaceStore(str(tmp_path / "diagnostics.sqlite3"))
    service = CampaignService(settings, store)
    user = store.identity("diagnostic-test")
    calls = []

    def handler(request):
        domain = request.url.params["domain"]
        calls.append((domain, dict(request.url.params)))
        emails = []
        if domain in {"unnamed-clinic.com", "invalid-clinic.com", "good-clinic.com"}:
            emails = [{"value": "private-person@" + domain, "position": "Owner"}]
            if domain != "unnamed-clinic.com":
                emails[0]["first_name"] = "Private Name"
        elif domain == "generic-clinic.com" and request.url.params.get("type") == "generic":
            emails = [{"value": "info@" + domain, "type": "generic"}]
        elif domain == "ordinary-clinic.com":
            emails = [{"value": "employee@" + domain, "first_name": "Employee", "position": "Receptionist"}]
        return httpx.Response(200, json={"data": {"emails": emails}, "meta": {"results": len(emails)}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        hunter = HunterService(ProviderHTTP(client, "hunter", interval=0), "private-api-key")
        monkeypatch.setattr("app.services.campaign_service.HunterService", lambda *args: hunter)
        verifier = MagicMock()
        verifier.verify.side_effect = lambda email: Verification(result="invalid" if "invalid-clinic" in email else "valid")
        monkeypatch.setattr("app.services.campaign_service.NeverBounceService", lambda *args: verifier)
        service._discover = lambda *args: [
            place("Missing website"), place("Social", "https://facebook.com/clinic"),
            place("Malformed", "not a website"), place("Unknown rank", "https://unknown-rank.com", None),
            place("Top ten", "https://top-ten.com", 3), place("Empty", "https://empty-clinic.com"),
            place("Generic", "https://generic-clinic.com"), place("Ordinary", "https://ordinary-clinic.com"),
            place("Unnamed", "https://unnamed-clinic.com"), place("Invalid", "https://invalid-clinic.com"),
            place("Good", "https://good-clinic.com"),
        ]
        campaign = service.create(user, CampaignPlan(name="Funnel", source="google_maps", niche="clinics",
            city="Austin", state="Texas", max_leads=20, research_websites=False, min_google_maps_rank=11))
        try:
            with caplog.at_level(logging.INFO, logger="uvicorn.error.lead_funnel"):
                service._run(user, campaign, Event())
            counts = campaign["diagnostics"]["counts"]
            assert counts["company_no_domain"] == 3
            assert campaign["diagnostics"]["reasons"]["company_no_domain"] == {
                "no_website": 1, "invalid_website": 1, "excluded_domain": 1}
            assert counts["company_rank_excluded"] == 2
            assert counts["company_no_eligible_contact"] == 4
            assert counts["candidate_verification"] == 2
            assert counts["lead_saved"] == 1
            assert campaign["progress"]["verified"] == 1
            assert campaign["progress"]["no_contact"] == 7
            logged = events(caplog)
            assert {e["reason"] for e in logged if e["event"] == "company_no_domain"} == {
                "no_website", "invalid_website", "excluded_domain"}
            assert {e["reason"] for e in logged if e["event"] == "company_rank_excluded"} == {
                "rank_below_requested_minimum", "ranking_unknown_or_organic_search_context_unavailable"}
            unnamed = next(e for e in logged if e["event"] == "hunter_filter_result" and e["domain"] == "unnamed-clinic.com")
            assert unnamed["decision"] == "stop_ranked_contacts" and unnamed["eligible_people"] == 0
            assert unnamed["remaining_filters"] == 3
            assert len([c for c in calls if c[0] == "unnamed-clinic.com"]) == 1
            assert len([c for c in calls if c[0] == "invalid-clinic.com"]) == 1
            assert len([c for c in calls if c[0] == "empty-clinic.com"]) == 4
            assert store.get(user, "campaign", campaign["id"])["diagnostics"] == campaign["diagnostics"]
            assert "private-person" not in caplog.text and "Private Name" not in caplog.text
            assert "private-api-key" not in caplog.text
            assert logged[-1]["event"] == "campaign_finished"
        finally:
            service.close()
            store.close()


@pytest.mark.parametrize("mode", ["truncated", "provider_error"])
def test_hunter_diagnostics_capture_limits_and_errors(mode, caplog):
    def handler(request):
        if mode == "provider_error":
            return httpx.Response(401, json={"message": "private-provider-detail"})
        return httpx.Response(200, json={"data": {"emails": [{"value": "private@clinic.com", "position": "Owner"}]},
                                        "meta": {"results": 50}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        hunter = HunterService(ProviderHTTP(client, "hunter", retries=0, interval=0), "private-key")
        with caplog.at_level(logging.INFO, logger="uvicorn.error.lead_funnel"):
            hunter.search("clinic.com")
    logged = events(caplog)
    if mode == "truncated":
        page = next(e for e in logged if e["event"] == "hunter_page_result")
        assert page["truncated"] is True and page["provider_total"] == 50
    else:
        assert logged[0]["reason"] == "hunter_authentication_error"
        assert logged[-1]["decision"] == "stop_provider_reason"
    assert "private@" not in caplog.text and "private-key" not in caplog.text
    assert "private-provider-detail" not in caplog.text


@pytest.mark.parametrize("named_contacts", [12, 240])
def test_300_company_yield_depends_on_real_provider_fields(settings, monkeypatch, caplog, named_contacts):
    """Compare 4% and 80% yield with the same real parsing/selection path and no paid calls."""
    store = WorkspaceStore(":memory:")
    service = CampaignService(settings, store)
    user = store.identity("volume-test")
    api_calls = []

    def handler(request):
        domain = request.url.params["domain"]
        index = int(domain.removeprefix("clinic").removesuffix(".com"))
        api_calls.append(domain)
        contact = {"value": "owner@" + domain, "position": "Owner", "type": "personal"}
        if index < named_contacts:
            contact["first_name"] = "Pat"
        return httpx.Response(200, json={"data": {"emails": [contact]}, "meta": {"results": 1}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        hunter = HunterService(ProviderHTTP(client, "hunter", interval=0), "test-key")
        monkeypatch.setattr("app.services.campaign_service.HunterService", lambda *args: hunter)
        verifier = MagicMock()
        verifier.verify.return_value = Verification(result="valid")
        monkeypatch.setattr("app.services.campaign_service.NeverBounceService", lambda *args: verifier)
        service._discover = lambda local, *args: [place(str(i), f"https://clinic{i}.com")
            for i in range(int(local.city) * 60, (int(local.city) + 1) * 60)]
        campaign = service.create(user, CampaignPlan(name="300 company comparison", source="google_maps",
            niche="clinics", locations=[{"city": str(i), "state": "Test"} for i in range(5)],
            max_leads=300, research_websites=False))
        try:
            with caplog.at_level(logging.INFO, logger="uvicorn.error.lead_funnel"):
                service._run(user, campaign, Event())
            assert campaign["progress"]["discovered"] == campaign["progress"]["processed"] == 300
            assert campaign["progress"]["verified"] == named_contacts
            assert len(api_calls) == 300  # owner result prevents every broader query
            assert verifier.verify.call_count == named_contacts
            stopped_without_people = [e for e in events(caplog) if e["event"] == "hunter_filter_result"
                and e["decision"] == "stop_ranked_contacts" and e["eligible_people"] == 0]
            assert len(stopped_without_people) == 300 - named_contacts
            assert campaign["diagnostics"]["counts"]["company_no_eligible_contact"] == 300 - named_contacts
        finally:
            service.close()
            store.close()
