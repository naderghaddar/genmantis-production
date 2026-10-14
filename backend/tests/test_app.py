import csv
import io
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from impit import ConnectError

from app.config import ACTOR_ID
from app.main import app
from app.models.schemas import ScrapeRequest
from app.services.apify_service import ApifyService, build_actor_input, get_apify_service
from app.services.csv_service import csv_filename, generate_csv
from app.api.agent_routes import browser_owner


@pytest.fixture
def setup():
    sdk = MagicMock()
    sdk.actor.return_value.start.return_value = {"id": "run123", "status": "READY", "actId": ACTOR_ID}
    sdk.run.return_value.get.return_value = {
        "id": "run123", "status": "SUCCEEDED", "actId": ACTOR_ID,
        "defaultDatasetId": "dataset123", "defaultKeyValueStoreId": "store123",
    }
    sdk.dataset.return_value.get.return_value = {"itemCount": 2}
    sdk.dataset.return_value.iterate_items.return_value = iter([{"title": "Clinic"}, {"title": "Another"}])
    sdk.key_value_store.return_value.get_record.return_value = {"value": {
        "searchStringsArray": ["Chiropractors"], "locationQuery": "Austin, Texas",
    }}
    app.dependency_overrides[get_apify_service] = lambda: ApifyService(sdk)
    app.dependency_overrides[browser_owner] = lambda: "test-owner"
    with TestClient(app) as client:
        app.state.lead_agent.store.claim_source_run("run123", "test-owner")
        yield client, sdk
    app.dependency_overrides.clear()


@pytest.mark.parametrize("body", [
    {}, {"niche": "x", "city": "Austin"},
    {"niche": "  ", "city": "Austin", "state": "TX"},
    {"niche": 42, "city": "Austin", "state": "TX"},
    {"niche": "x" * 201, "city": "Austin", "state": "TX"},
    {"niche": "x", "city": "Austin", "state": "TX", "scrapeContacts": True},
])
def test_invalid_request(setup, body):
    client, sdk = setup
    assert client.post("/api/scrapes", json=body).status_code == 422
    sdk.actor.assert_not_called()


def test_exact_input_and_start(setup):
    client, sdk = setup
    response = client.post("/api/scrapes", json={"niche": " Chiropractors ", "city": " Austin ", "state": " Texas "})
    assert response.status_code == 202
    assert response.json()["run_id"] == "run123"
    assert response.json()["status"] == "running"
    sdk.actor.assert_called_once_with(ACTOR_ID)
    expected = {
        "searchStringsArray": ["Chiropractors"], "locationQuery": "Austin, Texas",
        "enableCompetitorAnalysis": False, "includeWebResults": False,
        "maxCompetitorsToAnalyze": 30, "maxCrawledPlacesPerSearch": 30,
        "maximumLeadsEnrichmentRecords": 0, "scrapeContacts": False,
        "scrapeDirectories": False, "scrapeImageAuthors": False,
        "scrapeOrderOnline": False, "scrapePlaceDetailPage": False,
        "scrapeReviewsPersonalData": True,
        "scrapeSocialMediaProfiles": {"facebooks": False, "instagrams": False,
            "tiktoks": False, "twitters": False, "youtubes": False},
        "scrapeTableReservationProvider": False, "skipClosedPlaces": False,
        "verifyLeadsEnrichmentEmails": False,
    }
    sdk.actor.return_value.start.assert_called_once_with(run_input=expected)
    first = build_actor_input(ScrapeRequest(niche="x", city="y", state="z"))
    first["scrapeSocialMediaProfiles"]["facebooks"] = True
    assert build_actor_input(ScrapeRequest(niche="x", city="y", state="z"))["scrapeSocialMediaProfiles"]["facebooks"] is False


@pytest.mark.parametrize("status", ["READY", "RUNNING", "TIMING-OUT", "ABORTING"])
def test_running(setup, status):
    client, sdk = setup
    sdk.run.return_value.get.return_value["status"] = status
    assert client.get("/api/scrapes/run123").json()["status"] == "running"
    assert client.get("/api/scrapes/run123/download").status_code == 409


