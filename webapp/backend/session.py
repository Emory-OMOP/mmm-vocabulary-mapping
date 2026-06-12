"""SQLite chat session persistence."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


def _get_db() -> sqlite3.Connection:
    """Get a connection to the sessions database, creating tables if needed."""
    db_path = settings.sessions_db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            title TEXT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_calls TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, created_at);
    """)
    return conn


def create_session(provider: str, model: str, title: str | None = None) -> str:
    """Create a new chat session. Returns the session ID."""
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with _get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, title, provider, model) VALUES (?, ?, ?, ?, ?)",
            (session_id, now, title, provider, model),
        )
    return session_id


def list_sessions(limit: int = 50) -> list[dict]:
    """List chat sessions ordered by most recent first."""
    with _get_db() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.created_at, s.title, s.provider, s.model,
                   COUNT(m.id) as message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_message(
    session_id: str,
    role: str,
    content: str,
    tool_calls: list[dict] | None = None,
) -> str:
    """Add a message to a session. Returns the message ID."""
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    tc_json = json.dumps(tool_calls) if tool_calls else None

    with _get_db() as conn:
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, tool_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, session_id, role, content, tc_json, now),
        )
    return msg_id


def get_messages(session_id: str) -> list[dict]:
    """Get all messages for a session, ordered chronologically."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, role, content, tool_calls, created_at "
            "FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()

    messages = []
    for r in rows:
        msg = dict(r)
        if msg["tool_calls"]:
            msg["tool_calls"] = json.loads(msg["tool_calls"])
        messages.append(msg)
    return messages


def update_session_title(session_id: str, title: str) -> None:
    """Update the title of a session."""
    with _get_db() as conn:
        conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (title, session_id),
        )
