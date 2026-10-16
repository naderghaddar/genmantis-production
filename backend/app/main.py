from contextlib import asynccontextmanager
from typing import Annotated, Literal

from apify_client.errors import ApifyApiError
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path as FilePath
from impit import TransportError

from app.models.schemas import ScrapeRequest, ScrapeStatus
from app.models.leads import RunStatus
from app.config import get_settings
from app.services.run_store import RunManager
from app.services.apify_service import ApifyService, get_apify_service
from app.services.csv_service import generate_csv
from app.api.agent_routes import router as agent_router, Owner
from app.agents.lead_agent import LeadAgent
from app.services.conversation_store import ConversationStore
from app.services.openai_service import OpenAIService
from app.api.workspace_routes import router as workspace_router
from app.services.workspace_store import WorkspaceStore
from app.services.campaign_service import CampaignService
from app.agents.research_agent import ResearchAgent

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    manager = RunManager(settings)
    store = ConversationStore(settings.agent_db_path)
    manager.source_owner_callback = store.claim_source_run
    app.state.run_manager = manager
    app.state.lead_agent = LeadAgent(store, OpenAIService(settings), manager)
    workspace_store = WorkspaceStore(settings.workspace_db_path, settings.supabase_url, settings.supabase_publishable_key)
    campaigns = CampaignService(settings, workspace_store)
    app.state.workspace_settings = settings
    app.state.workspace_store = workspace_store
    app.state.campaigns = campaigns
    app.state.research_agent = ResearchAgent(settings, workspace_store, campaigns)
    app.state.auth_cache = {}
    try:
        yield
    finally:
        # Shutdown cancels future provider work and waits for bounded in-flight calls.
        import asyncio
        await asyncio.to_thread(manager.close)
        await asyncio.to_thread(campaigns.close)
        workspace_store.close()
        store.close()


app = FastAPI(title="GenMantis API", lifespan=lifespan)
app.include_router(agent_router)
app.include_router(workspace_router)


@app.middleware("http")
async def protect_legacy_routes(request: Request, call_next):
    settings = getattr(request.app.state, "workspace_settings", None)
    if settings and not settings.allow_local_workspace and request.url.path.startswith("/api/") and not request.url.path.startswith("/api/workspace"):
        from app.api.workspace_routes import identity
        from starlette.concurrency import run_in_threadpool
        try:
            owner = await run_in_threadpool(identity, request, Response())
            request.state.authenticated_owner = owner.owner
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok", "application": "genmantis", "version": "4.0.0"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Content-Type", "Idempotency-Key", "Authorization"],
    expose_headers=["Content-Disposition"],
    allow_credentials=True,
)
Service = Annotated[ApifyService, Depends(get_apify_service)]
RunId = Annotated[str, Path(pattern=r"^[A-Za-z0-9]{1,64}$")]


def get_run_manager(request: Request) -> RunManager:
    return request.app.state.run_manager


Manager = Annotated[RunManager, Depends(get_run_manager)]


@app.post("/api/runs", response_model=RunStatus, status_code=202)
def start_run(body: ScrapeRequest, manager: Manager, owner: Owner,
              idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")] = None) -> RunStatus:
    try:
        manager.settings.require_keys()
    except ValueError as error:
        raise HTTPException(503, str(error)) from error
    return manager.start(body, idempotency_key, owner_id=owner)


@app.get("/api/runs/{run_id}", response_model=RunStatus)
def run_status(run_id: RunId, manager: Manager, owner: Owner) -> RunStatus:
    return manager.get(run_id, owner)


@app.get("/api/runs/{run_id}/download")
def download_run(run_id: RunId, manager: Manager, owner: Owner,
                 type: Annotated[Literal["verified", "all"], Query()] = "verified") -> Response:
    content, filename = manager.download(run_id, type, owner)
    return Response(content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.exception_handler(ApifyApiError)
def apify_error(_request: Request, error: ApifyApiError) -> JSONResponse:
    code = error.status_code
    if code in {401, 403}:
        return JSONResponse(status_code=502, content={"detail": "Apify rejected the backend token or actor access. Check your Apify account."})
    if code == 404:
        return JSONResponse(status_code=404, content={"detail": "Apify resource not found."})
    if code == 429:
        return JSONResponse(status_code=503, content={"detail": "Apify is rate limiting requests. Please try again shortly."})
    return JSONResponse(status_code=502, content={"detail": "Apify could not process the request. Check your account balance and actor availability."})


@app.exception_handler(TransportError)
def network_error(_request: Request, _error: TransportError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": "Cannot reach Apify. If starting a scrape, check Apify Console before retrying: the run may have started."})


@app.post("/api/scrapes", response_model=ScrapeStatus, status_code=202)
def start_scrape(body: ScrapeRequest, service: Service, owner: Owner, request: Request) -> ScrapeStatus:
    run = service.start(body)
    request.app.state.lead_agent.store.claim_source_run(run.run_id, owner)
    return run


@app.get("/api/scrapes/{run_id}", response_model=ScrapeStatus)
def scrape_status(run_id: RunId, service: Service, owner: Owner, request: Request) -> ScrapeStatus:
    request.app.state.lead_agent.store.require_source_owner(run_id, owner)
    return service.status(run_id)


@app.get("/api/scrapes/{run_id}/download")
def download_scrape(run_id: RunId, service: Service, owner: Owner, request: Request) -> Response:
    request.app.state.lead_agent.store.require_source_owner(run_id, owner)
    items, filename = service.download(run_id)
    return Response(generate_csv(items), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# Docker and production builds serve the React app from the same origin as the API.
frontend_dist = FilePath(__file__).resolve().parents[2] / "frontend_dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
