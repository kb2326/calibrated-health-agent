"use client";
import Markdown from "react-markdown";
import type { UiMessage } from "@/lib/types";
import { ReceiptChip } from "./ReceiptChip";

const RECEIPT = /\[?\b(r-[0-9a-f]{10})\b\]?/g;

/** Receipt ids become links the renderer turns into chips. */
export function withReceiptLinks(text: string): string {
  return text.replace(RECEIPT, (_m, id: string) => `[${id}](#receipt-${id})`);
}

// Model text is Markdown with raw HTML shown as text, no images and no outbound links.
export function Answer({ message, onOpenReceipt }: { message: UiMessage; onOpenReceipt: (id: string) => void }) {
  const n = message.unbacked?.length ?? 0;
  return (
    <div className="max-w-[62ch] text-[16px] leading-relaxed [&_p]:mb-3 [&_strong]:font-semibold [&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-5">
      <Markdown
        components={{
          a: ({ href, children }) => {
            const id = href?.startsWith("#receipt-") ? href.slice("#receipt-".length) : null;
            if (id) return <ReceiptChip id={id} onOpen={onOpenReceipt} />;
            return <span>{children}</span>;
          },
          img: () => null,
        }}
      >
        {withReceiptLinks(message.text)}
      </Markdown>
      {message.unbacked ? (
        <p className="mt-1 border-l-2 border-warn pl-2.5 text-[13.5px] text-muted">
          {n === 1 ? "One figure wasn't" : `${n} figures weren't`} computed by a tool:{" "}
          <span className="font-mono text-warn">{message.unbacked.join(", ")}</span>
        </p>
      ) : null}
      {message.incomplete ? (
        <p className="mt-1 font-mono text-[12px] text-bad">incomplete: the answer stopped early</p>
      ) : null}
    </div>
  );
}
