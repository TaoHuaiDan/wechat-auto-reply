from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    bridge_chat_id TEXT NOT NULL UNIQUE,
    chat_name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS bridge_events (
    event_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    bridge_status TEXT NOT NULL,
    local_status TEXT NOT NULL,
    message_count INTEGER NOT NULL,
    received_at REAL NOT NULL,
    acknowledged_at REAL,
    stored_at REAL,
    completed_at REAL,
    last_error TEXT,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bridge_events_local_status
    ON bridge_events(local_status);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    external_message_key TEXT NOT NULL UNIQUE,
    event_id TEXT REFERENCES bridge_events(event_id),
    direction TEXT NOT NULL CHECK(direction IN ('incoming', 'outgoing')),
    sender TEXT,
    message_type TEXT NOT NULL,
    content TEXT NOT NULL,
    time_text TEXT,
    is_self INTEGER,
    observed_at REAL NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_observed
    ON messages(conversation_id, observed_at, id);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE REFERENCES bridge_events(event_id),
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    context_json TEXT NOT NULL,
    raw_model_output TEXT,
    action TEXT CHECK(action IS NULL OR action IN ('IGNORE', 'AUTO_REPLY', 'NEED_HUMAN')),
    proposed_reply TEXT,
    confidence REAL,
    reason TEXT,
    should_send INTEGER,
    sent INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

"""


class Database:
    """Small SQLite wrapper with one short-lived connection per operation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # A file-backed database is intentional: the service may be restarted and
        # must be able to resume an acknowledged-but-not-completed bridge event.
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        if str(self.path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
