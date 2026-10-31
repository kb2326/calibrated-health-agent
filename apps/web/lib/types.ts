// The AG-UI events this page consumes, after the server's stream filter (no raw rows).

export type RunStatus = "idle" | "running" | "awaiting_approval" | "error" | "done";

export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  receipts: string[];
  /** Figures the agent could not back with a tool result (its quiet note), or null. */
  unbacked: string[] | null;
  incomplete: boolean;
}

export interface AgentStep {
  id: string;
  tool: string;
  label: string;
  status: "running" | "ok" | "error";
  receipt?: string;
  n?: number;
  error?: string;
}

export interface UiError {
  message: string;
  code?: string;
}

export interface PendingApproval {
  toolCallId: string;
  action: string;
  detail: string;
}

export interface RunState {
  messages: UiMessage[];
  steps: AgentStep[];
  status: RunStatus;
  error?: UiError;
  pending?: PendingApproval;
  /** The grounding check's revision count for this turn (from STATE_DELTA). */
  verifyAttempts?: number;
}

/** The filtered TOOL_CALL_RESULT content the server sends. */
export interface ToolSummary {
  tool: string | null;
  receipt: string | null;
  status: "ok" | "error";
  n: number | null;
  error: string | null;
}

export type AgUiEvent = { type: string } & Record<string, unknown>;
