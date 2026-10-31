import type { AgentStep } from "@/lib/types";

const COLOR: Record<AgentStep["status"], string> = { running: "bg-accent", ok: "bg-good", error: "bg-bad" };
const STATUS_TEXT: Record<AgentStep["status"], string> = { running: "in progress", ok: "done", error: "failed" };

// The agent at work: one row per tool call, in order, coloured like timing sectors.
export function AgentTimeline({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) return null;
  return (
    <ol aria-label="Agent at work" className="grid gap-1.5">
      {steps.map((s) => (
        <li key={s.id} className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-2.5 text-[13.5px] text-muted">
          <span aria-hidden className={`h-3.5 w-3.5 -skew-x-12 rounded-[1px] ${COLOR[s.status]}`} />
          <span>
            {s.label}
            <span className="sr-only"> ({STATUS_TEXT[s.status]})</span>
            {s.status === "error" && s.error ? <span className="text-bad">: {s.error}</span> : null}
          </span>
          <span className="font-mono text-[12px] tabular-nums">
            {s.n != null ? `${s.n} row${s.n === 1 ? "" : "s"}` : ""}
            {s.n != null && s.receipt ? " · " : ""}
            {s.receipt ?? ""}
          </span>
        </li>
      ))}
    </ol>
  );
}
