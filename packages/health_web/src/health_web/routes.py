"""Receipts (and re-run), scoreboard and health. The only way receipt data reaches the page."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from health_agents import receipts
from health_data import db

from .describe import describe_receipt

RECEIPT_ID = re.compile(r"\Ar-[0-9a-f]{10}\Z")
NOT_YET_BELOW = 10  # comparisons with fewer paired days say "not yet" (pre-registered rule)
NOT_FOUND = {"error": "No such receipt"}

router = APIRouter(prefix="/api")


def _missing() -> JSONResponse:
    return JSONResponse(NOT_FOUND, status_code=404)


@router.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: str) -> Any:
    found = receipts.get(receipt_id) if RECEIPT_ID.match(receipt_id) else None
    if found is None:
        return _missing()
    r, where = found
    return {"id": r.id, "kind": r.kind, "executor": r.executor, "as_of": r.as_of, "code": r.code,
            "output": r.output, "data_hash": r.data_hash, "where": where,
            "description": describe_receipt(r.kind, r.code)}


@router.post("/receipts/{receipt_id}/rerun")
def rerun_receipt(receipt_id: str) -> Any:
    if not RECEIPT_ID.match(receipt_id) or receipts.get(receipt_id) is None:
        return _missing()
    out = receipts.rerun(receipt_id)
    if "error" in out:
        return {"status": "error", "detail": str(out["error"])[:300]}
    if out.get("matches"):
        return {"status": "matches", "detail": "Re-ran the same code and got the same result."}
    if out.get("data_changed"):
        return {"status": "data_changed",
                "detail": "The data this read has changed since (a later sync), so a different "
                          "result is expected."}
    return {"status": "differs", "detail": "Re-ran the same code on the same data and got a "
                                           "different result."}


def _mark(row: dict) -> dict:
    return {**row, "not_yet": int(row.get("n") or 0) < NOT_YET_BELOW}


@router.get("/scoreboard")
def scoreboard() -> Any:
    from health_ledger import publish
    from health_ledger import scoreboard as board_mod

    if not db.DB_PATH.exists():
        return JSONResponse({"error": "No database yet"}, status_code=503)
    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    try:
        board = publish.public_board(board_mod.build(conn))
    except sqlite3.OperationalError:
        return JSONResponse({"error": "No forecast ledger in this database"}, status_code=503)
    finally:
        conn.close()
    board["primary"] = _mark(board["primary"])
    board["secondary"] = [_mark(x) for x in board.get("secondary", [])]
    board["forecasters"] = [_mark(x) for x in board.get("forecasters", [])]
    return board


@router.get("/health")
def health(request: Request) -> Any:
    mode = request.app.state.mode
    return {"ok": True, "mode": mode, "demo": mode == "demo"}
