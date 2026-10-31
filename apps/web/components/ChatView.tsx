"use client";
import { type FormEvent, useState } from "react";
import type { RunState } from "@/lib/types";
import { AgentTimeline } from "./AgentTimeline";
import { Answer } from "./Answer";
import { DemoBadge } from "./DemoBadge";
import { ErrorBanner } from "./ErrorBanner";
import { MetricCard } from "./MetricCard";

// Exactly health_agents.cli.DISCLOSURE: the same words as `cha ask`.
export const DISCLOSURE = "AI agent (Gemini) answering from your own data. It can be wrong and is not " +
  "medical advice; every number has a receipt you can re-run.";

export const EXAMPLES = ["How did I sleep this week?", "How was my tennis this month?",
                         "Do I sleep worse on hot nights?", "What's the weather tomorrow?"];

export interface ChatViewProps {
  state: RunState;
  demo: boolean;
  onAsk: (text: string) => void;
  onOpenReceipt: (id: string) => void;
  locationOn: boolean;
  onToggleLocation: () => void;
  locationNote?: string;
}

export function ChatView({ state, demo, onAsk, onOpenReceipt, locationOn, onToggleLocation, locationNote }: ChatViewProps) {
  const [text, setText] = useState("");
  const busy = state.status === "running";
  const lastUser = state.messages.findLastIndex((m) => m.role === "user");

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    setText("");
    onAsk(q);
  }

  return (
    <section className="flex min-h-0 min-w-0 flex-col gap-4 px-4 py-5 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <h1 className="font-display text-[22px] font-extrabold uppercase italic tracking-[.01em]">Calibrated</h1>
          {demo ? <DemoBadge /> : null}
        </div>
        <button type="button" onClick={onToggleLocation} aria-pressed={locationOn}
          className="rounded-tele border border-line px-2.5 py-1.5 text-[12.5px] text-muted hover:text-fg">
          {locationOn ? "Weather: your location" : "Use my location for weather"}
        </button>
      </header>
      {locationNote ? <p className="text-[12.5px] text-muted">{locationNote}</p> : null}
      <p className="text-[12.5px] text-muted">{DISCLOSURE}</p>

      {state.messages.length === 0 ? (
        <div className="grid gap-2">
          <p className="font-display text-[26px] font-bold uppercase italic leading-tight">Ask your own data</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((q) => (
              <button key={q} type="button" onClick={() => onAsk(q)}
                className="rounded-tele bg-soft px-3 py-2 text-[14px] hover:brightness-125">{q}</button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-4">
        {state.messages.map((m, i) => (
          <div key={m.id} className="flex flex-col gap-3">
            {m.role === "user" ? (
              <p className="max-w-[70%] self-end rounded-tele border-l-[3px] border-accent bg-soft px-3.5 py-2.5">{m.text}</p>
            ) : (
              <>
                <Answer message={m} onOpenReceipt={onOpenReceipt} />
                {m.receipts[0] && !m.incomplete ? <MetricCard id={m.receipts[0]} onOpenReceipt={onOpenReceipt} /> : null}
              </>
            )}
            {i === lastUser ? <AgentTimeline steps={state.steps} /> : null}
          </div>
        ))}
        <div aria-live="polite" className="sr-only" data-testid="live">
          {busy ? "The agent is working" : state.status === "done" ? "Answer ready" : ""}
        </div>
        {state.error ? <ErrorBanner error={state.error} /> : null}
      </div>

      <form onSubmit={submit} className="mt-auto flex gap-2.5 pt-2">
        <label htmlFor="question" className="sr-only">Your question</label>
        <input id="question" value={text} onChange={(e) => setText(e.target.value)} maxLength={2000}
          placeholder="Ask about your sleep, workouts, heart or weather" autoComplete="off"
          className="min-w-0 flex-1 rounded-tele bg-soft px-3.5 py-3 text-[15px] placeholder:text-muted" />
        <button type="submit" disabled={busy || !text.trim()}
          className="rounded-tele bg-accent px-4 py-3 font-semibold text-on-accent disabled:opacity-50">
          {busy ? "Working" : "Ask"}
        </button>
      </form>
    </section>
  );
}
