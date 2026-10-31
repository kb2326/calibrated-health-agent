import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatView, DISCLOSURE } from "@/components/ChatView";
import { friendlyError } from "@/components/ErrorBanner";
import type { RunState, UiMessage } from "@/lib/types";

const user = (text: string): UiMessage => ({ id: "u1", role: "user", text, receipts: [], unbacked: null, incomplete: false });
const bot = (text: string, extra: Partial<UiMessage> = {}): UiMessage =>
  ({ id: "a1", role: "assistant", text, receipts: [], unbacked: null, incomplete: false, ...extra });

function show(state: Partial<RunState>, onOpen = vi.fn(), onAsk = vi.fn()) {
  const full: RunState = { messages: [], steps: [], status: "idle", ...state };
  render(<ChatView state={full} demo={false} onAsk={onAsk} onOpenReceipt={onOpen} locationOn={false}
                   onToggleLocation={() => {}} />);
  return { onOpen, onAsk };
}

describe("ChatView", () => {
  it("renders the streamed answer with receipt chips that open the receipt", () => {
    const { onOpen } = show({ status: "done", messages: [user("Sleep?"),
      bot("You slept **6 h 49 min** [r-4f2a9c1e07].")] });
    expect(screen.getByText("6 h 49 min")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open receipt r-4f2a9c1e07" }));
    expect(onOpen).toHaveBeenCalledWith("r-4f2a9c1e07");
  });

  it("timeline shows each tool step with its status", () => {
    show({ status: "running", messages: [user("Sleep?")], steps: [
      { id: "1", tool: "data_catalog", label: "Checking what data exists", status: "ok" },
      { id: "2", tool: "run_sql", label: "Running a query", status: "running" }] });
    const list = screen.getByRole("list", { name: "Agent at work" });
    expect(within(list).getByText(/Checking what data exists/)).toHaveTextContent("(done)");
    expect(within(list).getByText(/Running a query/)).toHaveTextContent("(in progress)");
  });

  it("an unbacked figure shows as a quiet note, not hidden", () => {
    show({ status: "done", messages: [user("x"), bot("Average 61 bpm.", { unbacked: ["61"] })] });
    expect(screen.getByText(/computed by a tool/)).toHaveTextContent("One figure wasn't computed by a tool: 61");
  });

  it("renders HTML in the answer as text, never as markup", () => {
    const { container } = render(<ChatView state={{ status: "done", steps: [],
      messages: [user("x"), bot('<script>alert(1)</script> and <img src=x onerror="y">')] }}
      demo={false} onAsk={() => {}} onOpenReceipt={() => {}} locationOn={false} onToggleLocation={() => {}} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("model links never become outbound links", () => {
    const { container } = render(<ChatView state={{ status: "done", steps: [],
      messages: [user("x"), bot("See [this](https://evil.example).")] }}
      demo={false} onAsk={() => {}} onOpenReceipt={() => {}} locationOn={false} onToggleLocation={() => {}} />);
    expect(container.querySelector("a")).toBeNull();
    expect(screen.getByText("this")).toBeInTheDocument();
  });

  it("a run error keeps the partial answer, marked incomplete, with plain words", () => {
    show({ status: "error", messages: [user("x"), bot("Over the last week you", { incomplete: true })],
           error: { message: "Monthly chat budget ($0.30) reached; it resets on the 1st.", code: "BUDGET" } });
    expect(screen.getByText("Over the last week you")).toBeInTheDocument();
    expect(screen.getByText(/incomplete/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Monthly chat budget");
  });

  it("explains a quota error in plain words", () => {
    expect(friendlyError({ message: "429 RESOURCE_EXHAUSTED quota" })).toMatch(/busy.*Wait a minute/);
  });

  it("shows the same disclosure as the CLI", () => {
    show({});
    expect(screen.getByText(DISCLOSURE)).toBeInTheDocument();
    expect(DISCLOSURE).toBe("AI agent (Gemini) answering from your own data. It can be wrong and is not " +
      "medical advice; every number has a receipt you can re-run.");
  });

  it("has a polite live region for streaming status", () => {
    show({ status: "running", messages: [user("x")] });
    expect(screen.getByTestId("live")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByTestId("live")).toHaveTextContent("The agent is working");
  });

  it("example questions ask straight away; the form refuses while busy", () => {
    const { onAsk } = show({});
    fireEvent.click(screen.getByRole("button", { name: "How did I sleep this week?" }));
    expect(onAsk).toHaveBeenCalledWith("How did I sleep this week?");
  });
});
