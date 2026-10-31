// Receipt data reaches the page only through these two calls (never through the stream).

export interface Receipt {
  id: string;
  kind: "sql" | "python";
  executor: string;
  as_of: string;
  code: string;
  output: unknown;
  data_hash: string;
  description: string;
  where: string;
}

export type RerunStatus = "matches" | "differs" | "data_changed" | "error";

export type ReceiptResult = { ok: true; receipt: Receipt } | { ok: false; notFound: boolean; message: string };

export async function fetchReceipt(id: string): Promise<ReceiptResult> {
  try {
    const r = await fetch(`/api/receipts/${encodeURIComponent(id)}`);
    if (r.status === 404) return { ok: false, notFound: true, message: "No such receipt" };
    if (!r.ok) return { ok: false, notFound: false, message: "Couldn't load this receipt. Try again." };
    return { ok: true, receipt: (await r.json()) as Receipt };
  } catch {
    return { ok: false, notFound: false, message: "Couldn't reach the server. Try again." };
  }
}

export async function rerunReceipt(id: string): Promise<{ status: RerunStatus; detail: string }> {
  try {
    const r = await fetch(`/api/receipts/${encodeURIComponent(id)}/rerun`, { method: "POST" });
    if (!r.ok) return { status: "error", detail: r.status === 404 ? "No such receipt" : "Re-run failed." };
    return (await r.json()) as { status: RerunStatus; detail: string };
  } catch {
    return { status: "error", detail: "Couldn't reach the server. Try again." };
  }
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const PREFERRED = /asleep|resting|steps|value|avg|mean|total|hrv|duration|minutes$/i;

export interface Series {
  key: string;
  points: { date: string; value: number }[];
}

/** A list of rows with one date column and one numeric column is a chartable series. */
export function asSeries(output: unknown): Series | null {
  if (!Array.isArray(output) || output.length < 2) return null;
  const first: unknown = output[0];
  if (!first || typeof first !== "object") return null;
  const keys = Object.keys(first);
  const dateKey = keys.find((k) => typeof (first as Record<string, unknown>)[k] === "string" &&
                                   DAY.test(String((first as Record<string, unknown>)[k])));
  const numKeys = keys.filter((k) => k !== dateKey && typeof (first as Record<string, unknown>)[k] === "number");
  if (!dateKey || numKeys.length === 0) return null;
  // Several numeric columns: chart the headline measure, else the first column.
  const key = numKeys.find((k) => PREFERRED.test(k)) ?? (numKeys[0] as string);
  const points: Series["points"] = [];
  for (const row of output as Record<string, unknown>[]) {
    const date = row[dateKey], value = row[key];
    if (typeof date !== "string" || !DAY.test(date) || typeof value !== "number" || !Number.isFinite(value)) return null;
    points.push({ date, value });
  }
  points.sort((a, b) => a.date.localeCompare(b.date)); // oldest first, left to right
  return { key, points };
}
