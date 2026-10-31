import { describe, expect, it } from "vitest";
import { addUserMessage, initialState, reduce, splitNote } from "@/lib/run";
import type { AgUiEvent, RunState } from "@/lib/types";

function play(events: AgUiEvent[], start: RunState = initialState): RunState {
  return events.reduce(reduce, addUserMessage(start, "u1", "How did I sleep?"));
}

const answer = (id: string, ...deltas: string[]): AgUiEvent[] => [
  { type: "TEXT_MESSAGE_START", messageId: id, role: "assistant" },
  ...deltas.map((delta) => ({ type: "TEXT_MESSAGE_CONTENT", messageId: id, delta })),
  { type: "TEXT_MESSAGE_END", messageId: id },
];

describe("run reducer", () => {
  it("builds a message with receipts from text deltas", () => {
    const s = play([{ type: "RUN_STARTED" }, ...answer("a1", "You slept 6.8 h ", "[r-0123456789]."),
                    { type: "RUN_FINISHED" }]);
    const last = s.messages.at(-1)!;
    expect(last.role).toBe("assistant");
    expect(last.text).toBe("You slept 6.8 h [r-0123456789].");
    expect(last.receipts).toEqual(["r-0123456789"]);
    expect(s.status).toBe("done");
  });

  it("splits the quiet note into unbacked figures", () => {
    const s = play(answer("a1", "Average 61 bpm.\n\n_Note: 1 figure wasn't computed by a tool: 61._"));
    expect(s.messages.at(-1)!.text).toBe("Average 61 bpm.");
    expect(s.messages.at(-1)!.unbacked).toEqual(["61"]);
  });

  it("still splits the legacy unverified footer", () => {
    expect(splitNote("x 5\n\nunverified: 5, 6")).toEqual({ body: "x 5", unbacked: ["5", "6"] });
  });

  it("tool events become timeline steps", () => {
    const s = play([
      { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "data_catalog" },
      { type: "TOOL_CALL_RESULT", toolCallId: "c1", content: JSON.stringify(
        { tool: "data_catalog", receipt: null, status: "ok", n: null, error: null }) },
      { type: "TOOL_CALL_START", toolCallId: "c2", toolCallName: "run_sql" },
      { type: "TOOL_CALL_RESULT", toolCallId: "c2", content: JSON.stringify(
        { tool: "run_sql", receipt: "r-aaaaaaaaaa", status: "ok", n: 7, error: null }) },
    ]);
    expect(s.steps.map((x) => [x.label, x.status, x.receipt ?? null, x.n ?? null])).toEqual([
      ["Checking what data exists", "ok", null, null],
      ["Running a query", "ok", "r-aaaaaaaaaa", 7],
    ]);
  });

  it("a tool error shows on its step", () => {
    const s = play([
      { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "query_metric" },
      { type: "TOOL_CALL_RESULT", toolCallId: "c1", content: JSON.stringify(
        { tool: "query_metric", receipt: null, status: "error", n: null, error: "bad date" }) },
    ]);
    expect(s.steps[0]).toMatchObject({ status: "error", error: "bad date" });
  });

  it("confirmation tool call sets awaiting_approval", () => {
    const s = play([
      { type: "TOOL_CALL_START", toolCallId: "k1", toolCallName: "adk_request_confirmation" },
      { type: "TOOL_CALL_ARGS", toolCallId: "k1", delta: '{"text":"I train on Tuesdays"}' },
      { type: "RUN_FINISHED" },
    ]);
    expect(s.status).toBe("awaiting_approval");
    expect(s.pending).toMatchObject({ toolCallId: "k1" });
    expect(s.pending!.detail).toContain("Tuesdays");
  });

  it("RUN_ERROR keeps partial text and marks it incomplete", () => {
    const s = play([
      { type: "TEXT_MESSAGE_START", messageId: "a1", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "a1", delta: "Over the last week you" },
      { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "run_sql" },
      { type: "RUN_ERROR", message: "Monthly chat budget ($0.30) reached; it resets on the 1st.",
        code: "BUDGET" },
    ]);
    expect(s.status).toBe("error");
    expect(s.error).toEqual({ message: "Monthly chat budget ($0.30) reached; it resets on the 1st.",
                              code: "BUDGET" });
    expect(s.messages.at(-1)).toMatchObject({ text: "Over the last week you", incomplete: true });
    expect(s.steps[0]!.status).toBe("error");
  });

  it("a new question clears the previous steps and error", () => {
    const failed = play([{ type: "RUN_ERROR", message: "x" }]);
    const next = addUserMessage(failed, "u2", "again");
    expect(next.status).toBe("running");
    expect(next.error).toBeUndefined();
    expect(next.steps).toEqual([]);
  });
});
