// Pure state for one conversation: AG-UI events in, UI state out. No network here.
import type { AgentStep, AgUiEvent, RunState, ToolSummary, UiMessage } from "./types";

export const CONFIRM_TOOL = "adk_request_confirmation";
const RECEIPT = /\br-[0-9a-f]{10}\b/g;
const NOTE = /\n*_Note: \d+ figures? (?:wasn't|weren't) computed by a tool: (.+?)\._\s*$/;
const FOOTER = /\n\nunverified: (.+?)\s*$/;

export const TOOL_LABELS: Record<string, string> = {
  data_catalog: "Checking what data exists",
  query_metric: "Reading a metric",
  run_sql: "Running a query",
  run_python: "Computing in the sandbox",
  weather: "Checking the weather",
  get_journal: "Reading your journal",
  get_anomalies: "Looking for unusual days",
  get_correlations: "Looking for relationships",
  get_scoreboard: "Reading the forecast scoreboard",
  sources_for_metric: "Checking which device measured it",
  list_devices: "Listing your devices",
  get_health_profile: "Reading your profile",
  save_fact: "Asking to remember something",
  load_memory: "Searching memory",
  coach: "Asking the coach",
  domain_expert: "Asking the domain expert",
};

export function labelFor(tool: string): string {
  return TOOL_LABELS[tool] ?? `Using ${tool.replaceAll("_", " ")}`;
}

/** Split the agent's quiet note (or the legacy footer) off the answer. */
export function splitNote(text: string): { body: string; unbacked: string[] | null } {
  const m = NOTE.exec(text) ?? FOOTER.exec(text);
  if (!m || m[1] === undefined) return { body: text, unbacked: null };
  const unbacked = m[1].split(",").map((s) => s.trim()).filter(Boolean);
  return { body: text.slice(0, m.index).trimEnd(), unbacked };
}

export function receiptIds(text: string): string[] {
  return [...new Set(text.match(RECEIPT) ?? [])];
}

export const initialState: RunState = { messages: [], steps: [], status: "idle" };

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function parseSummary(content: unknown): ToolSummary | null {
  try {
    const body: unknown = JSON.parse(str(content));
    if (body && typeof body === "object" && "status" in body) return body as ToolSummary;
  } catch {
    /* not a summary */
  }
  return null;
}

function finish(msg: UiMessage): UiMessage {
  const { body, unbacked } = splitNote(msg.text);
  return { ...msg, text: body, unbacked, receipts: receiptIds(msg.text) };
}

function updateLast(messages: UiMessage[], f: (m: UiMessage) => UiMessage): UiMessage[] {
  const i = messages.findLastIndex((m) => m.role === "assistant");
  if (i < 0) return messages;
  const copy = messages.slice();
  copy[i] = f(copy[i] as UiMessage);
  return copy;
}

export function addUserMessage(state: RunState, id: string, text: string): RunState {
  const msg: UiMessage = { id, role: "user", text, receipts: [], unbacked: null, incomplete: false };
  return { ...state, messages: [...state.messages, msg], steps: [], status: "running",
           error: undefined, pending: undefined };
}

export function reduce(state: RunState, event: AgUiEvent): RunState {
  switch (event.type) {
    case "RUN_STARTED":
      return { ...state, status: "running", error: undefined };
    case "TEXT_MESSAGE_START": {
      const id = str(event.messageId);
      if (state.messages.some((m) => m.id === id)) return state;
      const msg: UiMessage = { id, role: "assistant", text: "", receipts: [], unbacked: null,
                               incomplete: false };
      return { ...state, messages: [...state.messages, msg] };
    }
    case "TEXT_MESSAGE_CONTENT": {
      const id = str(event.messageId);
      const delta = str(event.delta);
      return { ...state, messages: state.messages.map((m) =>
        m.id === id ? { ...m, text: m.text + delta, receipts: receiptIds(m.text + delta) } : m) };
    }
    case "TEXT_MESSAGE_END": {
      const id = str(event.messageId);
      return { ...state, messages: state.messages.map((m) => (m.id === id ? finish(m) : m)) };
    }
    case "TOOL_CALL_START": {
      const tool = str(event.toolCallName);
      const id = str(event.toolCallId);
      if (tool === CONFIRM_TOOL) {
        return { ...state, pending: { toolCallId: id, action: "save a memory", detail: "" } };
      }
      const step: AgentStep = { id, tool, label: labelFor(tool), status: "running" };
      return { ...state, steps: [...state.steps, step] };
    }
    case "TOOL_CALL_ARGS": {
      const id = str(event.toolCallId);
      if (state.pending?.toolCallId !== id) return state;
      return { ...state, pending: { ...state.pending, detail: state.pending.detail + str(event.delta) } };
    }
    case "TOOL_CALL_RESULT": {
      const id = str(event.toolCallId);
      const s = parseSummary(event.content);
      return { ...state, steps: state.steps.map((step) => step.id !== id ? step : {
        ...step,
        status: s?.status === "error" ? "error" : "ok",
        receipt: s?.receipt ?? undefined,
        n: s?.n ?? undefined,
        error: s?.error ?? undefined,
      }) };
    }
    case "RUN_ERROR": {
      const message = str(event.message) || "Something went wrong. Try asking again.";
      const code = str(event.code) || undefined;
      return { ...state, status: "error", error: { message, code },
               messages: updateLast(state.messages, (m) =>
                 m.text ? { ...finish(m), incomplete: true } : m),
               steps: state.steps.map((s) => (s.status === "running" ? { ...s, status: "error" } : s)) };
    }
    case "STATE_DELTA": {
      const ops = Array.isArray(event.delta) ? (event.delta as { path?: unknown; value?: unknown }[]) : [];
      const op = ops.find((o) => o.path === "/verify_attempts" && typeof o.value === "number");
      if (!op) return state;
      const n = op.value as number;
      if (n <= (state.verifyAttempts ?? 0)) return { ...state, verifyAttempts: n };
      // The number check sent the draft back: it held a figure no tool computed. Drop it;
      // the revised answer streams next.
      const lastUser = state.messages.findLastIndex((m) => m.role === "user");
      const i = state.messages.findLastIndex((m) => m.role === "assistant");
      const messages = i > lastUser ? state.messages.filter((_, j) => j !== i) : state.messages;
      const step: AgentStep = { id: `verify-${n}`, tool: "verify", status: "ok",
                                label: "Rechecking a number that wasn't computed by a tool" };
      return { ...state, messages, verifyAttempts: n, steps: [...state.steps, step] };
    }
    case "RUN_FINISHED":
      return { ...state, status: state.pending ? "awaiting_approval" : "done" };
    default:
      return state;
  }
}
