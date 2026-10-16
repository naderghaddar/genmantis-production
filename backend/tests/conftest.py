from unittest.mock import MagicMock

import pytest

from app.config import ACTOR_ID, Settings
from app.models.schemas import ScrapeRequest
from app.services.apify_service import ApifyService


@pytest.fixture(autouse=True)
def isolated_agent_storage(monkeypatch):
    # API lifespan tests must never read/write the user's local conversation database.
    monkeypatch.setenv("AGENT_DB_PATH", ":memory:")
    monkeypatch.setenv("WORKSPACE_DB_PATH", ":memory:")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "")
    monkeypatch.setenv("ALLOW_LOCAL_WORKSPACE", "true")


@pytest.fixture
def settings():
    return Settings(apify_token="test-apify", hunter_key="test-hunter", neverbounce_key="test-nb",
                    provider_interval=0, apify_poll_interval=0.001)


@pytest.fixture
def search_request():
    return ScrapeRequest(niche="Chiropractors", city="Austin", state="Texas")


@pytest.fixture
def sdk():
    client = MagicMock()
    client.actor.return_value.start.return_value = {"id": "actorRun123", "status": "READY", "actId": ACTOR_ID}
    client.run.return_value.get.return_value = {"id": "actorRun123", "status": "SUCCEEDED", "actId": ACTOR_ID,
                                              "defaultDatasetId": "dataset123"}
    client.dataset.return_value.get.return_value = {"itemCount": 5}
    client.dataset.return_value.iterate_items.return_value = iter([
        {"placeId": "1", "title": "North", "website": "https://www.clinic.co.uk/", "address": "North Street", "phone": "business phone"},
        {"placeId": "2", "title": "South", "website": "https://clinic.co.uk/about", "address": "South Street"},
        {"placeId": "3", "title": "No site"},
        {"placeId": "4", "title": "Provider error", "website": "https://failed.com"},
        {"placeId": "1", "title": "North", "website": "https://clinic.co.uk", "additional": "retained"},
    ])
    return client
