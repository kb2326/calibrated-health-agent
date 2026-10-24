"""The agent's memory, behind ADK's memory interface, in the laptop's `agent.db`.

Two kinds:

- **Facts** the owner confirmed ("started a new training plan on Oct 1"), each with a
  validity window. The agent saves one only through `save_fact`, a tool that needs the
  owner's yes (`require_confirmation`). `close_fact` ends a fact's window; `forget`
  deletes it.
- **Episodes**: journal notes and the investigator's hypotheses, embedded so a search for
  "stressful weeks" finds "work deadline". `refresh_episodes` embeds the new ones.

`search_memory` returns facts valid today plus the closest episodes, with episode text
wrapped as untrusted. Chat sessions are not memorised automatically. Forecaster 7 never
reads this memory (it reads hypotheses from the ledger directly).
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.tools.function_tool import FunctionTool
from google.genai import types
from health_core.settings import get_settings
from health_data import civil, db

from . import agent_db
from .untrusted import wrap

TOP_K = 5


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VertexEmbedder:
    """Gemini embeddings on Vertex (owner credentials, global endpoint)."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        from google import genai

        settings = get_settings()
        client = genai.Client(vertexai=True, project=settings.gcp_project,
                              location=settings.vertex_location)
        result = client.models.embed_content(model=settings.embedding_model, contents=texts)
        return [list(e.values or []) for e in result.embeddings or []]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb) if na and nb else 0.0


def _entry(text: str, kind: str) -> MemoryEntry:
    return MemoryEntry(content=types.Content(role="user", parts=[types.Part(text=text)]),
                       author="memory", custom_metadata={"kind": kind})


def save_fact_now(text: str, valid_from: str | None = None, source: str = "chat") -> str:
    fid = "f-" + uuid.uuid4().hex[:8]
    with agent_db.connect() as conn:
        conn.execute("INSERT INTO facts VALUES (?, ?, ?, NULL, ?, ?)",
                     (fid, text.strip(), valid_from or civil.today().isoformat(), source,
                      db.utc_stamp()))
    return fid


def close_fact(fact_id: str, valid_to: str) -> bool:
    with agent_db.connect() as conn:
        return conn.execute("UPDATE facts SET valid_to = ? WHERE id = ?",
                            (valid_to, fact_id)).rowcount == 1


def forget(item_id: str) -> bool:
    with agent_db.connect() as conn:
        n = conn.execute("DELETE FROM facts WHERE id = ?", (item_id,)).rowcount
        n += conn.execute("DELETE FROM episodes WHERE id = ?", (item_id,)).rowcount
    return n > 0


def save_fact(text: str, valid_from: str | None = None) -> dict:
    """Remember a fact the person told you about themselves, after they confirm.

    Use only for durable context they stated ("I started a new job on Oct 1"), never for
    numbers you computed. The person is asked to approve before anything is saved.

    Args:
        text: The fact, in one sentence.
        valid_from: ISO date it became true; defaults to today.

    Returns:
        dict: `saved` id.
    """
    return {"saved": save_fact_now(text, valid_from)}


save_fact_tool = FunctionTool(save_fact, require_confirmation=True)


class HealthMemoryService(BaseMemoryService):
    def __init__(self, embedder: Embedder | None = None):
        self._embedder = embedder

    def _embedder_or_default(self) -> Embedder:
        if self._embedder is None:
            self._embedder = VertexEmbedder()
        return self._embedder

    async def add_session_to_memory(self, session: Any) -> None:
        return None  # chat sessions are not memorised automatically

    def refresh_episodes(self, health: sqlite3.Connection) -> int:
        """Embed journal notes and hypotheses not yet stored; returns how many were added."""
        candidates: list[tuple[str, str, str | None, str]] = [
            (f"note:{d}", "journal_note", d, n) for d, n in health.execute(
                "SELECT o.date, s.note FROM journal_outcome o JOIN journal_submissions s "
                "ON s.id = o.submission_id WHERE s.note IS NOT NULL AND s.note != ''")]
        try:
            candidates += [(f"hyp:{i}", "hypothesis", d, s) for i, d, s in health.execute(
                "SELECT id, created_day, statement FROM hypotheses")]
        except sqlite3.OperationalError:
            pass  # a database from before schema v4
        with agent_db.connect() as conn:
            have = {r[0] for r in conn.execute("SELECT id FROM episodes")}
            new = [c for c in candidates if c[0] not in have]
            if not new:
                return 0
            vectors = self._embedder_or_default().embed([c[3] for c in new])
            conn.executemany("INSERT INTO episodes VALUES (?, ?, ?, ?, ?, ?)", [
                (eid, kind, day, text, json.dumps(vec), db.utc_stamp())
                for (eid, kind, day, text), vec in zip(new, vectors, strict=True)])
        return len(new)

    async def search_memory(self, *, app_name: str, user_id: str,
                            query: str) -> SearchMemoryResponse:
        today = civil.today().isoformat()
        with agent_db.connect() as conn:
            facts = conn.execute(
                "SELECT text, valid_from FROM facts WHERE valid_from <= ? AND "
                "(valid_to IS NULL OR valid_to > ?) ORDER BY valid_from", (today, today)).fetchall()
            episodes = conn.execute("SELECT kind, day, text, vector FROM episodes").fetchall()
        memories = [_entry(f"Fact (since {since}): {text}", "fact") for text, since in facts]
        if episodes:
            try:
                qvec = self._embedder_or_default().embed([query])[0]
                ranked = sorted(episodes, key=lambda e: -_cosine(qvec, json.loads(e[3] or "[]")))
            except Exception:  # offline: most recent episodes instead
                ranked = sorted(episodes, key=lambda e: e[1] or "", reverse=True)
            for kind, day, text, _ in ranked[:TOP_K]:
                memories.append(_entry(f"{kind} ({day}): {wrap(kind, text)}", kind))
        return SearchMemoryResponse(memories=memories)
