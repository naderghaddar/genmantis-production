from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.api.workspace_routes import router as workspace_router
from app.services.workspace_store import WorkspaceStore
from app.services.campaign_service import CampaignService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = WorkspaceStore(settings.workspace_db_path, settings.supabase_url, settings.supabase_publishable_key)
    campaigns = CampaignService(settings, store)
    app.state.workspace_settings = settings
    app.state.workspace_store = store
    app.state.campaigns = campaigns
    app.state.auth_cache = {}
    try:
        yield
    finally:
        import asyncio
        await asyncio.to_thread(campaigns.close)
        store.close()


app = FastAPI(title="GenMantis API", lifespan=lifespan)
app.include_router(workspace_router)


@app.get("/health")
def health():
    return {"status": "ok", "application": "genmantis", "version": "5.0.0"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Disposition"],
    allow_credentials=True,
)
frontend_dist = Path(__file__).resolve().parents[2] / "frontend_dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
