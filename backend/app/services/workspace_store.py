"""Durable workspace records. Supabase RLS for accounts; SQLite for local workspaces.

Tokens stay in memory. No service-role key is needed: cloud requests use the
authenticated user's JWT, and Postgres independently enforces ownership.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

import httpx
from fastapi import HTTPException

from app.models.workspace import now
from app.services.lead_index import LeadIndex

KINDS = {"profile", "campaign", "lead", "thread"}


@dataclass
class WorkspaceIdentity:
    owner: str
    token: str | None = field(default=None, repr=False)
    email: str | None = None


class WorkspaceStore:
    def __init__(self, path: str, supabase_url: str = "", publishable_key: str = ""):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS workspace_records (owner TEXT, kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(owner,kind,id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS workspace_outbox (owner TEXT, kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(owner,kind,id))")
        self.db.commit()
        self.lock = RLock()
        self.url, self.key = supabase_url.rstrip("/"), publishable_key
        self.identities: dict[str, WorkspaceIdentity] = {}
        self.owner_locks: dict[str, RLock] = {}

    def identity(self, owner, token=None, email=None):
        with self.lock:
            identity = self.identities.setdefault(owner, WorkspaceIdentity(owner))
            # Existing background tasks see refreshed access tokens from subsequent requests.
            if token:
                identity.token, identity.email = token, email
            return identity

    def operation_lock(self, owner):
        with self.lock:
            return self.owner_locks.setdefault(owner, RLock())

    def _remote(self, identity, method, params=None, payload=None, *, insert_only=False):
        try:
            response = httpx.request(method, self.url + "/rest/v1/gm_workspace_records",
                headers={"apikey": self.key, "Authorization": "Bearer " + identity.token,
                         "Prefer": "resolution=" + ("ignore-duplicates" if insert_only else "merge-duplicates") + ",return=representation"},
                params=params, json=payload, timeout=20)
        except httpx.HTTPError:
            raise HTTPException(503, "Cloud storage is unavailable. Please retry.") from None
        if response.status_code in {401, 403}:
            raise HTTPException(401, "Your account session expired. Sign in again.")
        if response.is_error:
            raise HTTPException(503, "Cloud storage could not save or load this workspace. Check the database migration.")
        return response.json() if response.content else []

    def list(self, identity, kind):
        assert kind in KINDS
        if identity.token:
            rows, offset = [], 0
            while True:
                page = self._remote(identity, "GET", {"owner_id": "eq." + identity.owner, "kind": "eq." + kind,
                    "select": "data", "order": "updated_at.desc,record_id.asc", "limit": "500", "offset": str(offset)})
                rows.extend(item["data"] for item in page)
                if len(page) < 500:
                    return rows
                offset += 500
        with self.lock:
            rows = self.db.execute("SELECT data FROM workspace_records WHERE owner=? AND kind=?", (identity.owner, kind)).fetchall()
        return sorted((json.loads(row[0]) for row in rows), key=lambda item: item.get("updated_at", ""), reverse=True)

    def get(self, identity, kind, record_id):
        assert kind in KINDS
        if identity.token:
            rows = self._remote(identity, "GET", {"owner_id": "eq." + identity.owner, "kind": "eq." + kind,
                "record_id": "eq." + record_id, "select": "data", "limit": "1"})
            if rows:
                return rows[0]["data"]
        else:
            with self.lock:
                row = self.db.execute("SELECT data FROM workspace_records WHERE owner=? AND kind=? AND id=?", (identity.owner, kind, record_id)).fetchone()
            if row:
                return json.loads(row[0])
        raise HTTPException(404, "Record not found in this workspace.")

    def lead_index(self, identity):
        """Read only deduplication keys once, using the owner/kind primary-key prefix.

        Include all statuses and pending cloud recovery results. Provider checks
        then use O(1) membership/count lookups instead of scanning CRM payloads.
        """
        rows = {}
        if identity.token:
            after = None
            while True:
                params = {"owner_id": "eq." + identity.owner, "kind": "eq.lead",
                    "select": "record_id,email:data->lead->contact->>email,domain:data->>domain,website:data->>website,company_domain:data->lead->business->>business_domain,company_website:data->lead->business->>business_website",
                    "order": "record_id.asc", "limit": "500"}
                if after is not None:
                    params["record_id"] = "gt." + after
                page = self._remote(identity, "GET", params)
                rows.update((row["record_id"], row) for row in page)
                if len(page) < 500:
                    break
                after = page[-1]["record_id"]
        table = "workspace_outbox" if identity.token else "workspace_records"
        with self.lock:
            local = self.db.execute(f"""SELECT id,
                json_extract(data,'$.lead.contact.email'), json_extract(data,'$.domain'),
                json_extract(data,'$.website'), json_extract(data,'$.lead.business.business_domain'),
                json_extract(data,'$.lead.business.business_website')
                FROM {table} WHERE owner=? AND kind='lead'""", (identity.owner,)).fetchall()
        fields = ("record_id", "email", "domain", "website", "company_domain", "company_website")
        for row in local:
            rows.setdefault(row[0], dict(zip(fields, row)))
        return LeadIndex(rows.values())

    def insert_lead(self, identity, value):
        """Insert a canonical email-keyed lead without overwriting existing CRM data."""
        value["updated_at"] = now()
        with self.operation_lock(identity.owner):
            if identity.token:
                inserted = self._remote(identity, "POST", {"on_conflict": "owner_id,kind,record_id"}, {
                    "owner_id": identity.owner, "kind": "lead", "record_id": value["id"],
                    "data": value, "updated_at": value["updated_at"]}, insert_only=True)
                if not inserted:
                    return False
            with self.lock, self.db:
                cursor = self.db.execute("INSERT OR IGNORE INTO workspace_records VALUES (?,?,?,?)",
                    (identity.owner, "lead", value["id"], json.dumps(value)))
            return bool(identity.token) or cursor.rowcount == 1

    def save(self, identity, kind, value):
        assert kind in KINDS
        value["updated_at"] = now()
        if identity.token:
            self._remote(identity, "POST", {"on_conflict": "owner_id,kind,record_id"}, {
                "owner_id": identity.owner, "kind": kind, "record_id": value["id"],
                "data": value, "updated_at": value["updated_at"]})
        with self.lock, self.db:
            # Also retain a server-local recovery copy of account records.
            self.db.execute("INSERT OR REPLACE INTO workspace_records VALUES (?,?,?,?)",
                (identity.owner, kind, value["id"], json.dumps(value)))
        return value

    def recovery_save(self, identity, kind, value):
        """Preserve provider results locally if cloud storage fails mid-job."""
        value["updated_at"] = now()
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO workspace_records VALUES (?,?,?,?)",
                (identity.owner, kind, value["id"], json.dumps(value)))
            if identity.token:
                self.db.execute("INSERT OR REPLACE INTO workspace_outbox VALUES (?,?,?,?)",
                    (identity.owner, kind, value["id"], json.dumps(value)))

    def flush_recovery(self, identity):
        if not identity.token:
            return
        with self.operation_lock(identity.owner):
            with self.lock:
                rows = self.db.execute("SELECT kind,id,data FROM workspace_outbox WHERE owner=?", (identity.owner,)).fetchall()
            for kind, record_id, data in rows:
                value = json.loads(data)
                try:
                    current = self.get(identity, kind, record_id)
                except HTTPException as error:
                    if error.status_code != 404:
                        raise
                    current = None
                if current is None or current.get("updated_at", "") < value.get("updated_at", ""):
                    self.save(identity, kind, value)
                with self.lock, self.db:
                    # A background task may have written a newer recovery record meanwhile.
                    self.db.execute("DELETE FROM workspace_outbox WHERE owner=? AND kind=? AND id=? AND data=?", (identity.owner,kind,record_id,data))

    def close(self):
        self.db.close()