@pytest.mark.parametrize("status", ["FAILED", "ABORTED", "TIMED-OUT"])
def test_failed_run(setup, status):
    client, sdk = setup
    sdk.run.return_value.get.return_value["status"] = status
    data = client.get("/api/scrapes/run123").json()
    assert data["status"] == "failed"
    assert data["message"]
    assert client.get("/api/scrapes/run123/download").status_code == 409


def test_success_and_download(setup):
    client, sdk = setup
    assert client.get("/api/scrapes/run123").json()["result_count"] == 2
    response = client.get("/api/scrapes/run123/download")
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert 'chiropractors_austin_texas_leads.csv' in response.headers["content-disposition"]
    assert len(list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))) == 2
    sdk.dataset.return_value.iterate_items.assert_called_once_with()


def test_empty_run(setup):
    client, sdk = setup
    sdk.dataset.return_value.get.return_value = {"itemCount": 0}
    sdk.dataset.return_value.iterate_items.return_value = iter([])
    assert client.get("/api/scrapes/run123").json()["result_count"] == 0
    assert client.get("/api/scrapes/run123/download").status_code == 404
    with pytest.raises(ValueError):
        generate_csv([])


@pytest.mark.parametrize("run", [None, {"actId": "anotherActor"}])
def test_missing_or_unrelated_run(setup, run):
    client, sdk = setup
    sdk.run.return_value.get.return_value = run
    assert client.get("/api/scrapes/run123").status_code == 404
    assert client.get("/api/scrapes/run123/download").status_code == 404


def test_unavailable_dataset(setup):
    client, sdk = setup
    sdk.dataset.return_value.get.return_value = None
    assert client.get("/api/scrapes/run123").status_code == 502


def test_connection_failure(setup):
    client, sdk = setup
    sdk.actor.return_value.start.side_effect = ConnectError("private error details")
    response = client.post("/api/scrapes", json={"niche": "x", "city": "y", "state": "z"})
    assert response.status_code == 502
    assert "private error" not in response.text


def test_missing_token(monkeypatch):
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/scrapes", json={"niche": "x", "city": "y", "state": "z"})
    assert response.status_code == 503
    assert "backend/.env" in response.json()["detail"]


def test_csv_preserves_missing_nested_and_escaped_fields():
    records = [{"title": 'Clinic, "North"\nOffice', "phone": "+15125551212", "extra": {"a": [1, "\u00e9"]}},
               {"title": "Caf\u00e9", "categories": ["Health", "Care"], "newField": True, "website": None}]
    rows = list(csv.DictReader(io.StringIO(generate_csv(records).decode("utf-8-sig"))))
    assert rows[0]["title"] == records[0]["title"]
    assert rows[1]["title"] == "Caf\u00e9"
    assert rows[0]["phone"] == "'+15125551212"
    assert rows[1]["phone"] == ""
    assert rows[1]["website"] == ""
    assert json.loads(rows[0]["extra"]) == records[0]["extra"]
    assert json.loads(rows[1]["categories"]) == records[1]["categories"]
    assert list(rows[0]) == ["title", "categories", "phone", "website", "extra", "newField"]
    assert csv_filename("Chiropractors", "Austin", "Texas") == "chiropractors_austin_texas_leads.csv"
    assert "/" not in csv_filename("../x", "a", "b")


def test_cors(setup):
    client, _ = setup
    response = client.options("/api/scrapes", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize("code,expected", [(401, 502), (403, 502), (404, 404), (429, 503), (500, 502)])
def test_apify_api_errors(setup, code, expected):
    from apify_client.errors import ApifyApiError
    from impit import Response
    client, sdk = setup
    sdk.actor.return_value.start.side_effect = ApifyApiError(
        Response(code, content=b'{"error":{"message":"upstream detail","type":"test"}}'), 1)
    response = client.post("/api/scrapes", json={"niche": "x", "city": "y", "state": "z"})
    assert response.status_code == expected
    assert "upstream detail" not in response.text
