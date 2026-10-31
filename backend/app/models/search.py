"""Inputs for the sequential Maps → Hunter → NeverBounce workflow."""
import csv
import io
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from app.models.workspace import Strict

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class SearchLocation(Strict):
    city: Text
    state: Text
    min_rank: int | None = Field(default=None, ge=1, le=10000, strict=True)
    max_rank: int | None = Field(default=None, ge=1, le=10000, strict=True)

    @model_validator(mode="after")
    def rank_range(self):
        if self.min_rank and self.max_rank and self.min_rank > self.max_rank:
            raise ValueError("Minimum rank must not exceed maximum rank.")
        return self


class SearchPlan(Strict):
    niche: Text
    locations: list[SearchLocation] = Field(min_length=1, max_length=500)
    places_per_city: int = Field(default=100, ge=100, le=500, strict=True)

    @model_validator(mode="after")
    def unique_locations(self):
        seen = {}
        for location in self.locations:
            key = (location.city.casefold(), location.state.casefold())
            if key in seen and (seen[key].min_rank, seen[key].max_rank) != (location.min_rank, location.max_rank):
                raise ValueError(f"Duplicate city with different ranks: {location.city}, {location.state}.")
            seen[key] = location
        self.locations = list(seen.values())
        return self


class CityImport(Strict):
    csv: str = Field(min_length=1, max_length=500000)


def parse_cities(value: str) -> list[SearchLocation]:
    reader = csv.DictReader(io.StringIO(value.lstrip("\ufeff")), strict=True)
    if not reader.fieldnames:
        raise ValueError("CSV needs a header with city and state columns.")
    headers = [header.strip().lower() for header in reader.fieldnames]
    if len(headers) != len(set(headers)) or not {"city", "state"}.issubset(headers):
        raise ValueError("CSV needs unique headers including city and state.")
    if set(headers) - {"city", "state", "rank", "min_rank", "max_rank"}:
        raise ValueError("Supported CSV columns: city, state, rank, min_rank, max_rank.")
    reader.fieldnames = headers
    locations = []
    for row in reader:
        if None in row:
            raise ValueError(f"CSV line {reader.line_num}: too many columns.")
        if not any((cell or "").strip() for cell in row.values()):
            continue
        try:
            def rank(name):
                cell = (row.get(name) or "").strip()
                return int(cell) if cell else None
            maximum, alias = rank("max_rank"), rank("rank")
            if maximum is not None and alias is not None and maximum != alias:
                raise ValueError("rank and max_rank disagree")
            locations.append(SearchLocation(city=row.get("city") or "", state=row.get("state") or "",
                min_rank=rank("min_rank"), max_rank=maximum if maximum is not None else alias))
        except ValueError:
            raise ValueError(f"CSV line {reader.line_num}: provide city, state, and optional whole-number ranks from 1 to 10000; minimum must not exceed maximum.") from None
        if len(locations) > 500:
            raise ValueError("Import at most 500 cities per search.")
    if not locations:
        raise ValueError("CSV contains no cities.")
    return SearchPlan(niche="import", locations=locations).locations
