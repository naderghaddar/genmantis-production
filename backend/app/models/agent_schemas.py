from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.leads import RunStatus
from app.models.schemas import ScrapeRequest

PlanField = Literal["niche", "city", "state", "country", "business_size_preference", "min_google_maps_rank", "max_google_maps_rank", "max_leads", "additional_preferences", "unsupported_preferences"]
AgentState = Literal["collecting_requirements", "ready_for_confirmation", "confirmed", "running", "completed", "failed"]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanDraft(StrictModel):
    niche: ShortText | None
    city: ShortText | None
    state: ShortText | None
    country: ShortText | None
    business_size_preference: ShortText | None
    min_google_maps_rank: int | None = Field(ge=1, le=10000)
    max_google_maps_rank: int | None = Field(ge=1, le=10000)
    max_leads: int = Field(ge=1, le=30)
    additional_preferences: list[ShortText] = Field(max_length=10)
    unsupported_preferences: list[ShortText] = Field(max_length=10)


class AgentInterpretation(StrictModel):
    assistant_message: str = Field(min_length=1, max_length=3000)
    changed_fields: list[PlanField]
    plan: PlanDraft


class LeadSearchPlan(PlanDraft):
    id: str
    version: int = 1
    status: AgentState = "collecting_requirements"
    limitations: list[str] = Field(default_factory=list)

    def execution_request(self) -> ScrapeRequest:
        return ScrapeRequest(**{name: getattr(self, name) for name in ScrapeRequest.model_fields})


class ChatMessage(StrictModel):
    id: str
    role: Literal["user", "assistant"]
    content: str


class AgentUsage(StrictModel):
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0


class ConversationData(StrictModel):
    id: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage]
    plan: LeadSearchPlan
    previous_response_id: str | None = None
    approved_version: int | None = None
    executions: dict[str, str] = Field(default_factory=dict)
    execution_attempted_versions: list[int] = Field(default_factory=list)
    run_id: str | None = None
    announced_run_status: str | None = None
    usage: AgentUsage = Field(default_factory=AgentUsage)


class ConversationView(StrictModel):
    id: str
    messages: list[ChatMessage]
    plan: LeadSearchPlan
    confirmation_required: bool
    run: RunStatus | None = None
    usage: AgentUsage


class AgentMessageRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    message_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class PlanAction(StrictModel):
    version: int = Field(ge=1, strict=True)
