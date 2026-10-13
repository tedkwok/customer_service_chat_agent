import { useMemo, useRef, useState } from "react";
import { HttpAgent } from "@ag-ui/client";
import type { Message } from "@ag-ui/core";
import { loadSession } from "../auth";
import { RenderToolComponent } from "../components/RenderComponents";

// Chat page driven by the AG-UI protocol client (CopilotKit's agent protocol).
// HttpAgent POSTs a RunAgentInput to the backend `/stream/{customer_id}`
// endpoint and consumes the SSE event stream: TEXT_MESSAGE_* events stream the
// assistant reply; TOOL_CALL_* events for the render_* tools are the
// generative-UI channel — the agent "designs" a component by calling the tool
// with facts, and we render the bound React component here.
type ChatItem =
  | { kind: "text"; id: string; role: "user" | "assistant"; content: string }
  | { kind: "tool"; id: string; name: string; args: string; parsed?: Record<string, unknown> };

function parseArgs(raw: string): Record<string, unknown> | undefined {
  try {
    const value = JSON.parse(raw || "{}");
    return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}

export default function Chat() {
  // Captured once so the memoized agent below is not rebuilt every render.
  const [session] = useState(() => loadSession());
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  // One agent per customer; threadId keeps the backend checkpointer thread
  // (and therefore conversation memory) tied to this customer.
  const agent = useMemo(() => {
    if (!session) return null;
    return new HttpAgent({
      agentId: "customer_service",
      description: "Meridian Store customer service agent",
      url: `/stream/${session.customer_id}`,
      threadId: session.customer_id,
    });
  }, [session]);

  if (!session || !agent) return null;

  const appendText = (role: "assistant", id: string, content: string) =>
    setItems((prev) => [...prev, { kind: "text", id, role, content }]);

  const send = async () => {
    const text = input.trim();
    if (!text || running) return;
    setInput("");
    const messageId = crypto.randomUUID();
    setItems((prev) => [...prev, { kind: "text", id: messageId, role: "user", content: text }]);
    // The AG-UI client ships the full thread in RunAgentInput; the backend
    // extracts the newest user message and continues the thread.
    const message: Message = { id: messageId, role: "user", content: text };
    agent.messages.push(message);
    setRunning(true);
    try {
      await agent.runAgent(
        {},
        {
          onTextMessageStartEvent: ({ event }) =>
            appendText("assistant", event.messageId, ""),
          onTextMessageContentEvent: ({ event }) =>
            setItems((prev) =>
              prev.map((it) =>
                it.kind === "text" && it.id === event.messageId
                  ? { ...it, content: it.content + event.delta }
                  : it,
              ),
            ),
          onToolCallStartEvent: ({ event }) =>
            setItems((prev) => [
              ...prev,
              { kind: "tool", id: event.toolCallId, name: event.toolCallName, args: "" },
            ]),
          onToolCallArgsEvent: ({ event }) =>
            setItems((prev) =>
              prev.map((it) =>
                it.kind === "tool" && it.id === event.toolCallId
                  ? { ...it, args: it.args + event.delta }
                  : it,
              ),
            ),
          onToolCallEndEvent: ({ event }) =>
            setItems((prev) =>
              prev.map((it) =>
                it.kind === "tool" && it.id === event.toolCallId
                  ? { ...it, parsed: parseArgs(it.args) }
                  : it,
              ),
            ),
          onRunErrorEvent: ({ event }) =>
            appendText("assistant", crypto.randomUUID(), `⚠️ ${event.message ?? "agent error"}`),
        },
      );
    } catch (err) {
      appendText("assistant", crypto.randomUUID(), `⚠️ ${String(err)}`);
    } finally {
      setRunning(false);
      requestAnimationFrame(() => listRef.current?.scrollTo(0, listRef.current.scrollHeight));
    }
  };

  return (
    <div className="card chat-card">
      <h1>Customer service chat</h1>
      <p className="chat-hint">
        Signed in as <strong>{session.customer_id}</strong> — answers are grounded in the store
        documents and your live records. Purchases, refunds and membership changes are confirmed
        before they are executed.
      </p>
      <div className="chat-log" ref={listRef}>
        {items.length === 0 && (
          <div className="chat-bubble assistant">
            Hi! I&apos;m the Meridian Store assistant. Ask me about products, your membership or
            balance, or start a purchase or refund.
          </div>
        )}
        {items.map((it) =>
          it.kind === "text" ? (
            <div key={it.id} className={`chat-bubble ${it.role}`}>
              {it.content || "…"}
            </div>
          ) : (
            <div key={it.id} className="chat-tool">
              <RenderToolComponent name={it.name} args={it.parsed} />
            </div>
          ),
        )}
        {running && <div className="chat-bubble assistant chat-typing">Working…</div>}
      </div>
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. What wireless headphones do you have in stock?"
          disabled={running}
        />
        <button type="submit" disabled={running || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
