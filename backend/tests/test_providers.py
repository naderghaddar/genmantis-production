import httpx
import pytest

from app.services.hunter_service import HunterService, parse_contact
from app.services.neverbounce_service import NeverBounceService
from app.services.provider_http import ProviderError, ProviderHTTP


def transport(handler, provider="hunter", retries=2):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ProviderHTTP(client, provider, retries=retries, interval=0, sleep=lambda _: None)


def response(request, code=200, **payload):
    return httpx.Response(code, json=payload, request=request)


def test_hunter_parsing():
    item = {"value": "owner@x.com", "first_name": "Jane", "last_name": "Doe", "position_raw": "Owner",
            "linkedin": "https://linkedin.com/in/jane", "phone_number": "person phone", "decision_maker": True,
            "sources": [{"uri": "https://x.com/about"}], "verification": {"status": "valid"}}
    contact = parse_contact(item)
    assert contact.linkedin == item["linkedin"] and contact.phone == "person phone"
    assert contact.job_title == "Owner" and contact.raw == item
    assert parse_contact({"value": "bad value"}) is None
    assert parse_contact({"value": "info@x.com", "linkedin_url": "present"}).linkedin == "present"


def test_hunter_header_pagination():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["X-API-KEY"] == "test-key"
        assert "api_key" not in request.url.params
        offset = int(request.url.params["offset"])
        return response(request, data={"emails": [{"value": f"person{i}@x.com", "position": "Owner"} for i in range(offset, offset + 10)]}, meta={"results": 20})
    found = HunterService(transport(handler), "test-key", 20, 2).search("x.com")
    assert len(found.contacts) == 20 and found.reason is None
    assert [int(call.url.params["offset"]) for call in calls] == [0, 10]
    assert all(int(call.url.params["limit"]) == 10 for call in calls)


@pytest.mark.parametrize("code,error_id,expected", [(400, "pagination_error", "hunter_pagination_error"), (429, "too_many_requests", "hunter_quota_exhausted")])
def test_hunter_preserves_partial_results(code, error_id, expected):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return response(request, data={"emails": [{"value": f"owner{i}@x.com", "position": "Owner"} for i in range(10)]}, meta={"results": 20})
        return response(request, code, errors=[{"id": error_id, "details": "do not expose this"}])
    found = HunterService(transport(handler), "test-key", 20, 2).search("x.com")
    assert len(found.contacts) == 10 and found.reason == expected and len(calls) == 2


def test_hunter_privacy_suppression_discards_partial_contacts():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return response(request, data={"emails": [{"value": "owner@x.com", "position": "Owner"}]}, meta={"results": 20})
        return response(request, 451, errors=[{"id": "privacy_denial"}])
    found = HunterService(transport(handler), "test-key", 20, 2).search("x.com")
    assert not found.contacts and found.reason == "hunter_privacy_suppressed"


def test_search_cap_and_no_emails():
    found = HunterService(transport(lambda r: response(r, data={"emails": [{"value": "a@x.com"}]}, meta={"results": 20})), "key").search("x.com")
    assert found.reason == "hunter_search_limit_reached"
    empty = HunterService(transport(lambda r: response(r, data={"emails": []}, meta={"results": 0})), "key").search("x.com")
    assert empty.contacts == [] and empty.reason is None


@pytest.mark.parametrize("result", ["valid", "invalid", "disposable", "catchall", "unknown"])
def test_neverbounce_response_and_encoded_alias(result):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.params["email"] == "owner+alias@x.com"
        assert "%2B" in str(request.url)
        assert request.url.params["key"] == "test-key"
        return response(request, status="success", result=result, flags=["has_dns"], suggested_correction="")
    verified = NeverBounceService(transport(handler, "neverbounce"), "test-key").verify("owner+alias@x.com")
    assert verified.result == result and verified.flags == ["has_dns"] and len(calls) == 1


@pytest.mark.parametrize("code", [429, 500, 503])
def test_transient_retries(code):
    calls = []
    def handler(request):
        calls.append(request)
        return response(request, code) if len(calls) < 3 else response(request, status="success", result="valid")
    assert NeverBounceService(transport(handler, "neverbounce"), "key").verify("a@x.com").result == "valid"
    assert len(calls) == 3


