from urllib.parse import urlsplit
import math

from app.models.leads import Lead
from app.models.schemas import ScrapeRequest
from app.services.domain_service import EXTRACT


def search_contexts(record: dict) -> list[dict]:
    contexts = [{key: record.get(key) for key in (
        "rank", "searchString", "searchPageUrl", "searchPageLoadedUrl", "isAdvertisement",
    )}]
    duplicates = record.get("duplicate_records", [])
    for duplicate in duplicates if isinstance(duplicates, list) else []:
        if isinstance(duplicate, dict):
            contexts.extend(search_contexts(duplicate))
    return contexts


def organic_rank(context: dict) -> int | None:
    rank = context.get("rank")
    if isinstance(rank, bool) or not isinstance(rank, (int, float)) or not math.isfinite(rank) or rank < 1 or rank > 10000 or int(rank) != rank:
        return None
    query = context.get("searchString")
    if not isinstance(query, str) or not query.strip() or query.startswith("Direct Detail URL:"):
        return None
    urls = [context.get("searchPageLoadedUrl"), context.get("searchPageUrl")]
    valid_context = False
    for url in urls:
        if isinstance(url, str):
            try:
                parsed = urlsplit(url)
                host = (parsed.hostname or "").lower()
                extracted = EXTRACT(host)
                if extracted.domain == "google" and extracted.suffix and "/maps/search" in parsed.path:
                    valid_context = True
            except ValueError:
                pass
    # Unknown ad status cannot establish an organic position.
    return int(rank) if valid_context and context.get("isAdvertisement") is False else None


def qualify(lead: Lead, request: ScrapeRequest) -> bool:
    lead.ranking_evidence = search_contexts(lead.business.original)
    ranks = [rank for context in lead.ranking_evidence if (rank := organic_rank(context)) is not None]
    # Conservative policy: use the best (lowest) observed organic rank across company contexts.
    # A business observed in the top ten anywhere in this source search cannot be labeled outside it.
    lead.google_maps_rank = min(ranks) if ranks else None
    if request.min_google_maps_rank is None and request.max_google_maps_rank is None:
        return True
    if lead.google_maps_rank is None:
        lead.filter_reason = "ranking_unknown_or_organic_search_context_unavailable"
    elif request.min_google_maps_rank and lead.google_maps_rank < request.min_google_maps_rank:
        lead.filter_reason = "rank_below_requested_minimum"
    elif request.max_google_maps_rank and lead.google_maps_rank > request.max_google_maps_rank:
        lead.filter_reason = "rank_above_requested_maximum"
    if lead.filter_reason:
        lead.enrichment_status = "filtered_out"
        lead.failure_reason = lead.filter_reason
        return False
    return True
