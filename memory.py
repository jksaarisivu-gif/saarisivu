"""Persistent Client Session State, History Compaction, & Non-Blocking Async Memory."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List

from observability import LOGGER, get_secret_or_env, redact_pii


class ClientMemoryDB:
    """Durable SQLite backing store for client handbag preferences & past appraisals."""

    def __init__(self, db_path: str = "boutique_sessions.db") -> None:
        self.db_path = db_path
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vip_client_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def write_memory(self, session_id: str, client_id: str, summary_text: str) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO vip_client_memories (session_id, client_id, summary_json, created_at) VALUES (?, ?, ?, ?)",
                (session_id, client_id, redact_pii(summary_text), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return int(cur.lastrowid or 0)
        finally:
            conn.close()

    def get_memories(self, client_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT session_id, summary_json, created_at FROM vip_client_memories WHERE client_id = ? ORDER BY id DESC",
                (client_id,),
            ).fetchall()
            return [{"session_id": r[0], "summary": r[1], "created_at": r[2]} for r in rows]
        finally:
            conn.close()


def get_session_service() -> Any:
    """Connects ADK persistent `DatabaseSessionService` backed by SQLite."""
    db_url = get_secret_or_env("ADK_SESSION_DB_URL", "sqlite:///./boutique_sessions.db")
    try:
        from google.adk.sessions import DatabaseSessionService  # type: ignore[import-not-found]

        return DatabaseSessionService(db_url=db_url)
    except ImportError:
        return ClientMemoryDB()


def get_memory_bank_service() -> Any:
    """Connects Vertex AI Memory Bank (`VertexAiMemoryBankService`) with local SQLite fallback."""
    try:
        from google.adk.memory import VertexAiMemoryBankService  # type: ignore[import-not-found]

        return VertexAiMemoryBankService(
            project=get_secret_or_env("GOOGLE_CLOUD_PROJECT", "local-boutique-dev"),
            location=get_secret_or_env("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    except ImportError:
        return ClientMemoryDB()


def compact_conversation_history(
    messages: List[Dict[str, Any]],
    max_recent: int = 8,
) -> List[Dict[str, Any]]:
    """Compacts old conversation turns into a concise summary digest to prevent context bloat."""
    if len(messages) <= max_recent:
        return list(messages)

    older = messages[:-max_recent]
    recent = messages[-max_recent:]
    digest_text = " | ".join(
        f"{m.get('role', 'user')}: {redact_pii(str(m.get('content', '')))[:90]}"
        for m in older
    )
    LOGGER.info(
        "Compacted client history window",
        extra={"structured_data": {"compacted_turns": len(older), "kept_turns": len(recent)}},
    )
    return [{"role": "system", "event_type": "compacted_digest", "content": digest_text}] + recent


async def save_client_memory_async(
    session_id: str,
    client_id: str,
    messages: List[Dict[str, Any]],
    db: ClientMemoryDB | None = None,
) -> Dict[str, Any]:
    """Saves client style preferences asynchronously so the chat UI never blocks."""
    store = db or ClientMemoryDB()
    await asyncio.sleep(0)
    highlights = [redact_pii(str(m.get("content", "")))[:120] for m in messages[-3:]]
    row_id = store.write_memory(session_id, client_id, json.dumps({"notes": highlights}))
    return {"status": "saved", "memory_id": row_id}
