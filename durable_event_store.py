"""Durable run, prompt, and event storage for the CAF web API.

The web UI may stream events over SSE, but an SSE connection is inherently
ephemeral.  This store is the authoritative record: events are committed to
SQLite before they are offered to any live subscriber, so clients can replay
from a sequence number after a reconnect.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DurableEventStore:
    """Small SQLite/WAL store suitable for a single CAF host.

    Each operation opens a short-lived connection.  That avoids sharing a
    sqlite cursor across Flask request threads and keeps transaction boundaries
    explicit around event sequence allocation.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS prompts (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    completed_at TEXT,
                    prompt_text TEXT NOT NULL,
                    error TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE INDEX IF NOT EXISTS prompts_run_id_idx ON prompts(run_id, submitted_at);
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    prompt_id TEXT,
                    type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES runs(id),
                    FOREIGN KEY(prompt_id) REFERENCES prompts(id)
                );
                CREATE INDEX IF NOT EXISTS events_prompt_id_idx ON events(prompt_id, sequence);
                """
            )

    def recover_interrupted_work(self) -> None:
        """Make prompts from a previous crashed CAF process terminal.

        The current CAF agent worker is process-local.  A restart cannot resume
        its asyncio task, so leaving its prompt ``running`` would be less
        truthful than recording an explicit durable failure for a client to
        inspect or retry.
        """
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """UPDATE prompts SET status='failed', completed_at=?,
                   error=COALESCE(error, 'CAF restarted before this prompt completed.')
                   WHERE status IN ('queued', 'running')""",
                (now,),
            )
            connection.execute(
                """UPDATE runs SET status='failed', updated_at=?
                   WHERE status IN ('starting', 'running', 'stopping')""",
                (now,),
            )

    def create_run(self, run_id: str, status: str, metadata: dict[str, Any] | None = None) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs(id, status, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                    updated_at=excluded.updated_at, metadata_json=excluded.metadata_json
                """,
                (run_id, status, now, now, json.dumps(metadata or {}, default=str)),
            )

    def update_run_status(self, run_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status=?, updated_at=? WHERE id=?",
                (status, _now(), run_id),
            )

    def create_prompt(self, prompt_id: str, run_id: str, prompt_text: str, status: str = "queued") -> dict[str, Any]:
        submitted_at = _now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO prompts(id, run_id, status, submitted_at, prompt_text)
                   VALUES (?, ?, ?, ?, ?)""",
                (prompt_id, run_id, status, submitted_at, prompt_text),
            )
        return self.get_prompt(prompt_id) or {}

    def update_prompt_status(self, prompt_id: str, status: str, error: str | None = None) -> None:
        terminal = status in {"completed", "failed", "cancelled"}
        with self._connect() as connection:
            connection.execute(
                """UPDATE prompts
                   SET status=?, error=COALESCE(?, error),
                       completed_at=CASE WHEN ? THEN ? ELSE completed_at END
                   WHERE id=?""",
                (status, error, terminal, _now(), prompt_id),
            )

    def get_prompt(self, prompt_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM prompts WHERE id=?", (prompt_id,)).fetchone()
        return dict(row) if row else None

    def append_event(
        self,
        run_id: str,
        prompt_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Commit an ordered event and return the client-facing record."""
        created_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM events WHERE run_id=?",
                (run_id,),
            ).fetchone()
            sequence = int(row["next_sequence"])
            event = {
                **payload,
                "type": event_type,
                "run_id": run_id,
                "prompt_id": prompt_id,
                "sequence": sequence,
                "timestamp": created_at,
            }
            connection.execute(
                """INSERT INTO events(run_id, sequence, prompt_id, type, created_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, sequence, prompt_id, event_type, created_at, json.dumps(event, default=str)),
            )
            connection.commit()
        return event

    def events_after(self, run_id: str, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM events
                   WHERE run_id=? AND sequence>? ORDER BY sequence ASC LIMIT ?""",
                (run_id, max(0, int(after)), limit),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]
