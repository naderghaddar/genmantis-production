import json
from typing import Callable

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.agent_schemas import ConversationData
from app.models.schemas import ScrapeRequest
from app.services.run_store import RunManager

START_LEAD_GENERATION = {
    "type": "function", "name": "start_lead_generation",
    "description": "Start the existing asynchronous lead pipeline for this exact backend-approved niche, city, state, ranking filters and business limit. Never call without backend approval.",
    "strict": True,
    "parameters": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "niche": {"type": "string", "minLength": 1, "maxLength": 200},
            "city": {"type": "string", "minLength": 1, "maxLength": 200},
            "state": {"type": "string", "minLength": 1, "maxLength": 200},
            "min_google_maps_rank": {"type": ["integer", "null"], "minimum": 1, "maximum": 10000},
            "max_google_maps_rank": {"type": ["integer", "null"], "minimum": 1, "maximum": 10000},
            "max_leads": {"type": "integer", "minimum": 1, "maximum": 30},
        },
        "required": ["niche", "city", "state", "min_google_maps_rank", "max_google_maps_rank", "max_leads"],
    },
}
REGISTERED_TOOLS = {"start_lead_generation": START_LEAD_GENERATION}


def execute_tool(name: str, arguments: str, conversation: ConversationData, owner: str, manager: RunManager,
                 persist: Callable[[ConversationData], None] | None = None):
    if name not in REGISTERED_TOOLS:
        raise HTTPException(422, "Assistant requested an unsupported tool.")
    if conversation.owner_id != owner:
        raise HTTPException(404, "Search plan not found.")
    if conversation.approved_version != conversation.plan.version or conversation.plan.status not in {"confirmed", "running", "completed", "failed"}:
        raise HTTPException(409, "This exact search plan has not been approved.")
    try:
        raw = json.loads(arguments)
        # Require all schema properties even though the internal manual schema has defaults.
        if not isinstance(raw, dict) or set(raw) != set(START_LEAD_GENERATION["parameters"]["required"]):
            raise ValueError
        request = ScrapeRequest.model_validate(raw)
        if request.model_dump() != conversation.plan.execution_request().model_dump():
            raise ValueError
    except (ValueError, ValidationError):
        raise HTTPException(422, "Tool arguments do not match the approved search plan.") from None
    version = str(conversation.plan.version)
    if version in conversation.executions:
        return {"run_id": conversation.executions[version], "status": "running", "message": "Existing lead generation run."}
    try:
        manager.settings.require_keys()
    except ValueError as error:
        raise HTTPException(503, str(error)) from error
    if conversation.plan.version in conversation.execution_attempted_versions:
        raise HTTPException(409, "An interrupted execution attempt is recorded. Check Apify Console before preparing and confirming a new plan version.")
    conversation.execution_attempted_versions.append(conversation.plan.version)
    if persist:
        persist(conversation)
    try:
        run = manager.start(request, f"agent_{conversation.plan.id}_{version}", owner_id=owner)
    except HTTPException:
        # RunManager HTTP errors are pre-creation validation/capacity failures.
        conversation.execution_attempted_versions.remove(conversation.plan.version)
        if persist:
            persist(conversation)
        raise
    conversation.executions[version] = run.run_id
    conversation.run_id = run.run_id
    conversation.plan.status = "running"
    conversation.announced_run_status = None
    return {"run_id": run.run_id, "status": run.status, "message": "Lead generation started."}
