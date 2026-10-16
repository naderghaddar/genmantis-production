import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
ACTOR_ID = "nwua9Gu5YrADL7ZDj"


def get_api_token() -> str:
    token = os.getenv("APIFY_API_TOKEN", "").strip()
    if not token or token == "your_token_here":
        raise ValueError("Set APIFY_API_TOKEN in backend/.env before finding leads.")
    return token


@dataclass(frozen=True)
class Settings:
    apify_token: str = field(default="", repr=False)
    hunter_key: str = field(default="", repr=False)
    neverbounce_key: str = field(default="", repr=False)
    openai_key: str = field(default="", repr=False)
    openai_model: str = "gpt-5.4-mini"
    agent_db_path: str = str(Path(__file__).resolve().parents[1] / ".data" / "agent.sqlite3")
    workspace_db_path: str = str(Path(__file__).resolve().parents[1] / ".data" / "workspace.sqlite3")
    supabase_url: str = ""
    supabase_publishable_key: str = field(default="", repr=False)
    allow_local_workspace: bool = True
    research_max_calls: int = 60
    max_verification_attempts: int = 4
    max_hunter_results: int = 10
    max_hunter_pages: int = 1
    concurrency: int = 3
    provider_retries: int = 2
    provider_interval: float = 0.25
    max_active_runs: int = 1
    max_stored_runs: int = 20
    retention_seconds: int = 3600
    apify_poll_interval: float = 3
    apify_wait_timeout: int = 3600

    def require_keys(self) -> None:
        names = [("APIFY_API_TOKEN", self.apify_token), ("HUNTER_API_KEY", self.hunter_key),
                 ("NEVERBOUNCE_API_KEY", self.neverbounce_key)]
        missing = [name for name, value in names if not value or value == "your_token_here"]
        if missing:
            raise ValueError("Set " + ", ".join(missing) + " in backend/.env before starting enrichment.")


def get_settings() -> Settings:
    def number(name: str, default: float, low: float, high: float, integer: bool = True):
        try:
            value = int(os.getenv(name, str(default))) if integer else float(os.getenv(name, str(default)))
        except ValueError as error:
            raise ValueError(f"Invalid backend configuration: {name}.") from error
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}.")
        return value

    return Settings(
        apify_token=os.getenv("APIFY_API_TOKEN", "").strip(),
        hunter_key=os.getenv("HUNTER_API_KEY", "").strip(),
        neverbounce_key=os.getenv("NEVERBOUNCE_API_KEY", "").strip(),
        openai_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini",
        agent_db_path=os.getenv("AGENT_DB_PATH", str(Path(__file__).resolve().parents[1] / ".data" / "agent.sqlite3")),
        workspace_db_path=os.getenv("WORKSPACE_DB_PATH", str(Path(__file__).resolve().parents[1] / ".data" / "workspace.sqlite3")),
        supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
        supabase_publishable_key=os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip(),
        allow_local_workspace=os.getenv("ALLOW_LOCAL_WORKSPACE", "true").lower() == "true",
        research_max_calls=number("RESEARCH_MAX_CALLS", 60, 2, 100),
        max_verification_attempts=number("MAX_VERIFICATION_ATTEMPTS_PER_BUSINESS", 4, 1, 10),
        max_hunter_results=number("MAX_HUNTER_RESULTS_PER_DOMAIN", 10, 1, 100),
        max_hunter_pages=number("MAX_HUNTER_PAGES_PER_DOMAIN", 1, 1, 10),
        concurrency=number("ENRICHMENT_CONCURRENCY", 3, 1, 5),
        provider_retries=number("PROVIDER_MAX_RETRIES", 2, 0, 3),
        provider_interval=number("PROVIDER_MIN_INTERVAL_SECONDS", 0.25, 0.1, 10, False),
        max_active_runs=number("MAX_ACTIVE_RUNS", 1, 1, 3),
        max_stored_runs=number("MAX_STORED_RUNS", 20, 3, 100),
        retention_seconds=number("RUN_RETENTION_SECONDS", 3600, 60, 86400),
        apify_poll_interval=number("APIFY_POLL_INTERVAL_SECONDS", 3, 1, 30, False),
        apify_wait_timeout=number("APIFY_WAIT_TIMEOUT_SECONDS", 3600, 60, 21600),
    )
