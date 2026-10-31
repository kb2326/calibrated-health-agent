"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { type Board, Scoreboard } from "@/components/Scoreboard";

export default function ScoreboardPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/scoreboard")
      .then(async (r) => (r.ok ? setBoard((await r.json()) as Board) : setError("The scoreboard isn't available yet.")))
      .catch(() => setError("Couldn't reach the server. Try again."));
  }, []);
  return (
    <main className="mx-auto grid max-w-[900px] gap-5 px-4 py-6 sm:px-6">
      <header className="flex items-center justify-between gap-3">
        <h1 className="font-display text-[26px] font-extrabold uppercase italic">Forecast scoreboard</h1>
        <Link href="/" className="rounded-tele border border-line px-3 py-1.5 text-[13px]">Back to chat</Link>
      </header>
      <p className="text-[14px] text-muted">Each morning seven forecasters bet on how you will feel that evening. Bets are locked before the day happens and scored against your journal.</p>
      {error ? <p role="status">{error}</p> : board ? <Scoreboard board={board} /> : <p className="text-muted">Loading…</p>}
    </main>
  );
}
