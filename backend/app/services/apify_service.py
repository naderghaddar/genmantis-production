from copy import deepcopy
from typing import Any

from apify_client import ApifyClient
from fastapi import HTTPException

from app.config import ACTOR_ID, get_api_token
from app.models.schemas import ScrapeRequest, ScrapeStatus
from app.services.csv_service import csv_filename

FIXED_SETTINGS = {
    "enableCompetitorAnalysis": False,
    "includeWebResults": False,
    "maxCompetitorsToAnalyze": 30,
    "maxCrawledPlacesPerSearch": 70,
    "maximumLeadsEnrichmentRecords": 0,
    "scrapeContacts": False,
    "scrapeDirectories": False,
    "scrapeImageAuthors": False,
    "scrapeOrderOnline": False,
    "scrapePlaceDetailPage": False,
    "scrapeReviewsPersonalData": True,
    "scrapeSocialMediaProfiles": {
        "facebooks": False, "instagrams": False, "tiktoks": False,
        "twitters": False, "youtubes": False,
    },
    "scrapeTableReservationProvider": False,
    "skipClosedPlaces": False,
    "verifyLeadsEnrichmentEmails": False,
}


def build_actor_input(request: ScrapeRequest) -> dict[str, Any]:
    return {**deepcopy(FIXED_SETTINGS), "searchStringsArray": [request.niche],
            "locationQuery": f"{request.city}, {request.state}"}


class ApifyService:
    def __init__(self, client: ApifyClient) -> None:
        self.client = client

    def start(self, request: ScrapeRequest, *, business_limit: int = 70) -> ScrapeStatus:
        if type(business_limit) is not int or not 70 <= business_limit <= 350:
            raise ValueError("Business limit must be between 70 and 350.")
        actor_input = build_actor_input(request)
        actor_input["maxCrawledPlacesPerSearch"] = business_limit
        run = self.client.actor(ACTOR_ID).start(run_input=actor_input)
        return self._status(run)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.client.run(run_id).get()
        if not run or run.get("actId") != ACTOR_ID:
            raise HTTPException(404, "Scraping run not found.")
        return run

    def status(self, run_id: str) -> ScrapeStatus:
        return self._status(self.get_run(run_id))

    def _status(self, run: dict[str, Any]) -> ScrapeStatus:
        status = run["status"]
        if status == "SUCCEEDED":
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                raise HTTPException(502, "Apify did not return a results dataset.")
            dataset = self.client.dataset(dataset_id).get()
            if dataset is None:
                raise HTTPException(502, "Apify results dataset is unavailable.")
            count = dataset.get("itemCount")
            return ScrapeStatus(run_id=run["id"], status="succeeded", result_count=count,
                                message="Scraping complete.")
        if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
            messages = {"FAILED": "Scraping failed. Please try again.",
                        "ABORTED": "Scraping was aborted. Please try again.",
                        "TIMED-OUT": "Scraping timed out. Please try again."}
            return ScrapeStatus(run_id=run["id"], status="failed", message=messages[status])
        if status not in {"READY", "RUNNING", "TIMING-OUT", "ABORTING"}:
            raise HTTPException(502, "Apify returned an unrecognized run status.")
        return ScrapeStatus(run_id=run["id"], status="running", message="Scraping businesses...")

    def download(self, run_id: str) -> tuple[list[dict[str, Any]], str]:
        run = self.get_run(run_id)
        if run["status"] != "SUCCEEDED":
            raise HTTPException(409, "CSV is available only after a successful scrape.")
        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            raise HTTPException(502, "Apify did not return a results dataset.")
        items = list(self.client.dataset(dataset_id).iterate_items())
        if not items:
            raise HTTPException(404, "No businesses were found. Try another niche or location.")
        # Recover the original inputs from Apify, so filenames survive server restarts.
        record = self.client.key_value_store(run["defaultKeyValueStoreId"]).get_record("INPUT")
        actor_input = record.get("value", {}) if record else {}
        searches = actor_input.get("searchStringsArray", [])
        city, _, state = actor_input.get("locationQuery", "").rpartition(", ")
        filename = csv_filename(searches[0] if searches else "businesses", city, state)
        return items, filename

    def results(self, run_id: str) -> list[dict[str, Any]]:
        run = self.get_run(run_id)
        if run["status"] != "SUCCEEDED":
            raise HTTPException(409, "Apify run has not succeeded.")
        if not run.get("defaultDatasetId"):
            raise HTTPException(502, "Apify did not return a results dataset.")
        return list(self.client.dataset(run["defaultDatasetId"]).iterate_items())


def get_apify_service() -> ApifyService:
    try:
        token = get_api_token()
    except ValueError as error:
        raise HTTPException(503, str(error)) from error
    # No automatic retries on job creation: a timed-out POST may already have started a run.
    return ApifyService(ApifyClient(token, max_retries=0, timeout_secs=30))
