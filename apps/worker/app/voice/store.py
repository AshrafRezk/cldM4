"""SQLite for published scripts and live call sessions.

Local on purpose: a call must be answerable while Neon is suspended or the org
is having a bad day. Neon is never on the Twilio webhook path.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_scripts (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    display_name TEXT,
    definition TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS voice_numbers (
    number TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    script_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_sessions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    call_sid TEXT NOT NULL UNIQUE,
    from_number TEXT,
    to_number TEXT,
    script_id TEXT NOT NULL,
    script_version INTEGER NOT NULL,
    definition TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT,
    attempt INTEGER NOT NULL DEFAULT 1,
    language TEXT,
    answers TEXT NOT NULL DEFAULT '{}',
    turns TEXT NOT NULL DEFAULT '[]',
    recording_url TEXT,
    commit_doc TEXT,
    committed_ids TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    acked_at REAL
);
CREATE INDEX IF NOT EXISTS voice_sessions_tenant ON voice_sessions (tenant_id, created_at);
CREATE TABLE IF NOT EXISTS voice_web_links (
    token_hash TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    script_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    revoked_at REAL
);
CREATE TABLE IF NOT EXISTS voice_replies (
    call_sid TEXT NOT NULL,
    step TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    reply TEXT NOT NULL,
    PRIMARY KEY (call_sid, step, attempt)
);
"""

JSON_COLUMNS = ("definition", "answers", "turns", "commit_doc", "committed_ids")


class NumberTaken(Exception):
    """An inbound number is already routed to another tenant."""


