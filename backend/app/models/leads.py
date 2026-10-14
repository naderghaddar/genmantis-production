from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Business(BaseModel):
    business_name: str | None = None
    business_category: str | None = None
    business_website: str | None = None
    business_domain: str | None = None
    business_phone: str | None = None
    business_address: str | None = None
    business_city: str | None = None
    business_state: str | None = None
    business_postal_code: str | None = None
    google_maps_url: str | None = None
    google_place_id: str | None = None
    google_rating: float | None = None
    google_review_count: int | None = None
    original: dict[str, Any] = Field(default_factory=dict)


class Contact(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    seniority: str | None = None
    department: str | None = None
    decision_maker: bool | None = None
    provider_type: str | None = None
    confidence: float | None = None
    phone: str | None = None
    linkedin: str | None = None
    twitter: str | None = None
    sources: list[Any] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class Verification(BaseModel):
    result: Literal["valid", "invalid", "disposable", "catchall", "unknown", "verification_error"]
    status: str | None = None
    flags: list[str] = Field(default_factory=list)
    suggested_correction: str | None = None
    failure_reason: str | None = None


class CheckedContact(BaseModel):
    company_domain: str
    contact: Contact
    verification: Verification


class Lead(BaseModel):
    business: Business
    contact: Contact | None = None
    contact_type: Literal["decision_maker", "generic"] | None = None
    verification: Verification | None = None
    verified: bool = False
    enrichment_status: str = "pending"
    failure_reason: str | None = None
    hunter_search_reason: str | None = None
    hunter_metadata: dict[str, Any] = Field(default_factory=dict)
    verification_attempts: list[dict[str, Any]] = Field(default_factory=list)
    contact_scope: str | None = None
    shared_domain: bool = False
    run_id: str
    enrichment_timestamp: datetime | None = None
    google_maps_rank: int | None = None
    ranking_evidence: list[dict[str, Any]] = Field(default_factory=list)
    filter_reason: str | None = None


RunStage = Literal["pending", "scraping", "enriching", "verifying", "exporting", "completed", "failed"]


class RunProgress(BaseModel):
    businesses_scraped: int = 0
    businesses_processed: int = 0
    domains_searched: int = 0
    contacts_found: int = 0
    verified_emails: int = 0
    generic_emails_selected: int = 0
    businesses_without_contact: int = 0
    failed_enrichments: int = 0
    businesses_eligible: int = 0
    businesses_filtered: int = 0
    unverified_contacts: int = 0


class RunStatus(BaseModel):
    run_id: str
    apify_run_id: str | None = None
    status: RunStage = "pending"
    message: str = "Waiting to start..."
    progress: RunProgress = Field(default_factory=RunProgress)
    failure_reason: str | None = None
    downloads_ready: bool = False
    created_at: datetime
    completed_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
