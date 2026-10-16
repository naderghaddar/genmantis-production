import csv
import hashlib
import io
import time
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.agent_routes import browser_owner
from app.agents.research_tools import source_catalog
from app.models.workspace import AdvisorMessage, BusinessProfile, BulkLeadPatch, CampaignAction, CampaignPlan, LeadPatch, now
from app.services.csv_service import safe_cell
from app.services.lead_policy import verified_contact, normalize_record, visible_leads
from app.services.workspace_store import WorkspaceIdentity

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def identity(request: Request, response: Response) -> WorkspaceIdentity:
    settings, store = request.app.state.workspace_settings, request.app.state.workspace_store
    authorization = request.headers.get("authorization", "")
    if authorization:
        if not authorization.startswith("Bearer ") or not settings.supabase_url or not settings.supabase_publishable_key:
            raise HTTPException(401, "Sign in with a valid account.")
        token = authorization[7:]
        digest = hashlib.sha256(token.encode()).hexdigest()
        cached = request.app.state.auth_cache.get(digest)
        if cached and cached[0] > time.monotonic():
            user = cached[1]
        else:
            try:
                result = httpx.get(settings.supabase_url + "/auth/v1/user", headers={"apikey": settings.supabase_publishable_key,
                    "Authorization": authorization}, timeout=10)
            except httpx.HTTPError:
                raise HTTPException(503, "Account authentication is temporarily unavailable.") from None
            if result.status_code != 200:
                raise HTTPException(401, "Your session expired. Please sign in again.")
            user = result.json()
            if not user.get("id"):
                raise HTTPException(401, "Invalid account session.")
            if len(request.app.state.auth_cache) > 1000:
                request.app.state.auth_cache.clear()
            request.app.state.auth_cache[digest] = (time.monotonic() + 45, user)
        return store.identity(user["id"], token, user.get("email"))
    if not settings.allow_local_workspace:
        raise HTTPException(401, "Sign in to access your workspace.")
    return store.identity("local_" + browser_owner(request, response))


Identity = Annotated[WorkspaceIdentity, Depends(identity)]


@router.get("/config")
def config(request: Request):
    settings = request.app.state.workspace_settings
    return {"auth": {"url": settings.supabase_url, "publishable_key": settings.supabase_publishable_key,
            "local_enabled": settings.allow_local_workspace}, "sources": source_catalog(settings),
        "integrations": [{"name": name, "connected": bool(key), "purpose": purpose} for name, key, purpose in [
            ("OpenAI", settings.openai_key, "Research and campaign strategy"), ("Apify", settings.apify_token, "Google Maps discovery"),
            ("Hunter", settings.hunter_key, "Company contact discovery"), ("NeverBounce", settings.neverbounce_key, "Email verification")]]}


@router.get("")
def workspace(request: Request, user: Identity):
    store = request.app.state.workspace_store
    store.flush_recovery(user)
    campaigns = [request.app.state.campaigns.recover(user, item) for item in store.list(user, "campaign")]
    leads = visible_leads(store.list(user, "lead"))
    threads = store.list(user, "thread")
    try:
        profile = store.get(user, "profile", "business")["profile"]
    except HTTPException as error:
        if error.status_code != 404:
            raise
        profile = BusinessProfile().model_dump()
    return {"profile": profile, "campaigns": campaigns, "leads": leads,
        "threads": [{key: item.get(key) for key in ("id", "title", "updated_at", "status")} for item in threads],
        "account": {"email": user.email, "storage": "cloud" if user.token else "local"}}


@router.put("/profile")
def save_profile(body: BusinessProfile, request: Request, user: Identity):
    return request.app.state.workspace_store.save(user, "profile", {"id": "business", "profile": body.model_dump()})


@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignPlan, request: Request, user: Identity):
    return request.app.state.campaigns.create(user, body)


@router.put("/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, body: CampaignPlan, request: Request, user: Identity, version: int = Query(ge=1)):
    return request.app.state.campaigns.update_plan(user, campaign_id, body, version)


@router.post("/campaigns/{campaign_id}/start")
def start_campaign(campaign_id: str, body: CampaignAction, request: Request, user: Identity):
    return request.app.state.campaigns.start(user, campaign_id, body.version)


@router.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str, request: Request, user: Identity):
    return request.app.state.campaigns.cancel(user, campaign_id)


def patch_lead(store, user, lead_id, body):
    with store.operation_lock(user.owner):
        lead = normalize_record(store.get(user, "lead", lead_id))
        changes = body.model_dump(exclude_none=True)
        if changes.get("stage") == "qualified" and not verified_contact(lead):
            raise HTTPException(409, "Only a named contact with a NeverBounce valid, catchall or unknown result can move to Qualified.")
        changed = [key for key, value in changes.items() if lead.get(key) != value]
        lead.update(changes)
        if changed:
            lead.setdefault("activities", []).append({"at": now(), "message": "Updated " + ", ".join(key.replace("_", " ") for key in changed)})
            lead["activities"] = lead["activities"][-100:]
        return store.save(user, "lead", lead)


@router.patch("/leads/bulk")
def bulk_leads(body: BulkLeadPatch, request: Request, user: Identity):
    store = request.app.state.workspace_store
    # Validate ownership and qualification for every row before any writes.
    with store.operation_lock(user.owner):
        records = [store.get(user, "lead", item) for item in body.ids]
        if body.changes.stage == "qualified" and any(not verified_contact(item) for item in records):
            raise HTTPException(409, "Only verified contacts can move to Qualified.")
        return [patch_lead(store, user, item, body.changes) for item in body.ids]


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: str, body: LeadPatch, request: Request, user: Identity):
    return patch_lead(request.app.state.workspace_store, user, lead_id, body)


@router.get("/leads/export")
def export_leads(request: Request, user: Identity, category: str = "verified", campaign_id: str = ""):
    records = visible_leads(request.app.state.workspace_store.list(user, "lead"))
    records = [item for item in records if (category in {"all", "verified"} or (item["lead"].get("verification") or {}).get("result") == category)
        and (not campaign_id or campaign_id in item["campaign_ids"])]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["company", "domain", "industry", "location", "first_name", "last_name", "title", "email", "email_status",
        "verified", "stage", "fit", "source", "notes", "next_action", "follow_up"])
    for item in records:
        lead = item.get("lead", {})
        contact, verification = lead.get("contact") or {}, lead.get("verification") or {}
        # The verified-only export checks provider evidence as well as the display category.
        if not verified_contact(item):
            continue
        writer.writerow([safe_cell(value) for value in [item["company"], item.get("domain"), item["industry"], item["location"],
            contact.get("first_name"), contact.get("last_name"), contact.get("job_title"), contact.get("email"), verification.get("result"),
            verified_contact(item), item["stage"], item["assessment"]["fit"], item["source"], item.get("notes"), item.get("next_action"), item.get("follow_up")]])
    return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="genmantis_leads.csv"'})


@router.post("/threads", status_code=201)
def create_thread(request: Request, user: Identity):
    return request.app.state.research_agent.create(user)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, request: Request, user: Identity):
    return request.app.state.workspace_store.get(user, "thread", thread_id)


@router.post("/threads/{thread_id}/messages")
def advisor_message(thread_id: str, body: AdvisorMessage, request: Request, user: Identity):
    return request.app.state.research_agent.message(user, thread_id, body)
