"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";
import type { AnalysisRunResponse, EvidenceRef } from "@/lib/api";
import { chatApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { EvidenceChip } from "@/components/Evidence";
import { Button, EmptyState } from "@/components/ui";

interface ChatWorkspaceProps {
  caseId: string;
  run: AnalysisRunResponse | null;
  onEvidenceSelect?: (ref: EvidenceRef) => void;
}

type ChatRole = "user" | "assistant";
type ChatMessageStatus = "complete" | "streaming" | "error" | "cancelled";

interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  evidenceRefs: EvidenceRef[];
  status: ChatMessageStatus;
  createdAt: number;
}

const QUICK_PROMPTS = [
  "Summarize what changed and why it matters",
  "What is the most likely root cause?",
  "Show the strongest evidence",
  "Draft a customer-safe update",
];

function makeId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export function ChatWorkspace({caseId, onEvidenceSelect, run}: ChatWorkspaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  function updateMessage(
    messageId: string,
    updater: (message: ChatMessage) => ChatMessage,
  ) {
    setMessages((current) =>
      current.map((message) => (message.id === messageId ? updater(message) : message)),
    );
  }

  async function sendMessage() {
    const question = input.trim();
    if (!run) {
      setError("Start an analysis run before asking the copilot.");
      return;
    }
    if (!question || streamingMessageId) {
      return;
    }

    const controller = new AbortController();
    const assistantId = makeId("assistant");
    abortRef.current = controller;
    setError(null);
    setInput("");
    setStreamingMessageId(assistantId);
    setMessages((current) => [
      ...current,
      {
        id: makeId("user"),
        role: "user",
        content: question,
        evidenceRefs: [],
        status: "complete",
        createdAt: Date.now(),
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        evidenceRefs: [],
        status: "streaming",
        createdAt: Date.now(),
      },
    ]);

    try {
      await chatApi.stream(
        {
          message: question,
          case_id: caseId,
          analysis_run_id: run.analysis_run_id,
        },
        {
          delta: (delta) => {
            updateMessage(assistantId, (message) => ({
              ...message,
              content: `${message.content}${delta}`,
            }));
          },
          evidence: (evidenceRefs) => {
            updateMessage(assistantId, (message) => ({...message, evidenceRefs}));
          },
          done: (doneMessage) => {
            updateMessage(assistantId, (message) => ({
              ...message,
              content: message.content || doneMessage,
              status: "complete",
            }));
          },
          error: (messageText) => {
            setError(messageText);
            updateMessage(assistantId, (message) => ({
              ...message,
              content: message.content ? `${message.content}\n${messageText}` : messageText,
              status: "error",
            }));
          },
        },
        controller.signal,
      );
    } catch (caught) {
      if (isAbortError(caught)) {
        updateMessage(assistantId, (message) => ({
          ...message,
          content: message.content || "Cancelled.",
          status: "cancelled",
        }));
      } else {
        const messageText = apiErrorMessage(caught);
        setError(messageText);
        updateMessage(assistantId, (message) => ({
          ...message,
          content: message.content || messageText,
          status: "error",
        }));
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      setStreamingMessageId(null);
    }
  }

  function cancel() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreamingMessageId(null);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  const composerDisabled = !run || Boolean(streamingMessageId);

  return (
    <section className="chat-panel chat-workspace">
      <div className="section-header">
        <div>
          <span className="eyebrow">Incident Copilot</span>
          <h2>Analysis Chat</h2>
        </div>
      </div>

      {messages.length === 0 && (
        <div className="chat-empty">
          <EmptyState title="Ask about this incident">
            Use the latest run context to investigate symptoms, timeline, evidence, and likely root cause.
          </EmptyState>
          <div className="quick-prompts">
            {QUICK_PROMPTS.map((prompt) => (
              <Button
                key={prompt}
                size="sm"
                variant="ghost"
                onClick={() => setInput(prompt)}
              >
                {prompt}
              </Button>
            ))}
          </div>
        </div>
      )}

      <div className="message-list chat-scroll" ref={scrollRef}>
        {messages.map((message) => (
          <article className={`message-row chat-message ${message.role}`} key={message.id}>
            <div className="message-bubble chat-bubble">
              {message.content || (
                <span className="muted">
                  {message.status === "streaming" ? "Thinking…" : "No response"}
                </span>
              )}
            </div>
            <div className="message-meta">
              {message.status !== "complete" && (
                <span className={`message-status ${message.status}`}>
                  {message.status}
                </span>
              )}
            </div>
            {message.role === "assistant" && message.evidenceRefs.length > 0 && (
              <div className="chat-evidence evidence-list">
                {message.evidenceRefs.map((refItem) => (
                  <EvidenceChip
                    key={`${refItem.log_id}-${refItem.line_number}`}
                    refItem={refItem}
                    onClick={onEvidenceSelect}
                  />
                ))}
              </div>
            )}
          </article>
        ))}
      </div>

      {error && <div className="alert error compact">{error}</div>}
      {!run && (
        <p className="field-hint">Start an analysis run before asking the copilot.</p>
      )}

      <form
        className="composer chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void sendMessage();
        }}
      >
        <textarea
          aria-label="Ask the incident copilot"
          className="composer-input"
          disabled={composerDisabled}
          placeholder="Ask about this incident, logs, timeline, or likely root cause…"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <div className="composer-actions chat-composer-actions">
          {streamingMessageId ? (
            <Button variant="secondary" onClick={cancel}>
              Cancel
            </Button>
          ) : (
            <Button disabled={!input.trim() || !run} type="submit">
              Ask
            </Button>
          )}
        </div>
      </form>
    </section>
  );
}
