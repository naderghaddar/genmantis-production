import csv
import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.models.leads import Business, Contact, Lead, Verification
from app.models.schemas import ScrapeRequest
from app.services.apify_service import ApifyService, build_actor_input
from app.services.enrichment_pipeline import EnrichmentPipeline
from app.services.hunter_service import HunterSearch
from app.services.qualification_service import organic_rank, qualify


def context(rank=25, **extra):
    return {"rank": rank, "searchString": "Chiropractors", "searchPageUrl": "https://www.google.com/maps/search/Chiropractors/@30,-97,12z",
            "searchPageLoadedUrl": None, "isAdvertisement": False, **extra}


def test_actor_rank_meaning_is_verified_from_public_schema():
    evidence = json.loads((Path(__file__).parent / "fixtures" / "apify_rank_schema.json").read_text())
    assert evidence["fields"]["rank"]["description"] == "Position in search results (1-based)"
    assert evidence["build_id"]


@pytest.mark.parametrize("source", [
    context(None), context(True), context(0), context(-1), context(2.5), context(float("nan")),
    context(25, searchString=""), context(25, searchString="Direct Detail URL: https://google.com/maps/place/x"),
    context(25, searchPageUrl=None), context(25, searchPageUrl="https://google.evil.com/maps/search/x"),
    context(25, isAdvertisement=True), context(25, isAdvertisement=None),
])
def test_missing_unreliable_or_advertised_rank_is_unknown(source):
    assert organic_rank(source) is None


def test_conservative_best_observed_position_across_contexts():
    original = context(25)
    original["duplicate_records"] = [context(5), context(100, isAdvertisement=True)]
    lead = Lead(business=Business(original=original), run_id="run")
    assert not qualify(lead, ScrapeRequest(niche="x", city="y", state="TX", min_google_maps_rank=21))
    assert lead.google_maps_rank == 5 and len(lead.ranking_evidence) == 3
    assert lead.filter_reason == "rank_below_requested_minimum"


def test_rating_and_review_counts_are_not_ranking():
    lead = Lead(business=Business(original={"totalScore": 5, "reviewsCount": 25}), run_id="run")
    assert not qualify(lead, ScrapeRequest(niche="x", city="y", state="TX", min_google_maps_rank=21))
    assert lead.google_maps_rank is None


def test_filter_before_hunter_preserves_excluded_rows(settings, sdk):
    items = [{"title": f"Clinic {i}", "placeId": str(i), "website": f"https://clinic{i}.com",
              **context(10 if i < 25 else 25)} for i in range(50)]
    sdk.dataset.return_value.iterate_items.return_value = iter(items)
    hunter, nb = MagicMock(), MagicMock()
    hunter.search.side_effect = lambda domain: HunterSearch(contacts=[Contact(email=f"owner@{domain}", job_title="Owner")])
    nb.verify.return_value = Verification(result="valid")
    updates = []
    request = ScrapeRequest(niche="Chiropractors", city="Austin", state="Texas", min_google_maps_rank=21)
    exports = EnrichmentPipeline(settings, ApifyService(sdk), hunter, nb).run("run", request, lambda **values: updates.append(values))
    assert hunter.search.call_count == nb.verify.call_count == 25
    assert {call.args[0] for call in hunter.search.call_args_list} == {f"clinic{i}.com" for i in range(25, 50)}
    rows = list(csv.DictReader(io.StringIO(exports["all"][0].decode("utf-8-sig"))))
    assert len(rows) == 50 and sum(row["enrichment_status"] == "filtered_out" for row in rows) == 25
    assert all(row["filter_reason"] for row in rows[:25])
    assert updates[-1]["progress"].businesses_eligible == 25
    assert updates[-1]["progress"].businesses_filtered == 25


def test_missing_rank_prevents_all_enrichment_and_reports_warning(settings, sdk):
    sdk.dataset.return_value.iterate_items.return_value = iter([{"title": "Clinic", "website": "https://clinic.com"}])
    hunter, nb = MagicMock(), MagicMock()
    updates = []
    exports = EnrichmentPipeline(settings, ApifyService(sdk), hunter, nb).run("run",
        ScrapeRequest(niche="x", city="Austin", state="Texas", min_google_maps_rank=21), lambda **values: updates.append(values))
    hunter.search.assert_not_called()
    nb.verify.assert_not_called()
    assert any(update.get("warnings") for update in updates)
    assert len(list(csv.DictReader(io.StringIO(exports["verified"][0].decode("utf-8-sig"))))) == 0


def test_maximum_enrichment_count_does_not_change_fixed_actor_settings(settings, sdk):
    sdk.dataset.return_value.iterate_items.return_value = iter([
        {"title": f"Clinic {i}", "website": f"https://clinic{i}.com", **context(25)} for i in range(5)])
    request = ScrapeRequest(niche="x", city="Austin", state="Texas", max_leads=2, min_google_maps_rank=21)
    assert build_actor_input(request)["maxCrawledPlacesPerSearch"] == 30
    hunter, nb = MagicMock(), MagicMock()
    hunter.search.return_value = HunterSearch()
    updates = []
    EnrichmentPipeline(settings, ApifyService(sdk), hunter, nb).run("run", request, lambda **values: updates.append(values))
    assert hunter.search.call_count == 2
    assert updates[-1]["progress"].businesses_filtered == 3
