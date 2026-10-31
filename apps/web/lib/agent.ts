"use client";
// useAgentRun(): the page's one connection to the agent, over AG-UI at /api/agent.
import { HttpAgent } from "@ag-ui/client";
import { useCallback, useMemo, useReducer, useRef } from "react";
import { addUserMessage, CONFIRM_TOOL, initialState, reduce } from "./run";
import type { AgUiEvent, RunState } from "./types";

export interface DeviceLocation {
  latitude: number;
  longitude: number;
  place?: string;
}

type Action = { kind: "event"; event: AgUiEvent } | { kind: "ask"; id: string; text: string }
  | { kind: "resume" };

function reducer(state: RunState, action: Action): RunState {
  if (action.kind === "ask") return addUserMessage(state, action.id, action.text);
  if (action.kind === "resume") return { ...state, status: "running", pending: undefined };
  return reduce(state, action.event);
}

function newId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const NETWORK_ERROR = "Couldn't reach the agent. Check that cha-web is running and try again.";

export function useAgentRun(url = "/api/agent") {
  const [state, dispatch] = useReducer(reducer, initialState);
  const agent = useMemo(() => new HttpAgent({ url, threadId: newId() }), [url]);
  const location = useRef<DeviceLocation | null>(null);

  const run = useCallback(async () => {
    // Only the device location travels as state; the server drops anything else.
    agent.setState(location.current ? { location: location.current } : {});
    try {
      await agent.runAgent({ runId: newId() }, {
        onEvent: ({ event }) => { dispatch({ kind: "event", event: event as unknown as AgUiEvent }); },
      });
    } catch (err) {
      const message = err instanceof Error && /fetch|network/i.test(err.message) ? NETWORK_ERROR
        : "The answer stopped early. Try asking again.";
      dispatch({ kind: "event", event: { type: "RUN_ERROR", message } });
    }
  }, [agent]);

  const ask = useCallback(async (text: string) => {
    const id = newId();
    dispatch({ kind: "ask", id, text });
    agent.addMessage({ id, role: "user", content: text });
    await run();
  }, [agent, run]);

  const answerApproval = useCallback(async (confirmed: boolean) => {
    const pending = state.pending;
    if (!pending) return;
    dispatch({ kind: "resume" });
    agent.addMessage({ id: newId(), role: "tool", toolCallId: pending.toolCallId,
                       content: JSON.stringify({ confirmed }) });
    await run();
  }, [agent, run, state.pending]);

  const setLocation = useCallback((loc: DeviceLocation | null) => { location.current = loc; }, []);

  return {
    ...state,
    ask,
    approve: () => answerApproval(true),
    deny: () => answerApproval(false),
    setLocation,
    confirmTool: CONFIRM_TOOL,
  };
}