class VoiceStore:
    def __init__(self, path: str) -> None:
        self.path = os.path.expanduser(path)
        self._lock = threading.Lock()
        self._ready = False

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if not self._ready:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                if not self._ready:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.executescript(SCHEMA)
                    _migrate(conn)
                    self._ready = True
                with conn:
                    yield conn
            finally:
                conn.close()

    # Scripts -----------------------------------------------------------------

    def upsert_script(self, tenant_id: str, script: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        numbers = script.get("inbound_numbers") or []
        with self._db() as conn:
            for number in numbers:
                owner = conn.execute(
                    "SELECT tenant_id, script_id FROM voice_numbers WHERE number = ?", (number,)
                ).fetchone()
                # Within a tenant the latest publish wins the number.
                if owner and owner["tenant_id"] != tenant_id:
                    raise NumberTaken(number)
            row = conn.execute(
                "SELECT version FROM voice_scripts WHERE tenant_id = ? AND id = ?",
                (tenant_id, script["id"]),
            ).fetchone()
            version = (row["version"] + 1) if row else 1
            conn.execute(
                "INSERT OR REPLACE INTO voice_scripts "
                "(tenant_id, id, version, display_name, definition, active, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    tenant_id,
                    script["id"],
                    version,
                    script.get("display_name"),
                    json.dumps(script, ensure_ascii=False),
                    1 if script.get("active", True) else 0,
                    now,
                ),
            )
            # A republish owns exactly the numbers it lists now.
            conn.execute(
                "DELETE FROM voice_numbers WHERE tenant_id = ? AND script_id = ?",
                (tenant_id, script["id"]),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO voice_numbers (number, tenant_id, script_id) VALUES (?, ?, ?)",
                [(number, tenant_id, script["id"]) for number in numbers],
            )
        return {"id": script["id"], "version": version, "updated_at": iso(now)}

    def list_scripts(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM voice_scripts WHERE tenant_id = ? ORDER BY id", (tenant_id,)
            ).fetchall()
        out = []
        for row in rows:
            definition = json.loads(row["definition"])
            out.append(
                {
                    "id": row["id"],
                    "display_name": row["display_name"],
                    "version": row["version"],
                    "inbound_numbers": definition.get("inbound_numbers") or [],
                    "active": bool(row["active"]),
                    "updated_at": iso(row["updated_at"]),
                }
            )
        return out

    def script_for_number(self, number: str) -> tuple[str, int, dict[str, Any]] | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT s.tenant_id, s.version, s.definition FROM voice_numbers n "
                "JOIN voice_scripts s ON s.tenant_id = n.tenant_id AND s.id = n.script_id "
                "WHERE n.number = ? AND s.active = 1",
                (number,),
            ).fetchone()
        if row is None:
            return None
        return row["tenant_id"], row["version"], json.loads(row["definition"])

    def script_by_id(self, tenant_id: str, script_id: str) -> tuple[int, dict[str, Any]] | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT version, definition FROM voice_scripts "
                "WHERE tenant_id = ? AND id = ? AND active = 1",
                (tenant_id, script_id),
            ).fetchone()
        if row is None:
            return None
        return row["version"], json.loads(row["definition"])

    # Sessions ----------------------------------------------------------------

    def create_session(
        self,
        *,
        tenant_id: str,
        call_sid: str,
        from_number: str,
        to_number: str,
        script: dict[str, Any],
        script_version: int,
        first_step: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        session_id = str(uuid.uuid4())
        with self._db() as conn:
            conn.execute(
                "INSERT INTO voice_sessions (id, tenant_id, call_sid, from_number, to_number, "
                "script_id, script_version, definition, status, current_step, attempt, language, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'in_progress', ?, 1, ?, ?, ?)",
                (
                    session_id,
                    tenant_id,
                    call_sid,
                    from_number,
                    to_number,
                    script["id"],
                    script_version,
                    json.dumps(script, ensure_ascii=False),
                    first_step,
                    language,
                    now,
                    now,
                ),
            )
        session = self.session_by_call(call_sid)
        assert session is not None
        return session

    def session_by_call(self, call_sid: str) -> dict[str, Any] | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM voice_sessions WHERE call_sid = ?", (call_sid,)
            ).fetchone()
        return _session(row)

    def get_session(self, tenant_id: str, session_id: str) -> dict[str, Any] | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM voice_sessions WHERE id = ? AND tenant_id = ?",
                (session_id, tenant_id),
            ).fetchone()
        return _session(row)

    def list_sessions(
        self, tenant_id: str, *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM voice_sessions WHERE tenant_id = ?"
        args: list[Any] = [tenant_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._db() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_session(row) for row in rows]  # type: ignore[misc]

    def update_session(self, session_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        columns = []
        values = []
        for name, value in fields.items():
            if name in JSON_COLUMNS and value is not None:
                value = json.dumps(value, ensure_ascii=False)
            columns.append(f"{name} = ?")
            values.append(value)
        values.append(session_id)
        with self._db() as conn:
            conn.execute(f"UPDATE voice_sessions SET {', '.join(columns)} WHERE id = ?", values)

    # Browser call links ------------------------------------------------------

    def create_web_link(self, tenant_id: str, script_id: str) -> str:
        """The token is shown once; only its hash is stored."""
        token = "cl_" + secrets.token_urlsafe(24)
        with self._db() as conn:
            conn.execute(
                "INSERT INTO voice_web_links (token_hash, tenant_id, script_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (_hash(token), tenant_id, script_id, time.time()),
            )
        return token

    def revoke_web_links(self, tenant_id: str, script_id: str) -> int:
        with self._db() as conn:
            cur = conn.execute(
                "UPDATE voice_web_links SET revoked_at = ? "
                "WHERE tenant_id = ? AND script_id = ? AND revoked_at IS NULL",
                (time.time(), tenant_id, script_id),
            )
        return cur.rowcount

    def web_link(self, token: str) -> tuple[str, str] | None:
        if not token.startswith("cl_") or len(token) > 80:
            return None
        with self._db() as conn:
            row = conn.execute(
                "SELECT tenant_id, script_id FROM voice_web_links "
                "WHERE token_hash = ? AND revoked_at IS NULL",
                (_hash(token),),
            ).fetchone()
        return (row["tenant_id"], row["script_id"]) if row else None

    # Twilio retry cache ------------------------------------------------------

    def reply_for(self, call_sid: str, step: str, attempt: int) -> dict[str, Any] | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT reply FROM voice_replies WHERE call_sid = ? AND step = ? AND attempt = ?",
                (call_sid, step, attempt),
            ).fetchone()
        return json.loads(row["reply"]) if row else None

    def save_reply(self, call_sid: str, step: str, attempt: int, reply: dict[str, Any]) -> None:
        with self._db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO voice_replies (call_sid, step, attempt, reply) "
                "VALUES (?, ?, ?, ?)",
                (call_sid, step, attempt, json.dumps(reply, ensure_ascii=False)),
            )

    # Retention ---------------------------------------------------------------

    def purge_expired(self, ttl_days: float) -> int:
        """Transcripts are prompts. Committed or abandoned calls go after the TTL;
        so does a ready call nobody ever acked."""
        cutoff = time.time() - ttl_days * 86400
        with self._db() as conn:
            sids = [
                row["call_sid"]
                for row in conn.execute(
                    "SELECT call_sid FROM voice_sessions WHERE COALESCE(acked_at, updated_at) < ?",
                    (cutoff,),
                )
            ]
            conn.executemany("DELETE FROM voice_replies WHERE call_sid = ?", [(s,) for s in sids])
            conn.executemany("DELETE FROM voice_sessions WHERE call_sid = ?", [(s,) for s in sids])
        return len(sids)


def _migrate(conn: sqlite3.Connection) -> None:
    """Columns added after the first deploy (CREATE TABLE IF NOT EXISTS skips them)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(voice_sessions)")}
    if "language" not in columns:
        conn.execute("ALTER TABLE voice_sessions ADD COLUMN language TEXT")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _session(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for name in JSON_COLUMNS:
        if data.get(name) is not None:
            data[name] = json.loads(data[name])
    return data


def iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))

