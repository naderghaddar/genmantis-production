import hashlib
import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.agents.lead_agent import LeadAgent
from app.models.agent_schemas import AgentMessageRequest, ConversationView, PlanAction

router = APIRouter(prefix="/api/agent", tags=["agent"])


def browser_owner(request: Request, response: Response) -> str:
    if getattr(request.state, "authenticated_owner", None):
        return request.state.authenticated_owner
    token = request.cookies.get("gm_session", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        token = secrets.token_urlsafe(32)
        response.set_cookie("gm_session", token, httponly=True, samesite="strict", max_age=31536000, path="/api", secure=request.url.scheme == "https")
    return hashlib.sha256(token.encode()).hexdigest()


def get_agent(request: Request) -> LeadAgent:
    return request.app.state.lead_agent


Agent = Annotated[LeadAgent, Depends(get_agent)]
Owner = Annotated[str, Depends(browser_owner)]


@router.post("/conversations", response_model=ConversationView, status_code=201)
def create_conversation(agent: Agent, owner: Owner):
    return agent.create(owner)


@router.get("/conversations/{conversation_id}", response_model=ConversationView)
def get_conversation(conversation_id: str, agent: Agent, owner: Owner):
    return agent.get(conversation_id, owner)


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationView)
def send_message(conversation_id: str, body: AgentMessageRequest, agent: Agent, owner: Owner):
    return agent.message(conversation_id, owner, body)


@router.post("/search-plans/{plan_id}/confirm", response_model=ConversationView)
def confirm_plan(plan_id: str, body: PlanAction, agent: Agent, owner: Owner):
    return agent.confirm(plan_id, owner, body.version)


@router.post("/search-plans/{plan_id}/edit", response_model=ConversationView)
def edit_plan(plan_id: str, body: PlanAction, agent: Agent, owner: Owner):
    return agent.edit(plan_id, owner, body.version)
