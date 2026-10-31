from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid4().hex


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BusinessProfile(Strict):
    company_name: str = Field(default="", max_length=200)
    website: str = Field(default="", max_length=500)
    offer: str = Field(default="", max_length=3000)
    ideal_customer: str = Field(default="", max_length=3000)
    deal_size: str = Field(default="", max_length=200)
    geography: str = Field(default="", max_length=300)
    exclusions: str = Field(default="", max_length=2000)
    buyer_roles: str = Field(default="", max_length=500)


class CampaignLocation(Strict):
    city: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=1, max_length=200, description="State, province, region or country needed to identify this city.")

    @model_validator(mode="after")
    def nonempty(self):
        self.city, self.state = self.city.strip(), self.state.strip()
        if not self.city or not self.state:
            raise ValueError("Each location needs a city and state, region or country.")
        return self


class CampaignPlan(Strict):
    name: str = Field(min_length=1, max_length=120)
    source: Literal["google_maps", "web_research", "company_websites"]
    niche: str = Field(min_length=1, max_length=200)
    city: str = Field(default="", max_length=200)
    state: str = Field(default="", max_length=200)
    locations: list[CampaignLocation] = Field(default_factory=list, max_length=30,
        description="All user-approved cities in search order. Deepen searches only within these cities until the verified-person target is met. Never add unapproved cities.")
    query: str = Field(default="", max_length=1000)
    websites: list[str] = Field(default_factory=list, max_length=70)
    max_leads: int = Field(default=50, ge=1, le=1000, strict=True,
        description="Requested number of NEW unique people with Hunter emails checked by NeverBounce as valid, catchall or unknown. This is NOT a business/scrape limit. Google Maps starts with 100 businesses per location and can deepen within those cities.")
    max_leads_per_company: int | None = Field(default=1, ge=1, le=1000, strict=True,
        description="Maximum saved leads per company domain, including existing workspace leads. Default 1. For '200 leads from 200 unique companies' set max_leads=200 and this field=1. Use a higher number when requested, or null only for explicitly unlimited contacts per company. Duplicate emails are always excluded.")
    rationale: str = Field(default="", max_length=3000)
    qualification_criteria: list[str] = Field(default_factory=list, max_length=6,
        description="Additional company-fit requirements to assess from website evidence. Do not repeat niche, location or lead-count fields. Must be [] when research_websites is false.")
    exclusions: list[str] = Field(default_factory=list, max_length=6,
        description="Company traits to exclude based on website evidence. Must be [] when research_websites is false.")
    research_websites: bool = Field(default=True,
        description="Research company websites for fit before enrichment. If false, qualification_criteria and exclusions must both be empty arrays.")
    min_google_maps_rank: int | None = Field(default=None, ge=1, le=10000)
    max_google_maps_rank: int | None = Field(default=None, ge=1, le=10000)
    email_policy: Literal["valid_only", "accepted"] = Field(default="accepted",
        description="accepted counts valid/catchall/unknown, the workspace default. Use valid_only only when requested.")
    max_city_rounds: int = Field(default=3, ge=1, le=5, strict=True,
        description="Search depth per explicitly named city: up to 100, 200, then 300 businesses. Deepen only if the prior batch filled its cap and supplied new businesses. Default 3; never add cities.")

    @model_validator(mode="after")
    def valid_source(self):
        if self.locations:
            self.locations = list({(item.city.casefold(), item.state.casefold()): item for item in self.locations}.values())
            self.city, self.state = self.locations[0].city, self.locations[0].state
        if self.source == "google_maps" and (not self.city.strip() or not self.state.strip()):
            raise ValueError("Google Maps needs a city and state or region.")
        if not self.locations and self.city.strip() and self.state.strip():
            self.locations = [CampaignLocation(city=self.city, state=self.state)]
        if self.source == "web_research" and not self.query.strip():
            raise ValueError("Web research needs a search query.")
        if self.source == "company_websites" and not self.websites:
            raise ValueError("Add at least one company website.")
        if self.source != "google_maps" and (self.min_google_maps_rank or self.max_google_maps_rank):
            raise ValueError("Maps ranking filters are only available for Google Maps.")
        if self.min_google_maps_rank and self.max_google_maps_rank and self.min_google_maps_rank > self.max_google_maps_rank:
            raise ValueError("Minimum rank must not exceed maximum rank.")
        if any(not value.strip() or len(value) > 400 for value in self.qualification_criteria + self.exclusions):
            raise ValueError("Criteria must contain between 1 and 400 characters.")
        if (self.qualification_criteria or self.exclusions) and not self.research_websites:
            raise ValueError("Website research is required to assess qualification criteria.")
        return self


class Evidence(Strict):
    title: str
    url: str
    observation: str


class CriterionCheck(Strict):
    criterion: str
    verdict: Literal["met", "not_met", "unknown"]
    evidence: list[Evidence]


class Assessment(Strict):
    summary: str
    fit: Literal["strong", "possible", "poor", "unknown"]
    reasons: list[str]
    unknowns: list[str]
    evidence: list[Evidence]
    excluded: bool
    criteria_checks: list[CriterionCheck] = Field(default_factory=list,
        description="One check per exact requested positive qualification criterion. met requires supporting cited evidence; absence of evidence is unknown.")


class DiscoveredCompany(Strict):
    name: str
    website: str
    category: str
    location: str
    source_url: str
    observation: str


class DiscoveryBatch(Strict):
    companies: list[DiscoveredCompany]
    limitations: list[str]


class LocationRecommendation(Strict):
    city: str
    state: str
    reason: str
    evidence: list[Evidence]


class LocationRecommendations(Strict):
    locations: list[LocationRecommendation]


class LeadPatch(Strict):
    stage: Literal["new", "qualified", "contacted", "meeting", "won", "lost", "archived"] | None = None
    notes: str | None = Field(default=None, max_length=10000)
    tags: list[str] | None = Field(default=None, max_length=12)
    next_action: str | None = Field(default=None, max_length=500)
    follow_up: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def valid_values(self):
        if self.tags and any(not tag.strip() or len(tag) > 40 for tag in self.tags):
            raise ValueError("Tags must contain 1 to 40 characters.")
        if self.follow_up:
            datetime.fromisoformat(self.follow_up)
        return self


class AdvisorMessage(Strict):
    message: str = Field(min_length=1, max_length=5000)
    message_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class CampaignAction(Strict):
    version: int = Field(ge=1, strict=True)


class BulkLeadPatch(Strict):
    ids: list[str] = Field(min_length=1, max_length=100)
    changes: LeadPatch


class LeadDelete(Strict):
    ids: list[Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]] = Field(min_length=1, max_length=100)
