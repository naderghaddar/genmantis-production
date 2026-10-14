import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_run_manager
from app.models.leads import RunProgress
from app.models.schemas import ScrapeRequest
from app.services.run_store import RunManager


def wait_completed(manager, run_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = manager.get(run_id)
        if status.status in {"completed", "failed"}:
            return status
        time.sleep(0.005)
    raise AssertionError("Mock pipeline did not finish")


def factory(settings, client, cancel):
    pipeline = MagicMock()
    def run(run_id, request, update):
        update(status="exporting", progress=RunProgress(businesses_scraped=1, businesses_processed=1, verified_emails=1))
        return {"verified": (b"header\r\n", "verified.csv"), "all": (b"header\r\n", "all.csv")}
    pipeline.run.side_effect = run
    return pipeline


def test_run_api_fast_start_progress_download_and_idempotency(settings, search_request):
    manager = RunManager(settings, factory)
    app.dependency_overrides[get_run_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            response = client.post("/api/runs", json=search_request.model_dump(), headers={"Idempotency-Key": "test123"})
            assert response.status_code == 202
            run_id = response.json()["run_id"]
            status = wait_completed(manager, run_id)
            assert status.status == "completed" and status.downloads_ready
            assert client.get(f"/api/runs/{run_id}").json()["progress"]["verified_emails"] == 1
            duplicate = client.post("/api/runs", json=search_request.model_dump(), headers={"Idempotency-Key": "test123"})
            assert duplicate.json()["run_id"] == run_id and len(manager.runs) == 1
            for kind in ["verified", "all"]:
                downloaded = client.get(f"/api/runs/{run_id}/download?type={kind}")
                assert downloaded.status_code == 200 and downloaded.content == b"header\r\n"
                assert kind + ".csv" in downloaded.headers["content-disposition"]
            assert client.get(f"/api/runs/{run_id}/download?type=wrong").status_code == 422
            assert client.get("/api/runs/unknown").status_code == 404
            assert client.post("/api/runs", json={"niche": "  ", "city": "Austin", "state": "TX"}).status_code == 422
            changed = {**search_request.model_dump(), "city": "Dallas"}
            assert client.post("/api/runs", json=changed, headers={"Idempotency-Key": "test123"}).status_code == 409
    finally:
        manager.close()
        app.dependency_overrides.clear()


def test_run_capacity_and_pending_download(settings, search_request):
    gate = Event()
    def blocked_factory(*_):
        pipeline = MagicMock()
        def run(*_):
            gate.wait(3)
            return {}
        pipeline.run.side_effect = run
        return pipeline
    manager = RunManager(settings, blocked_factory)
    try:
        first = manager.start(search_request, "same")
        assert manager.start(search_request, "same").run_id == first.run_id
        with pytest.raises(HTTPException) as error:
            manager.start(search_request, "another")
        assert error.value.status_code == 429
        with pytest.raises(HTTPException) as error:
            manager.download(first.run_id, "all")
        assert error.value.status_code == 409
    finally:
        gate.set()
        manager.close()


def test_failed_worker_masks_internal_error(settings, search_request):
    def failed_factory(*_):
        raise RuntimeError("private API key")
    manager = RunManager(settings, failed_factory)
    try:
        status = wait_completed(manager, manager.start(search_request).run_id)
        assert status.status == "failed" and "private" not in status.message
    finally:
        manager.close()


def test_storage_retention_and_snapshots(settings, search_request):
    manager = RunManager(replace(settings, max_stored_runs=2), factory)
    try:
        first = manager.start(search_request).run_id
        returned = wait_completed(manager, first)
        returned.progress.verified_emails = 900
        assert manager.get(first).progress.verified_emails == 1
        second = manager.start(search_request).run_id
        wait_completed(manager, second)
        third = manager.start(search_request).run_id
        wait_completed(manager, third)
        assert len(manager.runs) == 2 and first not in manager.runs
        manager.runs[second].public.completed_at = datetime.now(timezone.utc) - timedelta(hours=2)
        with pytest.raises(HTTPException):
            manager.get(second)
    finally:
        manager.close()


def test_missing_keys_block_before_paid_work():
    manager = RunManager(Settings(), factory)
    app.dependency_overrides[get_run_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            response = client.post("/api/runs", json={"niche": "x", "city": "y", "state": "z"})
            assert response.status_code == 503 and "HUNTER_API_KEY" in response.json()["detail"]
            assert not manager.runs
    finally:
        manager.close()
        app.dependency_overrides.clear()


def test_safe_configuration_limits(monkeypatch):
    monkeypatch.setenv("MAX_VERIFICATION_ATTEMPTS_PER_BUSINESS", "999")
    with pytest.raises(ValueError, match="MAX_VERIFICATION"):
        get_settings()


def test_real_orchestration_wiring_through_api(monkeypatch, settings, search_request, sdk):
    import httpx
    from app.services.csv_service import LEAD_COLUMNS
    import csv
    import io
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == "api.hunter.io":
            return httpx.Response(200, json={"data": {"emails": [{"value": "info@example.com", "type": "generic"}]}, "meta": {"results": 1}})
        return httpx.Response(200, json={"status": "success", "result": "valid"})
    original_client = httpx.Client
    monkeypatch.setattr("app.services.run_store.httpx.Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr("app.services.run_store.ApifyClient", lambda *_, **__: sdk)
    manager = RunManager(settings)
    app.dependency_overrides[get_run_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            started = client.post("/api/runs", json=search_request.model_dump())
            assert started.status_code == 202
            status = wait_completed(manager, started.json()["run_id"])
            assert status.status == "completed" and status.progress.businesses_scraped == 3
            assert status.progress.verified_emails == status.progress.generic_emails_selected == 2
            exported = client.get(f"/api/runs/{status.run_id}/download?type=all")
            rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
            assert len(rows) == 3 and list(rows[0]) == LEAD_COLUMNS
            sdk.actor.return_value.start.assert_called_once()
            assert len(calls) == 3  # Two distinct domains and one cached shared email verification.
    finally:
        manager.close()
        app.dependency_overrides.clear()
