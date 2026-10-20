"""Manual subjective log — the one non-API data source in this project.

Run:
    uv run python -m health_data.journal log --mood 7 --energy 6 --soreness 3 --note "easy run"
    uv run python -m health_data.journal log            # interactive prompts instead
"""
from __future__ import annotations

import argparse
from datetime import date

from health_data import db


def _prompt_int(label: str) -> int:
    while True:
        raw = input(f"{label} (1-10): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= 10:
            return int(raw)
        print("  enter a number 1-10")


def log(day: str, mood: int | None, energy: int | None, soreness: int | None, note: str | None) -> None:
    db.init_db()
    # Either mode, never a mix: any score passed as a flag means this is a
    # non-interactive invocation (a scheduler, a script), so we must not block
    # on input() for the fields that were left off.
    flag_mode = any(v is not None for v in (mood, energy, soreness, note))
    if flag_mode:
        missing = [n for n, v in (("mood", mood), ("energy", energy), ("soreness", soreness)) if v is None]
        if missing:
            raise SystemExit(
                "missing required score(s): "
                + ", ".join("--" + m for m in missing)
                + " -- pass all three, or pass none to be prompted interactively."
            )
    else:
        mood = _prompt_int("mood")
        energy = _prompt_int("energy")
        soreness = _prompt_int("soreness")
        note = input("note (optional): ").strip() or None

    with db.connect() as conn:
        now = db.now_iso()
        conn.execute(
            """INSERT INTO journal_submissions
               (date, mood, energy, soreness, note, submitted_at, source,
                row_hash, imported_at, status)
               VALUES (?, ?, ?, ?, ?, ?, 'cli', ?, ?, 'ok')""",
            (day, mood, energy, soreness, note, now,
             db.journal_row_hash(day, mood, energy, soreness, note, now, "cli"), now),
        )
    print(f"Logged for {day}: mood={mood} energy={energy} soreness={soreness}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("log")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--mood", type=int, default=None)
    p.add_argument("--energy", type=int, default=None)
    p.add_argument("--soreness", type=int, default=None)
    p.add_argument("--note", default=None)
    args = parser.parse_args()
    if args.cmd == "log":
        log(args.date, args.mood, args.energy, args.soreness, args.note)