def test_network_failure_is_bounded_and_safe():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private URL and key", request=request)
    result = NeverBounceService(transport(handler, "neverbounce"), "key").verify("a@x.com")
    assert result.result == "verification_error" and result.failure_reason == "neverbounce_network_error"
    assert len(calls) == 3


def test_quota_halts_future_provider_calls():
    calls = []
    def handler(request):
        calls.append(request)
        return response(request, status="insufficient_credit")
    service = NeverBounceService(transport(handler, "neverbounce"), "key")
    assert service.verify("a@x.com").result == "verification_error"
    assert service.verify("b@x.com").failure_reason == "neverbounce_quota_exhausted"
    assert len(calls) == 1


def test_auth_failure_does_not_retry_or_expose_details():
    calls = []
    def handler(request):
        calls.append(request)
        return response(request, 401, message="private credential")
    result = NeverBounceService(transport(handler, "neverbounce"), "key").verify("a@x.com")
    assert result.result == "verification_error" and len(calls) == 1
    assert "private" not in result.failure_reason


def test_retry_after_long_cooldown_not_retried_early():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={}, headers={"Retry-After": "120"}, request=request)
    result = NeverBounceService(transport(handler, "neverbounce"), "key").verify("a@x.com")
    assert result.failure_reason == "neverbounce_rate_limit_cooldown" and len(calls) == 1


def test_unrecognized_response_never_becomes_valid():
    service = NeverBounceService(transport(lambda r: response(r, status="success", result="something else"), "neverbounce"), "key")
    assert service.verify("a@x.com").result == "verification_error"


@pytest.mark.parametrize("status", ["temp_unavail", "throttle_triggered"])
def test_documented_neverbounce_temporary_statuses(status):
    calls = []
    def handler(request):
        calls.append(request)
        return response(request, status=status) if len(calls) < 3 else response(request, status="success", result="valid")
    assert NeverBounceService(transport(handler, "neverbounce"), "key").verify("a@x.com").result == "valid"
    assert len(calls) == 3


def test_neverbounce_general_failure_is_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        return response(request, status="general_failure", message="Missing required parameter")
    result = NeverBounceService(transport(handler, "neverbounce"), "key").verify("a@x.com")
    assert result.result == "verification_error" and result.failure_reason == "neverbounce_request_error"
    assert len(calls) == 1


def test_neverbounce_credit_error_in_successful_http_response():
    calls = []
    def handler(request):
        calls.append(request)
        return response(request, status="general_failure", message="Insufficient credits")
    service = NeverBounceService(transport(handler, "neverbounce"), "key")
    assert service.verify("a@x.com").failure_reason == "neverbounce_quota_exhausted"
    assert service.verify("b@x.com").result == "verification_error"
    assert len(calls) == 1


def test_httpx_request_logs_redact_credentials_and_email(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="httpx"):
        service = NeverBounceService(transport(lambda r: response(r, status="success", result="valid"), "neverbounce"), "private-key-value")
        service.verify("private-person@x.com")
    assert "private-key-value" not in caplog.text
    assert "private-person" not in caplog.text
    assert "REDACTED" in caplog.text


def test_hunter_queries_priority_roles_before_generic():
    calls = []
    def handler(request):
        calls.append(dict(request.url.params))
        if request.url.params.get("type") == "generic":
            return response(request, data={"emails": [{"value": "info@x.com", "type": "generic"}]}, meta={"results": 1})
        return response(request, data={"emails": []}, meta={"results": 0})
    found = HunterService(transport(handler), "key").search("x.com")
    assert [contact.email for contact in found.contacts] == ["info@x.com"]
    assert "CEO" in calls[0]["job_titles"] and "Owner" in calls[0]["job_titles"]
    assert calls[1]["seniority"] == "executive"
    assert calls[2]["decision_maker"] == "true"
    assert calls[3]["type"] == "generic"


def test_hunter_stops_after_finding_a_priority_decision_maker():
    calls = []
    def handler(request):
        calls.append(request)
        return response(request, data={"emails": [{"value": "ceo@x.com", "position": "CEO", "seniority": "executive", "decision_maker": True}]}, meta={"results": 1})
    assert HunterService(transport(handler), "key").search("x.com").contacts[0].email == "ceo@x.com"
    assert len(calls) == 1
