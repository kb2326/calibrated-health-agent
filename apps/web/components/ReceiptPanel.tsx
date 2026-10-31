"use client";
import { useEffect, useRef, useState } from "react";
import { fetchReceipt, type Receipt, rerunReceipt, type RerunStatus } from "@/lib/receipts";
import type { PendingApproval } from "@/lib/types";
import { ApproveCard } from "./ApproveCard";

const RERUN_TEXT: Record<RerunStatus, string> = {
  matches: "Matches", differs: "Differs", data_changed: "Data changed", error: "Re-run failed",
};
const RERUN_COLOR: Record<RerunStatus, string> = {
  matches: "text-good", differs: "text-bad", data_changed: "text-warn", error: "text-bad",
};

type Load = { state: "loading" } | { state: "ok"; receipt: Receipt } | { state: "missing"; message: string };

function Output({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 1) ?? "";
  return <pre tabIndex={0} aria-label="Output" className="max-h-56 overflow-auto bg-code p-3 font-mono text-[12px] leading-relaxed">{text.length > 4000 ? text.slice(0, 4000) + "\n…" : text}</pre>;
}

export function ReceiptView({ id }: { id: string }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [rerun, setRerun] = useState<{ status: RerunStatus; detail: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;  // a new id remounts this view (key), so state starts fresh
    fetchReceipt(id).then((r) => {
      if (!live) return;
      setLoad(r.ok ? { state: "ok", receipt: r.receipt } : { state: "missing", message: r.message });
    });
    return () => { live = false; };
  }, [id]);

  if (load.state === "loading") return <p className="text-muted">Loading receipt {id}…</p>;
  if (load.state === "missing") return <p role="status">{load.message}</p>;
  const r = load.receipt;
  return (
    <div className="grid gap-3">
      <p className="text-[15px]">{r.description}</p>
      <dl className="grid grid-cols-[88px_1fr] gap-x-2.5 gap-y-1.5 text-[13px]">
        <dt className="text-muted">Kind</dt><dd className="font-mono text-[12.5px]">{r.kind} · {r.executor}</dd>
        <dt className="text-muted">As of</dt><dd className="font-mono text-[12.5px]">{r.as_of}</dd>
        <dt className="text-muted">Data hash</dt><dd className="break-all font-mono text-[12.5px]">{r.data_hash.slice(0, 16)}…</dd>
      </dl>
      <pre className="whitespace-pre-wrap bg-code p-3 font-mono text-[12px] leading-relaxed">{r.code}</pre>
      <Output value={r.output} />
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={busy}
          onClick={async () => { setBusy(true); setRerun(await rerunReceipt(r.id)); setBusy(false); }}
          className="rounded-tele bg-accent px-3.5 py-2 font-semibold text-on-accent disabled:opacity-50">
          {busy ? "Re-running" : "Re-run"}
        </button>
        {rerun ? <span role="status" className={`font-semibold ${RERUN_COLOR[rerun.status]}`}>{RERUN_TEXT[rerun.status]}</span> : null}
      </div>
      {rerun ? <p className="text-[13px] text-muted">{rerun.detail}</p> : null}
    </div>
  );
}

/**
 * The right column on wide screens; a bottom sheet on phones. Escape closes it, and focus
 * moves to its heading when a receipt opens.
 */
export function ReceiptPanel({ id, onClose, pending, onApprove, onDeny }: {
  id: string | null; onClose: () => void; pending?: PendingApproval; onApprove: () => void; onDeny: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (id) heading.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && id) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, onClose]);

  const open = Boolean(id) || Boolean(pending); // on phones the sheet also opens for an approval
  return (
    <aside aria-label="Receipt"
      className={`flex min-w-0 flex-col gap-3 border-line bg-panel p-5 md:static md:border-l ${
        open ? "fixed inset-x-0 bottom-0 z-20 max-h-[80dvh] overflow-y-auto border-t pb-[max(20px,env(safe-area-inset-bottom))]" : "hidden md:flex"}`}>
      {pending ? <ApproveCard pending={pending} onApprove={onApprove} onDeny={onDeny} /> : null}
      {id ? (
        <>
          <div className="flex items-center justify-between gap-3">
            <h2 ref={heading} tabIndex={-1} className="font-display text-[22px] font-bold uppercase italic">Receipt {id}</h2>
            <button type="button" onClick={onClose} className="rounded-tele border border-line px-2.5 py-1 text-[13px]">Close</button>
          </div>
          <ReceiptView key={id} id={id} />
        </>
      ) : !pending ? (
        <p className="text-[14px] text-muted">Tap a receipt next to any number to see the code that computed it, and re-run it.</p>
      ) : null}
    </aside>
  );
}
