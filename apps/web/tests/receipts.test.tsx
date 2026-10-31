import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApproveCard } from "@/components/ApproveCard";
import { MetricCard, SeriesChart } from "@/components/MetricCard";
import { ReceiptPanel } from "@/components/ReceiptPanel";
import { asSeries } from "@/lib/receipts";

const RECEIPT = {
  id: "r-4f2a9c1e07", kind: "sql", executor: "sqlite-ro/1", as_of: "2026-10-30",
  code: "SELECT date, minutes_asleep FROM sleep_sessions", data_hash: "4f2a9c1e07b3d5aa99",
  description: "SQL over your sleep sessions", where: "chat",
  output: [{ date: "2026-10-28", minutes_asleep: 458 }, { date: "2026-10-29", minutes_asleep: 412 },
           { date: "2026-10-30", minutes_asleep: 404 }],
};

function mockFetch(routes: Record<string, { status?: number; body: unknown }>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const hit = routes[key];
    if (!hit) return new Response(JSON.stringify({ error: "No such receipt" }), { status: 404 });
    return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("receipt panel", () => {
  it("shows the description first, then code, output, as-of and data hash", async () => {
    mockFetch({ "GET /api/receipts/r-4f2a9c1e07": { body: RECEIPT } });
    render(<ReceiptPanel id="r-4f2a9c1e07" onClose={() => {}} onApprove={() => {}} onDeny={() => {}} />);
    expect(await screen.findByText("SQL over your sleep sessions")).toBeInTheDocument();
    expect(screen.getByText(/SELECT date, minutes_asleep/)).toBeInTheDocument();
    expect(screen.getByText("2026-10-30")).toBeInTheDocument();
    expect(screen.getByText(/4f2a9c1e07b3d5aa/)).toBeInTheDocument();
    expect(screen.getByText(/458/)).toBeInTheDocument();
  });

  it("shows a not-found state for an unknown receipt", async () => {
    mockFetch({});
    render(<ReceiptPanel id="r-0000000000" onClose={() => {}} onApprove={() => {}} onDeny={() => {}} />);
    expect(await screen.findByText("No such receipt")).toBeInTheDocument();
  });

  it.each([["matches", "Matches"], ["differs", "Differs"], ["data_changed", "Data changed"]])(
    "re-run shows %s", async (status, text) => {
      mockFetch({ "GET /api/receipts/r-4f2a9c1e07": { body: RECEIPT },
                  "POST /api/receipts/r-4f2a9c1e07/rerun": { body: { status, detail: "why" } } });
      render(<ReceiptPanel id="r-4f2a9c1e07" onClose={() => {}} onApprove={() => {}} onDeny={() => {}} />);
      fireEvent.click(await screen.findByRole("button", { name: "Re-run" }));
      expect(await screen.findByText(text)).toBeInTheDocument();
    });

  it("Escape closes the panel", async () => {
    mockFetch({ "GET /api/receipts/r-4f2a9c1e07": { body: RECEIPT } });
    const onClose = vi.fn();
    render(<ReceiptPanel id="r-4f2a9c1e07" onClose={onClose} onApprove={() => {}} onDeny={() => {}} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});

describe("metric card", () => {
  it("recognises a date series and skips anything else", () => {
    expect(asSeries(RECEIPT.output)?.key).toBe("minutes_asleep");
    expect(asSeries([{ m: 61.2, n: 7 }])).toBeNull();
    expect(asSeries([{ date: "2026-10-01", a: "x" }, { date: "2026-10-02", a: "y" }])).toBeNull(); // no numeric column
    expect(asSeries("text")).toBeNull();
  });

  it("charts the series to scale with the best value highlighted", () => {
    const { container } = render(<SeriesChart series={asSeries(RECEIPT.output)!} />);
    const bars = [...container.querySelectorAll("rect")];
    expect(bars).toHaveLength(3);
    const heights = bars.map((b) => Number(b.getAttribute("height")));
    // heights are proportional to the values on one shared scale starting at 0
    expect(heights[0]! / heights[2]!).toBeCloseTo(458 / 404, 2);
    expect(bars[0]!.getAttribute("fill")).toBe("var(--c-best)");
  });

  it("charts the first cited receipt that is a series, skipping the rest", async () => {
    mockFetch({ "GET /api/receipts/r-4f2a9c1e07": { body: RECEIPT },
                "GET /api/receipts/r-1111111111": { body: { ...RECEIPT, id: "r-1111111111", output: [{ m: 1 }] } } });
    const { rerender } = render(<MetricCard ids={["r-1111111111", "r-4f2a9c1e07"]} onOpenReceipt={() => {}} />);
    expect(await screen.findByTestId("metric-card")).toHaveTextContent("424.7");
    rerender(<MetricCard ids={["r-1111111111"]} onOpenReceipt={() => {}} />);
    await waitFor(() => expect(screen.queryByTestId("metric-card")).toBeNull());
  });
});

describe("approve card", () => {
  const pending = { toolCallId: "k1", action: "save a memory",
                    detail: JSON.stringify({ originalFunctionCall: { args: { text: "I train on Tuesdays" } } }) };

  it("approve and deny call the hook", () => {
    const onApprove = vi.fn(), onDeny = vi.fn();
    render(<ApproveCard pending={pending} onApprove={onApprove} onDeny={onDeny} />);
    expect(screen.getByText("I train on Tuesdays")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    fireEvent.click(screen.getByRole("button", { name: "Don't save" }));
    expect(onApprove).toHaveBeenCalledOnce();
    expect(onDeny).toHaveBeenCalledOnce();
  });

  it("shows the expired state", () => {
    render(<ApproveCard pending={pending} onApprove={() => {}} onDeny={() => {}} expired />);
    expect(screen.getByText("This conversation expired. Ask again.")).toBeInTheDocument();
  });
});

describe("chart scale", () => {
  it("orders days oldest first and keeps every bar inside the axis", () => {
    const s = asSeries([{ date: "2026-10-30", v: 66 }, { date: "2026-10-29", v: 61 }, { date: "2026-10-28", v: 63 }])!;
    expect(s.points.map((p) => p.date)).toEqual(["2026-10-28", "2026-10-29", "2026-10-30"]);
    const { container } = render(<SeriesChart series={s} />);
    const ys = [...container.querySelectorAll("rect")].map((r) => Number(r.getAttribute("y")));
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(12); // the top padding: nothing above the highest tick
    const labels = [...container.querySelectorAll("text")].map((t) => Number(t.textContent)).filter(Number.isFinite);
    expect(Math.max(...labels)).toBeGreaterThanOrEqual(66);
  });
});

describe("panel visibility", () => {
  it("opens for a pending approval even with no receipt (phones hide it otherwise)", () => {
    const pending = { toolCallId: "k1", action: "save a memory", detail: "{}" };
    render(<ReceiptPanel id={null} onClose={() => {}} pending={pending} onApprove={() => {}} onDeny={() => {}} />);
    const panel = screen.getByRole("complementary", { name: "Receipt" });
    expect(panel.className).not.toMatch(/(^|\s)hidden(\s|$)/);
    expect(screen.getByRole("group", { name: "Save a memory?" })).toBeInTheDocument();
  });
});

describe("series with several numeric columns", () => {
  it("charts the most meaningful column (minutes asleep over deep, light, efficiency)", () => {
    const rows = [
      { date: "2026-10-24", deep_min: 80, efficiency: 0.87, light_min: 279, minutes_asleep: 440, rem_min: 81 },
      { date: "2026-10-25", deep_min: 70, efficiency: 0.91, light_min: 250, minutes_asleep: 410, rem_min: 90 },
    ];
    expect(asSeries(rows)?.key).toBe("minutes_asleep");
    expect(asSeries([{ date: "2026-10-24", a: 1, b: 2 }, { date: "2026-10-25", a: 3, b: 4 }])?.key).toBe("a");
  });
});
