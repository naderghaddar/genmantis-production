import csv
import io
import json
from unittest.mock import MagicMock

import httpx
import pytest

from app.models.leads import Business, CheckedContact, Contact, Lead, Verification
from app.services.apify_service import ApifyService
from app.services.csv_service import CONTACT_COLUMNS, LEAD_COLUMNS, generate_contacts_csv, generate_leads_csv, safe_cell
from app.services.enrichment_pipeline import EnrichmentPipeline, PipelineFailure
from app.services.hunter_service import HunterService
from app.services.neverbounce_service import NeverBounceService
from app.services.provider_http import ProviderHTTP


def csv_rows(content):
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


def test_complete_pipeline_partial_failure_and_caches(settings, search_request, sdk):
    calls, updates = [], []
    def handler(request):
        calls.append(request)
        if request.url.host == "api.hunter.io":
            if request.url.params["domain"] == "failed.com":
                return httpx.Response(403, json={"errors": [{"id": "no_domain_search_access"}]})
            return httpx.Response(200, json={"data": {"domain": "clinic.co.uk", "emails": [
                {"value": "owner@clinic.co.uk", "position": "Owner", "first_name": "Jane", "last_name": "Doe",
                 "phone_number": "person phone", "linkedin": "https://linkedin.com/in/jane", "decision_maker": True},
                {"value": "info@clinic.co.uk", "type": "generic"},
            ]}, "meta": {"results": 2}})
        assert request.url.host == "api.neverbounce.com"
        return httpx.Response(200, json={"status": "success", "result": "valid", "flags": ["has_dns"]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        pipeline = EnrichmentPipeline(settings, ApifyService(sdk),
            HunterService(ProviderHTTP(client, "hunter", interval=0), "key"),
            NeverBounceService(ProviderHTTP(client, "neverbounce", interval=0), "key"))
        exports = pipeline.run("run123", search_request, lambda **values: updates.append(values))
    all_rows = csv_rows(exports["all"][0])
    verified = csv_rows(exports["verified"][0])
    assert len(all_rows) == 3 and len(verified) == 1
    assert list(verified[0]) == CONTACT_COLUMNS
    assert [row["email"] for row in verified] == ["owner@clinic.co.uk"]
    assert [row["business_name"] for row in all_rows] == ["North", "No site", "Provider error"]
    assert all_rows[1]["enrichment_status"] == "no_website"
    assert all_rows[2]["enrichment_status"] == "hunter_error"
    assert all_rows[2]["failure_reason"] == "hunter_no_domain_search_access"
    assert all_rows[0]["contact_phone"] == "person phone"
    assert all_rows[0]["business_phone"] == "business phone"
    assert all_rows[1]["business_phone"] == ""
    assert all_rows[0]["contact_linkedin"] == "https://linkedin.com/in/jane"
    assert all_rows[0]["shared_domain"] == "False"
    assert "not established" in all_rows[0]["contact_scope"]
    assert json.loads(all_rows[0]["original_business_data"])["duplicate_records"][0]["additional"] == "retained"
    assert sum(call.url.host == "api.hunter.io" for call in calls) == 2
    assert sum(call.url.host == "api.neverbounce.com" for call in calls) == 1
    sdk.actor.return_value.start.assert_called_once()
    assert exports["verified"][1] == "chiropractors_austin_texas_verified_leads.csv"
    assert exports["all"][1] == "chiropractors_austin_texas_all_results.csv"
    stages = [update["status"] for update in updates if "status" in update]
    assert stages == ["scraping", "enriching", "verifying", "exporting"]
    final = updates[-1]["progress"]
    assert final.businesses_scraped == final.businesses_processed == 3
    assert final.domains_searched == 2 and final.contacts_found == 2
    assert final.verified_emails == 1 and final.businesses_without_contact == 2 and final.failed_enrichments == 1


def test_failed_apify_stops_before_enrichment(settings, search_request, sdk):
    sdk.run.return_value.get.return_value["status"] = "FAILED"
    hunter, nb = MagicMock(), MagicMock()
    with pytest.raises(PipelineFailure, match="Scraping failed"):
        EnrichmentPipeline(settings, ApifyService(sdk), hunter, nb).run("run123", search_request, lambda **_: None)
    hunter.search.assert_not_called()
    nb.verify.assert_not_called()
    sdk.actor.return_value.start.assert_called_once()


def test_failed_start_never_retried(settings, search_request, sdk):
    sdk.actor.return_value.start.side_effect = RuntimeError("private credentials")
    with pytest.raises(PipelineFailure, match="Check Apify Console") as error:
        EnrichmentPipeline(settings, ApifyService(sdk), MagicMock(), MagicMock()).run("run123", search_request, lambda **_: None)
    assert "private" not in str(error.value)
    sdk.actor.return_value.start.assert_called_once()


def test_empty_apify_run_exports_headers_without_calls(settings, search_request, sdk):
    sdk.dataset.return_value.get.return_value = {"itemCount": 0}
    sdk.dataset.return_value.iterate_items.return_value = iter([])
    hunter, nb = MagicMock(), MagicMock()
    updates = []
    exports = EnrichmentPipeline(settings, ApifyService(sdk), hunter, nb).run("run123", search_request, lambda **values: updates.append(values))
    assert csv_rows(exports["all"][0]) == csv_rows(exports["verified"][0]) == []
    assert exports["all"][0].startswith(b"\xef\xbb\xbf")
    assert updates[-1]["progress"].businesses_processed == 0
    hunter.search.assert_not_called()
    nb.verify.assert_not_called()


@pytest.mark.parametrize("value", ["=1+1", "+SUM(1)", "-SUM(1)", "@SUM(1)", "  =CMD()", "\tplain", "\rplain", "\nplain"])
def test_formula_protection(value):
    assert safe_cell(value) == "'" + value


def test_csv_columns_nested_unicode_and_verified_filter():
    valid = Lead(business=Business(business_name='Caf\u00e9, "Clinic"', business_phone="+15550000", original={"nested": {"data": ["\u00e9"]}}),
                 contact=Contact(email="info@x.com", raw={"type": "generic"}), contact_type="generic",
                 verification=Verification(result="valid", flags=["role_account"]), verified=True, run_id="run123")
    unverified = Lead(business=Business(business_name="=HYPERLINK()"), contact=Contact(email="owner@x.com"),
                      verification=Verification(result="catchall"), verified=False, run_id="run123")
    # Defensive filter refuses inconsistent verified booleans.
    wrong = unverified.model_copy(update={"verified": True})
    verified = csv_rows(generate_leads_csv([valid, unverified, wrong], True))
    all_rows = csv_rows(generate_leads_csv([valid, unverified]))
    assert len(verified) == 1 and verified[0]["contact_type"] == "generic"
    assert len(all_rows) == 2 and all_rows[1]["business_name"] == "'=HYPERLINK()"
    assert verified[0]["business_phone"] == "'+15550000"
    assert all_rows[0]["business_name"] == 'Caf\u00e9, "Clinic"'
    assert json.loads(all_rows[0]["original_business_data"])["nested"]["data"] == ["\u00e9"]
    assert list(all_rows[0]) == list(all_rows[1])


def test_hunter_contact_csv_exact_columns_order_values_and_missing_fields():
    def checked(email, result, **metadata):
        return CheckedContact(company_domain=email.split("@")[0] + ".com", contact=Contact(email=email, **metadata),
                              verification=Verification(result=result))
    contacts = [
        checked("temporary@clinic.co.uk", "disposable"),
        checked("bad@clinic.co.uk", "invalid"),
        checked("maybe@clinic.co.uk", "unknown"),
        checked("owner@clinic.co.uk", "valid", first_name="Jane", last_name='Doe, "Jr"', job_title="Owner",
                phone="+15551234567", linkedin="https://linkedin.com/in/jane", twitter="jane"),
        checked("catch@clinic.co.uk", "catchall"),
        checked("apierror@clinic.co.uk", "verification_error"),
        checked("owner@clinic.co.uk", "valid"),
    ]
    rows = csv_rows(generate_contacts_csv(contacts))
    assert list(rows[0]) == ["first name", "last name", "company domain", "title", "email", "phone number", "linkedin", "twitter", "email_status"]
    assert [row["email_status"] for row in rows] == ["valid", "catchall", "unknown", "", "disposable"]
    assert all(row["email"] != "bad@clinic.co.uk" for row in rows)
    assert rows[0] == {"first name": "Jane", "last name": 'Doe, "Jr"', "company domain": "owner.com",
                       "title": "Owner", "email": "owner@clinic.co.uk", "phone number": "'+15551234567",
                       "linkedin": "https://linkedin.com/in/jane", "twitter": "jane", "email_status": "valid"}
    assert rows[1]["first name"] == rows[1]["phone number"] == ""
    assert csv_rows(generate_contacts_csv([checked("bad@clinic.co.uk", "invalid")])) == []


def test_contact_export_selects_one_contact_and_skips_duplicate_domain(settings, search_request, sdk):
    from dataclasses import replace
    from app.services.hunter_service import HunterSearch
    sdk.dataset.return_value.iterate_items.return_value = iter([
        {"placeId": "1", "title": "North", "website": "https://clinic.co.uk", "phone": "business phone"},
        {"placeId": "2", "title": "South", "website": "https://clinic.co.uk"},
    ])
    outcomes = {"owner": "valid", "staff": "catchall", "associate": "unknown", "temp": "disposable", "bad": "invalid", "failed": "verification_error"}
    contacts = [Contact(email=name + "@clinic.co.uk", job_title="Owner" if name == "owner" else "Employee", first_name=name)
                for name in outcomes]
    hunter, nb = MagicMock(), MagicMock()
    hunter.search.return_value = HunterSearch(contacts=contacts)
    nb.verify.side_effect = lambda email: Verification(result=outcomes[email.split("@")[0]])
    pipeline = EnrichmentPipeline(replace(settings, max_verification_attempts=1), ApifyService(sdk), hunter, nb)
    exports = pipeline.run("run123", search_request, lambda **_: None)
    rows = csv_rows(exports["verified"][0])
    assert [row["email_status"] for row in rows] == ["valid"]
    assert len(rows) == 1
    nb.verify.assert_called_once_with("owner@clinic.co.uk")
    hunter.search.assert_called_once_with("clinic.co.uk")
    all_rows = csv_rows(exports["all"][0])
    assert len(all_rows) == 1 and list(all_rows[0]) == LEAD_COLUMNS
    assert [row["business_name"] for row in all_rows] == ["North"]
    assert all(row["contact_email"] == "owner@clinic.co.uk" and row["verified"] == "True" for row in all_rows)
    assert all(len(json.loads(row["verification_attempts"])) == 1 for row in all_rows)


def test_duplicate_company_names_are_not_sent_to_hunter(settings, search_request, sdk):
    from app.services.hunter_service import HunterSearch
    sdk.dataset.return_value.iterate_items.return_value = iter([
        {"placeId": "1", "title": "Example Clinic", "website": "https://first.com"},
        {"placeId": "2", "title": "  EXAMPLE, CLINIC ", "website": "https://second.com"},
    ])
    hunter, nb = MagicMock(), MagicMock()
    hunter.search.return_value = HunterSearch(contacts=[Contact(email="ceo@first.com", job_title="CEO")])
    nb.verify.return_value = Verification(result="valid")
    exports = EnrichmentPipeline(settings, ApifyService(sdk), hunter, nb).run("run123", search_request, lambda **_: None)
    hunter.search.assert_called_once_with("first.com")
    nb.verify.assert_called_once_with("ceo@first.com")
    assert len(csv_rows(exports["all"][0])) == len(csv_rows(exports["verified"][0])) == 1


def test_no_hunter_contact_exports_zero_leads_and_makes_no_verification_calls(settings, search_request, sdk):
    from app.services.hunter_service import HunterSearch
    sdk.dataset.return_value.iterate_items.return_value = iter([{"title": "Clinic", "website": "https://first.com"}])
    hunter, nb = MagicMock(), MagicMock()
    hunter.search.return_value = HunterSearch()
    exports = EnrichmentPipeline(settings, ApifyService(sdk), hunter, nb).run("run123", search_request, lambda **_: None)
    assert csv_rows(exports["verified"][0]) == []
    assert csv_rows(exports["all"][0])[0]["enrichment_status"] == "no_email_found"
    nb.verify.assert_not_called()


def test_generic_selected_only_when_no_decision_maker_is_available(settings, search_request, sdk):
    from app.services.hunter_service import HunterSearch
    sdk.dataset.return_value.iterate_items.return_value = iter([{"title": "Clinic", "website": "https://first.com"}])
    hunter, nb = MagicMock(), MagicMock()
    hunter.search.return_value = HunterSearch(contacts=[
        Contact(email="staff@first.com", job_title="Receptionist"),
        Contact(email="info@first.com", provider_type="generic"),
        Contact(email="support@first.com", provider_type="generic"),
    ])
    nb.verify.return_value = Verification(result="catchall")
    exports = EnrichmentPipeline(settings, ApifyService(sdk), hunter, nb).run("run123", search_request, lambda **_: None)
    rows = csv_rows(exports["verified"][0])
    assert len(rows) == 1 and rows[0]["email"] == "info@first.com" and rows[0]["email_status"] == "catchall"
