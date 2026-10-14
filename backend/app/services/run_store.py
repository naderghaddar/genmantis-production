from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, RLock
from typing import Callable
from uuid import uuid4

import httpx
from apify_client import ApifyClient
from fastapi import HTTPException

from app.config import Settings
from app.models.leads import RunStatus
from app.models.schemas import ScrapeRequest
from app.services.apify_service import ApifyService
from app.services.enrichment_pipeline import EnrichmentPipeline, PipelineFailure
from app.services.hunter_service import HunterService
from app.services.neverbounce_service import NeverBounceService
from app.services.provider_http import ProviderHTTP

INTERNAL_ACCESS = object()


@dataclass
class StoredRun:
    request: ScrapeRequest
    public: RunStatus
    idempotency_key: str | None = None
    exports: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    owner_id: str | None = None


class RunManager:
    """Single-process, bounded local run store. No pending executor queue is accepted."""
    def __init__(self, settings: Settings, pipeline_factory: Callable | None = None):
        self.settings = settings
        self.runs: dict[str, StoredRun] = {}
        self.lock = RLock()
        self.cancel = Event()
        self.executor = ThreadPoolExecutor(max_workers=settings.max_active_runs, thread_name_prefix="enrichment")
        self.pipeline_factory = pipeline_factory
        self.source_owner_callback: Callable | None = None

    def _prune(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [key for key, value in self.runs.items() if value.public.completed_at and
                   (now - value.public.completed_at).total_seconds() > self.settings.retention_seconds]
        for key in expired:
            del self.runs[key]

    def start(self, request: ScrapeRequest, idempotency_key: str | None = None, owner_id: str | None = None) -> RunStatus:
        with self.lock:
            self._prune()
            if self.cancel.is_set():
                raise HTTPException(503, "Backend is shutting down.")
            if idempotency_key:
                for value in self.runs.values():
                    if value.idempotency_key == idempotency_key and value.owner_id == owner_id:
                        if value.request != request:
                            raise HTTPException(409, "This request key belongs to different search inputs.")
                        return value.public.model_copy(deep=True)
            active = sum(run.public.status not in {"completed", "failed"} for run in self.runs.values())
            if active >= self.settings.max_active_runs:
                raise HTTPException(429, "Another enrichment run is active. Wait for it to finish before starting another.")
            if len(self.runs) >= self.settings.max_stored_runs:
                terminal = next((key for key, run in self.runs.items() if run.public.status in {"completed", "failed"}), None)
                if terminal:
                    del self.runs[terminal]
                else:
                    raise HTTPException(429, "Run storage is full.")
            run_id = uuid4().hex
            public = RunStatus(run_id=run_id, created_at=datetime.now(timezone.utc))
            self.runs[run_id] = StoredRun(request=request, public=public, idempotency_key=idempotency_key, owner_id=owner_id)
            self.executor.submit(self._execute, run_id)
            return public.model_copy(deep=True)

    def update(self, run_id: str, **values) -> None:
        with self.lock:
            public = self.runs[run_id].public
            for name, value in values.items():
                setattr(public, name, value)
            if values.get("apify_run_id") and self.runs[run_id].owner_id and self.source_owner_callback:
                self.source_owner_callback(values["apify_run_id"], self.runs[run_id].owner_id)

    def get(self, run_id: str, owner_id=INTERNAL_ACCESS) -> RunStatus:
        with self.lock:
            self._prune()
            if run_id not in self.runs:
                raise HTTPException(404, "Enrichment run not found or expired. In-memory runs are lost on server restart.")
            owner = self.runs[run_id].owner_id
            if owner and owner_id is not INTERNAL_ACCESS and owner != owner_id:
                raise HTTPException(404, "Enrichment run not found.")
            return self.runs[run_id].public.model_copy(deep=True)

    def download(self, run_id: str, kind: str, owner_id=INTERNAL_ACCESS) -> tuple[bytes, str]:
        with self.lock:
            public = self.get(run_id, owner_id)
            if public.status != "completed" or not public.downloads_ready:
                raise HTTPException(409, "CSV exports are available after the pipeline completes.")
            return self.runs[run_id].exports[kind]

    def _execute(self, run_id: str) -> None:
        request = self.runs[run_id].request
        try:
            with httpx.Client(timeout=httpx.Timeout(35, connect=10), follow_redirects=False) as client:
                if self.pipeline_factory:
                    pipeline = self.pipeline_factory(self.settings, client, self.cancel)
                else:
                    settings = self.settings
                    pipeline = EnrichmentPipeline(settings,
                        ApifyService(ApifyClient(settings.apify_token, max_retries=0, timeout_secs=30)),
                        HunterService(ProviderHTTP(client, "hunter", settings.provider_retries, settings.provider_interval, cancel=self.cancel),
                                      settings.hunter_key, settings.max_hunter_results, settings.max_hunter_pages),
                        NeverBounceService(ProviderHTTP(client, "neverbounce", settings.provider_retries, settings.provider_interval, cancel=self.cancel), settings.neverbounce_key),
                        self.cancel)
                exports = pipeline.run(run_id, request, lambda **values: self.update(run_id, **values))
            with self.lock:
                self.runs[run_id].exports = exports
                self.update(run_id, status="completed", message="Enrichment complete.", downloads_ready=True,
                            completed_at=datetime.now(timezone.utc))
        except Exception as error:
            message = str(error) if isinstance(error, PipelineFailure) else "Pipeline failed. Check the provider accounts and Apify Console before starting another run."
            self.update(run_id, status="failed", message=message, failure_reason=message,
                        completed_at=datetime.now(timezone.utc))

    def close(self) -> None:
        self.cancel.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
