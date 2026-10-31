"use client";
import type { PendingApproval } from "@/lib/types";

/** Nothing is saved unless the person taps Save. */
export function ApproveCard({ pending, onApprove, onDeny, expired = false }: {
  pending: PendingApproval; onApprove: () => void; onDeny: () => void; expired?: boolean;
}) {
  let fact = "";
  try {
    const args: unknown = JSON.parse(pending.detail || "{}");
    const orig = (args as { originalFunctionCall?: { args?: { text?: string } } }).originalFunctionCall;
    fact = orig?.args?.text ?? (args as { text?: string }).text ?? "";
  } catch {
    fact = "";
  }
  if (expired) {
    return (
      <div role="status" className="rounded-tele bg-soft p-4 text-[14px]">
        This conversation expired. Ask again.
      </div>
    );
  }
  return (
    <div role="group" aria-label="Save a memory?" className="grid gap-3 rounded-tele border-l-[3px] border-accent bg-card p-4">
      <p className="font-display text-[18px] font-bold uppercase italic">Save a memory?</p>
      <p className="text-[14px]">The agent wants to remember:</p>
      <blockquote className="bg-code p-2.5 font-mono text-[13px]">{fact || "(no text)"}</blockquote>
      <div className="flex gap-2.5">
        <button type="button" onClick={onApprove}
          className="rounded-tele bg-accent px-4 py-2 font-semibold text-on-accent">Save</button>
        <button type="button" onClick={onDeny}
          className="rounded-tele border border-line px-4 py-2">Don&apos;t save</button>
      </div>
    </div>
  );
}
