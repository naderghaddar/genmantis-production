from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ScrapeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    niche: RequiredText
    city: RequiredText
    state: RequiredText
    min_google_maps_rank: int | None = Field(default=None, ge=1, le=10000, strict=True)
    max_google_maps_rank: int | None = Field(default=None, ge=1, le=10000, strict=True)
    max_leads: int = Field(default=30, ge=1, le=30, strict=True)

    @model_validator(mode="after")
    def check_rank_range(self):
        if self.min_google_maps_rank and self.max_google_maps_rank and self.min_google_maps_rank > self.max_google_maps_rank:
            raise ValueError("Minimum ranking cannot exceed maximum ranking.")
        return self


class ScrapeStatus(BaseModel):
    run_id: str
    status: Literal["running", "succeeded", "failed"]
    result_count: int | None = None
    message: str
