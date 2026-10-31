"use client";
// A receipt id as a button: tapping it opens the code and data behind the number.
export function ReceiptChip({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <button type="button" onClick={() => onOpen(id)} aria-label={`Open receipt ${id}`}
      className="mx-0.5 rounded-tele bg-chip px-1.5 py-0.5 align-[1px] font-mono text-[12px] leading-none text-chip-fg hover:brightness-125">
      {id}
    </button>
  );
}
