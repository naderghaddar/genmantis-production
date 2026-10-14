import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, RLock
from uuid import uuid4

from fastapi import HTTPException

from app.models.agent_schemas import ChatMessage, ConversationData, LeadSearchPlan

WELCOME = "Hi! I'm GenMantis. Tell me what kind of businesses you're looking to reach, and I'll help you prepare a lead search."


class ConversationStore:
    """Small SQLite repository; service code owns validation, approval, and execution."""
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, plan_id TEXT UNIQUE, owner TEXT, updated TEXT, data TEXT)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS source_runs (id TEXT PRIMARY KEY, owner TEXT)")
        self.connection.commit()
        self.lock = RLock()
        self.operation_locks: dict[str, Lock] = {}

    def save(self, value: ConversationData) -> None:
        value.updated_at = datetime.now(timezone.utc)
        with self.lock, self.connection:
            self.connection.execute("INSERT OR REPLACE INTO conversations VALUES (?, ?, ?, ?, ?)",
                (value.id, value.plan.id, value.owner_id, value.updated_at.isoformat(), value.model_dump_json()))

    def create(self, owner: str) -> ConversationData:
        with self.lock:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            self.connection.execute("DELETE FROM conversations WHERE updated < ?", (cutoff,))
            if self.connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] >= 100:
                self.connection.commit()
                raise HTTPException(429, "Conversation storage is full. Try again after older sessions expire.")
            now = datetime.now(timezone.utc)
            value = ConversationData(id=uuid4().hex, owner_id=owner, created_at=now, updated_at=now,
                messages=[ChatMessage(id=uuid4().hex, role="assistant", content=WELCOME)],
                plan=LeadSearchPlan(id=uuid4().hex, niche=None, city=None, state=None, country=None,
                    business_size_preference=None, min_google_maps_rank=None, max_google_maps_rank=None,
                    max_leads=30, additional_preferences=[], unsupported_preferences=[]))
            self.save(value)
            return value

    def get(self, key: str, owner: str, by_plan: bool = False) -> ConversationData:
        with self.lock:
            column = "plan_id" if by_plan else "id"
            row = self.connection.execute(f"SELECT data FROM conversations WHERE {column} = ? AND owner = ?", (key, owner)).fetchone()
        if not row:
            raise HTTPException(404, "Conversation or search plan not found.")
        value = ConversationData.model_validate_json(row[0])
        if value.updated_at < datetime.now(timezone.utc) - timedelta(hours=24):
            raise HTTPException(410, "Conversation expired. Start a new conversation.")
        return value

    def operation_lock(self, conversation_id: str) -> Lock:
        with self.lock:
            # Storage capacity bounds conversation locks too; stale keys are removed on creation.
            existing = {row[0] for row in self.connection.execute("SELECT id FROM conversations")}
            for key in list(self.operation_locks):
                if key not in existing and not self.operation_locks[key].locked():
                    del self.operation_locks[key]
            return self.operation_locks.setdefault(conversation_id, Lock())

    def close(self):
        self.connection.close()

    def claim_source_run(self, run_id: str, owner: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("INSERT OR IGNORE INTO source_runs VALUES (?, ?)", (run_id, owner))

    def require_source_owner(self, run_id: str, owner: str) -> None:
        with self.lock:
            row = self.connection.execute("SELECT owner FROM source_runs WHERE id = ?", (run_id,)).fetchone()
        if not row or row[0] != owner:
            raise HTTPException(404, "Scraping run not found in this browser session.")
